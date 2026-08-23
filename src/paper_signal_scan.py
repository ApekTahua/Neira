"""paper_signal_scan.py -- once-daily EOD job for the live V3 paper-trading
engine. Runs after IDX close (~18:10 WIB, right after the existing 18:00
WIB screener slot that already reliably has fresh ihsg_eod data --
.github/workflows/run_screener.yml).

Responsibilities:
  1. Reconcile OPEN positions against today's true EOD bar: CHECKPOINT/
     TIME exits (day-granularity concepts the original engine only
     checks once per day), plus a safety-net recheck of SL/TP1/TRAILING
     using ihsg_eod's real daily high/low, in case paper_monitor.py's
     15-min intraday polling missed a brief spike between polls.
  2. Increment hold_days for positions that didn't exit today.
  3. Recompute regime/thresholds over full history through today and
     queue today's new PENDING candidates -- filled at tomorrow's open
     by paper_monitor.py. Uses the exact same score_candidates() the
     backtest uses (src/backtest_v4.py) -- zero drift.
  4. Snapshot today's EOD equity (real drawdown_pct off the running peak,
     not a placeholder), update the backtest_runs summary row (including
     max_drawdown and cvar_95, the latter once 20+ days of history exist).
  5. Score the full liquid universe (not just today's qualifying
     candidates) into daily_scoreboard -- display only, read by the
     frontend for ticker search, never read back into trading decisions.
  6. Telegram notification.

Governance: frozen configuration -- see docs/V3_FINDINGS_LOG.md "Live
paper trading" section and paper_common.py's module docstring. Does not
modify config.py, screener.py, backtest.py, strategy.py, or notifier.py
(V1 live files).

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/paper_signal_scan.py
"""

import os
import sys
from datetime import date, datetime, timezone

import numpy as np

os.environ.setdefault("V4_TEST_END", date.today().isoformat())

import config as cfg  # noqa: E402
import backtest_v4 as bt  # noqa: E402
import paper_common as pc  # noqa: E402
from db_retry import retry as _retry  # noqa: E402
from supabase import create_client  # noqa: E402

LOT_SIZE = bt.LOT_SIZE

# Trading sessions a PENDING order may go unfilled before it's cancelled and
# its position slot released -- see the expiry block in main(). 2 sessions is
# deliberately short: the entry edge is a next-open effect, so a candidate
# that couldn't be bought for two straight sessions is a stale signal, not a
# patient order.
PENDING_EXPIRY_SESSIONS = 2


def _position_dict_from_row(row: dict) -> dict:
    """paper_positions columns -> the dict shape evaluate_position_exit()
    expects (same keys backtest_v4's own position dicts use)."""
    return {
        "stock_code": row["stock_code"],
        "entry_date": date.fromisoformat(row["entry_date"]) if row["entry_date"] else None,
        "avg_price": float(row["avg_price"]),
        "tp1_price": float(row["tp1_price"]),
        "sl_price": float(row["sl_price"]),
        "total_lots": int(row["total_lots"]),
        "remaining_lots": int(row["remaining_lots"]),
        "cost_basis": float(row["cost_basis"]),
        "hold_days": int(row["hold_days"]),
        "tp1_hit": bool(row["tp1_hit"]),
        "tp2_hit": bool(row["tp2_hit"]),
        "highest_price": float(row["highest_price"]) if row["highest_price"] is not None else float(row["avg_price"]),
        "trigger": row["trigger"],
        "checkpoint_day": row["checkpoint_day"],
        "target_price": float(row["target_price"]) if row["target_price"] is not None else None,
        "entry_price_original": float(row["entry_price_original"]) if row["entry_price_original"] is not None else float(row["avg_price"]),
        "atr_at_entry": float(row["atr_at_entry"]) if row["atr_at_entry"] is not None else None,
        # For evaluate_position_exit's slippage participation math (only active when
        # SLIPPAGE_ENABLED, off by default -- see config.py). Omitted before, silently
        # falling back to that function's own default of 1.0. paper_positions.avg_vol_20
        # is populated at signal time (see the paper_positions.insert() call below).
        "avg_vol_20": float(row["avg_vol_20"]) if row.get("avg_vol_20") is not None else 1.0,
    }


def _persist_position(supabase, position_id: int, pos: dict, day_high=None, day_low=None) -> None:
    payload = {
        "avg_price": pos["avg_price"], "tp1_price": pos["tp1_price"], "sl_price": pos["sl_price"],
        "total_lots": pos["total_lots"], "remaining_lots": pos["remaining_lots"], "cost_basis": pos["cost_basis"],
        "hold_days": pos["hold_days"], "tp1_hit": pos["tp1_hit"], "tp2_hit": pos["tp2_hit"],
        "highest_price": pos["highest_price"],
    }
    if day_high is not None:
        payload["day_high"] = day_high
    if day_low is not None:
        payload["day_low"] = day_low
    # Retry-safe: every field in `payload` is an absolute snapshot of `pos`/
    # day_high/day_low keyed by this row's own id, not a delta -- a replayed
    # write after a lost response re-applies the same final state.
    _retry(lambda: supabase.table("paper_positions").update(payload).eq("id", position_id).execute())


def _close_position(supabase, run_id: int, position_id: int, pos: dict, trade_record: dict) -> None:
    # Retry-safe: absolute overwrite keyed by this row's own id.
    _retry(lambda: supabase.table("paper_positions").update({
        "status": "CLOSED", "remaining_lots": pos["remaining_lots"],
        "exit_date": trade_record["exit_date"].isoformat(), "exit_price": trade_record["exit_price"],
        "exit_reason": trade_record["exit_reason"], "pnl": trade_record["pnl"], "pnl_pct": trade_record["pnl_pct"],
        "hold_days": trade_record["hold_days"],
        "exited_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", position_id).execute())
    # Deliberately NOT wrapped in retry: bare INSERT with no idempotency key
    # (no unique constraint on run_id/stock_code/exit_date etc in
    # sql/paper_trading_schema.sql -- backtest_trades predates that file and
    # isn't defined there at all). If the first attempt actually succeeded
    # server-side and only the response was lost to a transient blip, a
    # retry would silently create a second identical backtest_trades row for
    # the same exit, double-counting this trade in win-rate/profit-factor/
    # frontend charts -- worse than the status quo (an uncaught exception
    # here crashes the run, run_guarded() alerts, and the next scan picks up
    # cleanly since paper_positions is already CLOSED). Same reasoning as
    # paper_monitor.py's identical backtest_trades.insert() call.
    supabase.table("backtest_trades").insert({
        "run_id": run_id, "stock_code": trade_record["stock_code"],
        "entry_date": trade_record["entry_date"].isoformat(), "exit_date": trade_record["exit_date"].isoformat(),
        "entry_price": float(trade_record["entry_price"]), "exit_price": float(trade_record["exit_price"]),
        "lots": int(trade_record["lots"]), "pnl": float(trade_record["pnl"]), "pnl_pct": float(trade_record["pnl_pct"]),
        "exit_reason": trade_record["exit_reason"], "trigger": trade_record["trigger"],
        "hold_days": int(trade_record["hold_days"]),
    }).execute()


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    if not pc.is_idx_trading_day(date.today()):
        print(f"[SCAN] {date.today().isoformat()} is not an IDX trading day -- skipping.")
        return

    latest_res = _retry(lambda: supabase.table("ihsg_eod").select("trade_date").order("trade_date", desc=True).limit(1).execute())
    if not latest_res.data:
        sys.exit("ihsg_eod is empty -- nothing to scan.")
    today = date.fromisoformat(latest_res.data[0]["trade_date"])

    run_id = pc.get_paper_run_id(supabase)
    acct_res = _retry(lambda: supabase.table("paper_account").select("*").eq("run_id", run_id).limit(1).execute())
    if not acct_res.data:
        sys.exit(f"No paper_account row for run_id={run_id} -- run sql/paper_trading_schema.sql's seed first.")
    account = acct_res.data[0]
    cash = float(account["cash"])
    last_signal_date = date.fromisoformat(account["last_signal_date"]) if account["last_signal_date"] else None

    if last_signal_date == today:
        print(f"[SKIP] Already processed {today} (last_signal_date matches). Nothing to do.")
        return

    print(f"[SCAN] {today} -- run_id={run_id}, cash=Rp{cash:,.0f}")
    print("[FETCH] Building full dataset through today (add_features/sector-RS/weekly-trend) ...")
    df, idx_df = bt.build_full_dataset(supabase)
    regime_by_date, bullish_streak_by_date, trend_strength_by_date = bt.compute_regime_with_hysteresis(idx_df)
    regime = regime_by_date.get(today, "NEUTRAL")
    trend_strength = trend_strength_by_date.get(today, 0.0)

    open_res = _retry(lambda: (
        supabase.table("paper_positions").select("*").eq("run_id", run_id).eq("status", "OPEN").execute()
    ))
    open_positions = open_res.data
    today_bars = df[df["trade_date"] == today].set_index("stock_code")
    # Previous trading day's close per stock, for the corporate-action guard
    # below -- cheap, one groupby over the full history already in memory.
    prev_close_by_stock = (
        df[df["trade_date"] < today].sort_values("trade_date").groupby("stock_code")["close_price"].last()
    )
    # Cost-basis proxy for total equity (used only to size the optional
    # pyramid add-on tranche, not any exit/risk decision) -- a true
    # mark-to-market figure would need a running valuation ledger this
    # v1 doesn't maintain; slightly conservative (ignores unrealized
    # gains) but immaterial to correctness of exits.
    prev_equity = cash + sum(float(p["cost_basis"]) for p in open_positions)

    # ---- Expire stale PENDING orders (suspended / ARA-locked / no print) ----
    # paper_monitor.py refuses to fill a candidate whose ihsg_realtime `open`
    # is 0 -- correct (a suspended or auto-reject-locked ticker has no real
    # tradeable open, and inventing one would fake a fill that could never
    # happen). But nothing ever cancelled those orders, so a ticker that
    # stays suspended squats one of MAX_POSITIONS slots indefinitely: BAJA
    # queued 2026-08-03 hit ARA, went volume=0/open=0, and held a slot with
    # no way to ever fill or expire. Real brokers expire an unfilled day
    # order; this does the same.
    #
    # Deliberately NOT a strategy change under the frozen-config rule: it
    # never alters which ticker is chosen, at what price, or with what size
    # -- an expired order is one that was never fillable in the first place.
    # It only stops dead orders from starving live ones of slots.
    stale_pending = _retry(lambda: (
        supabase.table("paper_positions").select("*").eq("run_id", run_id).eq("status", "PENDING")
        .lt("signal_date", today.isoformat()).execute()
    )).data
    for row in stale_pending:
        signal_day = date.fromisoformat(row["signal_date"])
        sessions_waited = pc.trading_days_elapsed(supabase, signal_day, today)
        if sessions_waited < PENDING_EXPIRY_SESSIONS:
            continue
        # Retry-safe: absolute overwrite keyed by this row's own id.
        _retry(lambda: supabase.table("paper_positions").update({
            "status": "CLOSED", "exit_date": today.isoformat(), "exit_reason": "UNFILLED_EXPIRED",
            "pnl": 0, "pnl_pct": 0, "exited_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row["id"]).execute())
        # No backtest_trades row on purpose: nothing was ever bought or sold,
        # so counting it as a trade would pollute win-rate/profit-factor with
        # a phantom breakeven.
        msg = (f"\U0001F6AB *EXPIRED* {row['stock_code']} -- queued {row['signal_date']}, never filled after "
               f"{sessions_waited} session(s) (suspended / no valid open). Slot released.")
        print(f"[EXPIRE] {msg}")
        pc.notify(msg)

    new_candidates_notes = []
    # Tracks whether any position actually closed (fully or TP1-partially)
    # today -- used below to quiet the routine EOD summary for a retired
    # run (pc.RETIRED_PAPER_VERSIONS) on a day where nothing happened to its
    # remaining open positions. EXPIRE/corp-action-guard messages above/below
    # this loop already notify immediately on their own and are untouched --
    # this only gates the final combined summary.
    had_exit_today = False
    for row in open_positions:
        if row["entry_date"] == today.isoformat():
            continue  # filled today by paper_monitor.py -- don't exit-check same-day, matches backtest_v4.py's own guard

        # A suspended stock still gets an EOD row on some feeds -- open=high=low=0 with
        # close frozen at the last real print (DOOH, 2026-08-06: exactly this shape).
        # Without this check that row reached evaluate_position_exit as a real bar,
        # low=0 <= any sl_price trivially, and DOOH "sold" at price 0 for a fabricated
        # -100% loss -- a real production incident, not a hypothetical.
        #
        # This is deliberately keyed off close_price/volume, NOT open_price>0. Audited
        # 2026-08-18: ~25% of actively-traded stocks on a normal day have open_price=0
        # in ihsg_eod (an upstream data-quality gap, not a real halt) while close/high/
        # low/volume are all real -- WMPP (a currently-OPEN live position) has
        # open_price=0 on every historical row despite trading normally. Gating "did
        # this stock trade today" on open_price>0 would misclassify WMPP as delisted
        # forever, permanently freezing last_valid_close and eventually force-exiting
        # it via DELISTING_GAP_DAYS on a stock that never stopped trading. close_price
        # and volume are the real "did it trade" signal; open_price>0 stays required
        # only where a fill genuinely needs a real opening print (paper_monitor.py's
        # order-fill guard, ~line 202, and the `open_val` mask a few lines below, which
        # keeps a fictional 0 open out of evaluate_position_exit's SL/TP1 gap-fill price
        # selection without weakening the DOOH-style suspension check this comment
        # describes -- that check already runs on close/high/low, not open).
        had_real_trade = (
            row["stock_code"] in today_bars.index
            and float(today_bars.loc[row["stock_code"]]["close_price"]) > 0
            and float(today_bars.loc[row["stock_code"]]["volume"] or 0) > 0
        )
        if not had_real_trade:
            # No real trading today -- suspension, ARA-lock with no print, or delisting.
            # Same DELISTING_GAP_DAYS force-exit the backtest applies (src/backtest_v4.py's
            # simulate_window "no bar found" branch): without this, a delisted position
            # would sit open forever, frozen at its last mark-to-market price, never
            # contributing its real loss.
            no_data_days = int(row["no_data_days"]) + 1
            hold_days = int(row["hold_days"]) + 1
            if no_data_days >= bt.DELISTING_GAP_DAYS and row["last_valid_close"] is not None:
                exit_price = float(row["last_valid_close"])
                remaining_lots = int(row["remaining_lots"])
                sell_qty = remaining_lots * LOT_SIZE
                gross_return = exit_price * sell_qty
                fee = gross_return * cfg.SELL_FEE
                net_return = gross_return - fee
                pnl = net_return - float(row["cost_basis"])
                pnl_pct = (exit_price / float(row["avg_price"]) - 1) * 100
                cash += net_return
                trade_record = {
                    "stock_code": row["stock_code"], "entry_date": date.fromisoformat(row["entry_date"]),
                    "exit_date": today, "entry_price": float(row["avg_price"]), "exit_price": exit_price,
                    "lots": remaining_lots, "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": "DELISTED_GAP",
                    "trigger": row["trigger"], "hold_days": hold_days,
                }
                _close_position(supabase, run_id, row["id"], {"remaining_lots": 0}, trade_record)
                had_exit_today = True
                print(f"  [EOD-RECONCILE] {row['stock_code']}: DELISTED_GAP (no print for {no_data_days}d) pnl={pnl:+,.0f}")
            else:
                # Retry-safe: both fields are Python-computed absolute values
                # (prior value + 1), keyed by this row's own id.
                _retry(lambda: supabase.table("paper_positions").update({"no_data_days": no_data_days, "hold_days": hold_days}).eq("id", row["id"]).execute())
            continue

        bar_row = today_bars.loc[row["stock_code"]]
        # open_price==0 on a day with a real close/volume print is the data-quality gap
        # described above (WMPP etc), not a real opening trade at Rp0 -- mask it to None
        # so evaluate_position_exit's own documented None-handling (falls back to
        # sl_price/tp1_price for the gap-fill price, see that function's SL/TP1 branches)
        # kicks in instead of feeding it a fabricated Rp0 "gap-through" fill price.
        raw_open = float(bar_row["open_price"])
        open_val = raw_open if raw_open > 0 else None
        bar = (open_val, float(bar_row["close_price"]), float(bar_row["high"]), float(bar_row["low"]))

        prev_close = prev_close_by_stock.get(row["stock_code"])
        if pc.looks_like_unadjusted_corporate_action(prev_close, bar[1]):
            msg = (f"⚠️ *{row['stock_code']}*: close Rp{bar[1]:,.0f} vs prev Rp{prev_close:,.0f} "
                   f"looks like an unadjusted split/corporate action -- SKIPPING SL/TP check today, "
                   f"please verify and correct avg_price/sl_price/tp1_price manually.")
            print(f"  [CORP-ACTION-GUARD] {msg}")
            pc.notify(msg)
            hold_days = int(row["hold_days"]) + 1
            # Retry-safe: absolute value keyed by this row's own id.
            _retry(lambda: supabase.table("paper_positions").update({"hold_days": hold_days}).eq("id", row["id"]).execute())
            continue

        pos = _position_dict_from_row(row)
        trade_record, cash_delta = bt.evaluate_position_exit(pos, bar, regime, trend_strength, today, prev_equity, cash)
        cash += cash_delta

        if trade_record is not None:
            if trade_record["exit_reason"] == "TP1":
                # Partial exit only -- TP1_PCT of remaining_lots sold, position
                # rides on. Mirrors paper_monitor.py's own TP1 branch (~line
                # 302-311): update the position's bookkeeping fields in place
                # (already mutated onto `pos` by evaluate_position_exit --
                # avg_price, sl_price, total_lots, remaining_lots, cost_basis,
                # tp1_hit) and leave status="OPEN". Do NOT call _close_position
                # (that unconditionally sets status="CLOSED", wrongly liquidating
                # the other 90% of lots) and do NOT insert a backtest_trades row
                # -- same as paper_monitor.py's TP1 branch, a "trade" for win-
                # rate/profit-factor purposes is the position's eventual full
                # exit, not each partial leg.
                #
                # hold_days is deliberately NOT incremented here: neither
                # paper_monitor.py's TP1 branch nor simulate_window's own TP1
                # continuation (src/backtest_v4.py, the
                # `if trade_record["exit_reason"] == "TP1": remaining_positions.
                # append(pos)` branch, which skips the `pos["hold_days"] += 1`
                # that only runs in the `else` branch below it) increments
                # hold_days on the TP1 day itself.
                _persist_position(supabase, row["id"], pos)
                # Retry-safe: absolute overwrite keyed by this row's own id.
                _retry(lambda: supabase.table("paper_positions").update({
                    "tp1_at": datetime.now(timezone.utc).isoformat(),
                    "no_data_days": 0, "last_valid_close": bar[1],
                }).eq("id", row["id"]).execute())
                had_exit_today = True
                print(f"  [EOD-RECONCILE] {trade_record['stock_code']}: TP1 (partial, {pos['remaining_lots']} "
                      f"lot(s) remaining OPEN) pnl={trade_record['pnl']:+,.0f}")
            else:
                _close_position(supabase, run_id, row["id"], pos, trade_record)
                had_exit_today = True
                print(f"  [EOD-RECONCILE] {trade_record['stock_code']}: {trade_record['exit_reason']} "
                      f"pnl={trade_record['pnl']:+,.0f}")
            continue

        pos["hold_days"] += 1
        _persist_position(supabase, row["id"], pos)
        # Retry-safe: absolute overwrite keyed by this row's own id.
        _retry(lambda: supabase.table("paper_positions").update({"no_data_days": 0, "last_valid_close": bar[1]}).eq("id", row["id"]).execute())

    # ---- New candidates for tomorrow's open ----
    train_liquid_bullish = df[
        (df["trade_date"] <= today)
        & (df["adtv_20"] >= cfg.ADTV_MIN)
        & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
        & (df["trade_date"].map(regime_by_date).fillna("NEUTRAL") == "BULLISH")
        & (df["trade_date"].map(bullish_streak_by_date).fillna(0) >= bt.REGIME_CONFIRM_DAYS)
        & (df["trade_date"].map(trend_strength_by_date).fillna(0.0) >= bt.TREND_STRENGTH_MIN)
        & df["atr_14"].notna() & (df["atr_14"] > 0)
        & ((df["atr_14"] / df["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
    ]
    weekly_cut = train_liquid_bullish["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
    sector_cut = train_liquid_bullish["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)
    # Live analog of simulate_window's own weekly_comp_abs_cap block -- same train-derived,
    # applied-out-of-sample methodology as weekly_cut/sector_cut above. None (default, the
    # frozen V3_PAPER run) => no-op, score_candidates behaves exactly as before.
    weekly_comp_abs_cap = None
    if bt.SCORE_WEEKLY_COMP_ABS_CAP_Q is not None:
        train_w_comp = (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        if len(train_w_comp) > 0:
            weekly_comp_abs_cap = train_w_comp.quantile(bt.SCORE_WEEKLY_COMP_ABS_CAP_Q)
    # Refreshed daily and persisted (paper_account.log_adtv_p90) so paper_monitor.py can
    # fill entries with the exact same LIQ_SIZING reference without rebuilding the full
    # dataset every 15 minutes -- see compute_entry_fill()'s docstring in backtest_v4.py.
    train_log_adtv = np.log(train_liquid_bullish["adtv_20"].clip(lower=1))
    log_adtv_p90 = train_log_adtv.quantile(0.90) if len(train_log_adtv) > 0 else 1.0
    if not np.isfinite(log_adtv_p90) or log_adtv_p90 <= 0:
        log_adtv_p90 = 1.0

    # Same persist-and-reread pattern as log_adtv_p90 above, for
    # BANDAR_SIZING_ENABLED (docs/BANDARMOLOGY_DESIGN.md). Without this,
    # paper_monitor.py would fall back to compute_entry_fill's default
    # concentration_p90=1.0 -- the wrong reference (raw concentration
    # values, not the 90th-percentile-of-train ratio the multiplier is
    # supposed to divide by) -- silently mis-sizing every V4_PAPER fill.
    train_concentration = train_liquid_bullish["concentration"].dropna()
    concentration_p90 = train_concentration.quantile(0.90) if len(train_concentration) > 0 else 1.0
    if not np.isfinite(concentration_p90) or concentration_p90 <= 0:
        concentration_p90 = 1.0

    regime_ok = (regime == "BULLISH" and bullish_streak_by_date.get(today, 0) >= bt.REGIME_CONFIRM_DAYS
                 and trend_strength >= bt.TREND_STRENGTH_MIN)

    # ---- Real daily qualifying-signal list (the actual trade-entry gate) --
    # hoisted here so it's computed whenever regime_ok is true, independent of
    # slots_free/max_new/stop_new_entries below. Those are portfolio-capacity/
    # retirement concerns ("how many can we buy"), a different question from
    # "how many pass the entry gate today" -- computing this only inside the
    # slots-free branch (as before) would wrongly answer "0 qualify" on a day
    # a full portfolio just had no room, when the real answer might be "5
    # qualify, 0 slots free". Reused verbatim by the queueing loop below --
    # same inputs (day_data/weekly_cut/sector_cut/weekly_comp_abs_cap) at the
    # same point in the flow as the old inline call, so zero drift in what
    # actually gets queued.
    scored = []
    if regime_ok:
        day_data = df[df["trade_date"] == today]
        scored = bt.score_candidates(day_data, weekly_cut, sector_cut, top_n=15,
                                      weekly_comp_abs_cap=weekly_comp_abs_cap)

    # ---- Full-universe daily scoreboard (display only -- never read back
    # into trading decisions, see docs/V3_FINDINGS_LOG.md "NEXT ENHANCEMENT") ----
    train_scores = (
        (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        + (train_liquid_bullish["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
    )
    score_p90 = train_scores.quantile(0.90) if len(train_scores) > 0 else 1.0
    if not np.isfinite(score_p90) or score_p90 <= 0:
        score_p90 = 1.0
    scoreboard = bt.score_full_universe(df[df["trade_date"] == today], weekly_cut, sector_cut, score_p90, regime_ok)

    # Persist the actual thresholds applied today so the frontend can show a
    # real per-gate pass/fail breakdown for any ticker instead of only the
    # final label -- see daily_gate_summary_schema.sql. Written even when
    # regime_ok is False / scoreboard is empty, since "why is everything
    # WAIT today" is exactly the case this needs to answer too.
    # Retry-safe: upsert on an explicit on_conflict target -- replaying the
    # same write after a lost response re-applies the identical row.
    _retry(lambda: supabase.table("daily_gate_summary").upsert({
        "trade_date": today.isoformat(), "regime": regime,
        "bullish_streak": int(bullish_streak_by_date.get(today, 0)),
        "trend_strength": float(trend_strength), "regime_ok": bool(regime_ok),
        "weekly_cut": float(weekly_cut), "sector_cut": float(sector_cut),
        "score_p90": float(score_p90), "atr_ratio_max": float(bt.ATR_PRICE_RATIO_MAX),
        "adtv_min": float(cfg.ADTV_MIN),
    }, on_conflict="trade_date").execute())

    if scoreboard:
        # Retry-safe: same reasoning -- upsert on an explicit on_conflict target.
        _retry(lambda: supabase.table("daily_scoreboard").upsert([{
            "trade_date": today.isoformat(), "stock_code": row["stock_code"], "score": row["score"],
            "label": row["label"], "percentile": row["percentile"], "weekly_ma_spread": row["weekly_ma_spread"],
            "sector_rs_momentum": row["sector_rs_momentum"], "close_price": row["close_price"],
            "adtv_20": row["adtv_20"], "atr_14": row["atr_14"],
        } for row in scoreboard], on_conflict="trade_date,stock_code").execute())
        print(f"[SCOREBOARD] {len(scoreboard)} tickers scored for {today}")

    # ---- Real qualifying-signal list, persisted for the public Screener page
    # (docs/V3_FINDINGS_LOG.md "why the Screener page never shows fewer than
    # ~90 signals" -- daily_scoreboard above is a ticker-lookup table that
    # deliberately never drops a row, not the real selectivity answer).
    # Only the primary engine's output is public-facing: V3_PAPER/V3.1_PAPER
    # run different filter env vars (V4_ARA_FILTER, V4_ATR_PRICE_RATIO_MAX,
    # V4_SCORE_WEEKLY_COMP_ABS_CAP_Q) that make their `scored` NOT the same
    # computation as V4_PAPER's -- writing theirs here would silently swap
    # the public count depending on which of the three workflows ran last.
    # Full delete-then-insert per trade_date (not a plain upsert) so a stock
    # that qualified on an earlier run for the same date but not this one
    # doesn't linger -- see the "full day replace, not accumulate" note in
    # the task. Purely additive: no read-back into score_candidates,
    # compute_entry_fill, or the paper_positions queueing loop below.
    if pc.PAPER_VERSION == pc.PRIMARY_PAPER_VERSION:
        _retry(lambda: supabase.table("daily_qualifying_signals").delete().eq("trade_date", today.isoformat()).execute())
        if scored:
            _retry(lambda: supabase.table("daily_qualifying_signals").upsert([{
                "trade_date": today.isoformat(), "stock_code": sig["stock_code"], "rank": i + 1,
                "score": sig["score"], "trigger": sig["trigger"], "adtv_20": sig["adtv_20"],
                "avg_vol_20": sig["avg_vol_20"], "atr": sig["atr"], "signal_close": sig["signal_close"],
                "tp_target": sig["tp_target"], "concentration": sig.get("concentration"),
            } for i, sig in enumerate(scored)], on_conflict="trade_date,stock_code").execute())
            print(f"[QUALIFYING] {len(scored)} candidates passed the real entry gate for {today}")

    candidates = []
    # V3.1_PAPER stopped opening NEW positions 2026-08-14, and V3_PAPER got
    # the same treatment 2026-08-15 (user: "Retire beneran, V4 doang" --
    # confused why V3/V3.1 both still existed when V4 alone was enough).
    # Confirmed via real GitHub Actions run history that V3_PAPER was still
    # firing daily, unchanged, alongside V3.1_PAPER and V4_PAPER (the
    # original "why 3 Telegram notifications" complaint was never actually
    # fixed). This is NOT a retroactive edit to either run's own exit rules:
    # everything above this line (stale-PENDING expiry, open-position exit
    # checks) still runs exactly as before for their existing positions,
    # same governance rule this project already enforces everywhere else --
    # a frozen run's already-open positions ride to their own natural exit,
    # never mutated mid-flight. Only which engine gets NEW capital changes.
    # New signals now come from V4_PAPER alone -- see
    # paper_common.RETIRED_PAPER_VERSIONS (single source of truth, in case
    # a future script besides this one ever needs the same check).
    stop_new_entries = pc.PAPER_VERSION in pc.RETIRED_PAPER_VERSIONS
    if regime_ok and not stop_new_entries:
        # Both OPEN and PENDING count against MAX_POSITIONS -- a queued but
        # unfilled order still occupies a slot -- and both must be checked
        # per-ticker below too. Bug found 2026-08-05: the per-ticker dedup
        # used to check only `open_positions` (status='OPEN'), so a stock
        # already PENDING from a prior day's signal (not yet filled, not yet
        # expired) could still get queued a SECOND time -- SMLE was queued
        # both 2026-08-03 and 2026-08-05 simultaneously before this fix.
        open_and_pending = _retry(lambda: supabase.table("paper_positions").select("id, stock_code").eq("run_id", run_id).in_(
            "status", ["OPEN", "PENDING"]
        ).execute()).data
        open_count = len(open_and_pending)
        already_queued_codes = {p["stock_code"] for p in open_and_pending}
        slots_free = max(0, bt.MAX_POSITIONS - open_count)
        max_new = min(slots_free, bt.MAX_NEW_ENTRIES_PER_DAY)
        if max_new > 0:
            # `scored` already computed above (hoisted so it runs whenever
            # regime_ok is true, not just when a slot happens to be free) --
            # reused verbatim here, identical to the old inline call.
            for sig in scored:
                if len(candidates) >= max_new:
                    break
                if sig["stock_code"] in already_queued_codes:
                    continue
                sl_res = _retry(lambda: (
                    supabase.table("paper_positions").select("exit_date")
                    .eq("run_id", run_id).eq("stock_code", sig["stock_code"]).eq("exit_reason", "SL")
                    .order("exit_date", desc=True).limit(1).execute()
                ))
                if sl_res.data:
                    since = date.fromisoformat(sl_res.data[0]["exit_date"])
                    if pc.trading_days_elapsed(supabase, since, today) < cfg.COOLDOWN_DAYS:
                        continue
                candidates.append(sig)

            for sig in candidates:
                # tp1_price/sl_price/lots are NOT computed here -- compute_entry_fill()
                # needs the actual FILL price (tomorrow's open), not today's signal close.
                # paper_monitor.py fills this row and computes all of that at execution
                # time. signal_close is kept only for the gap-check at fill time.
                #
                # Deliberately NOT wrapped in retry: bare INSERT, no unique constraint
                # on (run_id, stock_code, signal_date) or similar in
                # sql/paper_trading_schema.sql (paper_positions' only unique column is
                # its own serial id). If the first attempt actually succeeded server-side
                # and only the response was lost, a retry would silently queue a second
                # PENDING row for the same ticker -- the already_queued_codes dedup above
                # only guards against re-scanning the SAME candidates list this run, not
                # against a duplicate created by retrying this exact insert, and
                # paper_monitor.py has no dedup of its own at fill time, so it would
                # double-fill (double real capital deployed to one ticker on one signal).
                # Same insert-safety reasoning as backtest_trades.insert() above.
                supabase.table("paper_positions").insert({
                    "run_id": run_id, "stock_code": sig["stock_code"], "status": "PENDING",
                    "signal_date": today.isoformat(), "trigger": sig["trigger"], "score": sig["score"],
                    "adtv_20": sig["adtv_20"], "avg_vol_20": sig["avg_vol_20"], "atr_at_entry": sig["atr"],
                    "entry_price_original": sig["signal_close"], "avg_price": sig["signal_close"],
                    "target_price": sig["tp_target"], "concentration": sig.get("concentration"),
                    "total_lots": 0, "remaining_lots": 0, "cost_basis": 0,
                }).execute()
                new_candidates_notes.append(f"{sig['stock_code']} (score {sig['score']:.2f})")

    # ---- EOD equity snapshot + backtest_runs summary ----
    still_open = _retry(lambda: supabase.table("paper_positions").select("*").eq("run_id", run_id).eq("status", "OPEN").execute()).data
    # Reset day_high/day_low so paper_monitor.py starts fresh tracking tomorrow's
    # intraday range from scratch (see that script's docstring).
    for row in still_open:
        # Retry-safe: absolute overwrite keyed by this row's own id.
        _retry(lambda: supabase.table("paper_positions").update({"day_high": None, "day_low": None}).eq("id", row["id"]).execute())
    market_value = 0.0
    for row in still_open:
        if row["stock_code"] in today_bars.index:
            close_px = float(today_bars.loc[row["stock_code"]]["close_price"])
        elif row.get("last_valid_close") is not None:
            # No fresh EOD row for this stock today (no-print gap, not yet at
            # DELISTING_GAP_DAYS) -- mark at the last real close this same script
            # already tracks (updated a few dozen lines above, in the DELISTED_GAP
            # branch's sibling continue paths), not the entry/cost price. avg_price
            # can be weeks stale for a long-running winner and understates/overstates
            # equity, drawdown_pct, and cvar_95 versus the stock's real last mark.
            close_px = float(row["last_valid_close"])
        else:
            # Rare edge case: a position that has never had a real print since entry
            # (e.g. filled today, or every day since has been a no-print gap) -- no
            # last_valid_close exists yet either. Cost price is the only mark available.
            close_px = float(row["avg_price"])
        market_value += close_px * int(row["remaining_lots"]) * LOT_SIZE
    total_equity = cash + market_value

    idx_today = idx_df[idx_df["trade_date"] == today]
    bench_close = float(idx_today.iloc[0]["close"]) if not idx_today.empty else None

    all_trades = _retry(lambda: supabase.table("backtest_trades").select("pnl").eq("run_id", run_id).execute()).data
    wins = sum(1 for t in all_trades if t["pnl"] > 0)
    total_trades = len(all_trades)
    win_rate = 100 * wins / total_trades if total_trades else 0.0
    gross_win = sum(t["pnl"] for t in all_trades if t["pnl"] > 0)
    gross_loss = -sum(t["pnl"] for t in all_trades if t["pnl"] < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    run_res = _retry(lambda: supabase.table("backtest_runs").select("initial_capital, period_start").eq("id", run_id).limit(1).execute())
    initial_capital = float(run_res.data[0]["initial_capital"])
    net_profit_pct = (total_equity / initial_capital - 1) * 100

    # alpha_pct was never computed here -- backtest_runs rows for every live
    # paper run sat at their column default (0), rendered on the frontend as
    # a flattering "+0.00%" (green) regardless of real performance vs IHSG.
    # Same formula backtest_v4.py uses for completed backtests: bench_ret =
    # IHSG's own % return over the identical period, alpha = strategy's
    # return minus that. period_start is fixed at run creation and can land
    # on a non-trading day (confirmed: V3_PAPER/V3.1_PAPER's period_start
    # are both Saturdays -- the row was created ahead of the first real
    # trading day) -- use the first real IHSG close ON OR AFTER period_start,
    # not an exact-date match, or those runs would wrongly find no benchmark
    # at all and stay null forever instead of just until their first trade.
    period_start = date.fromisoformat(run_res.data[0]["period_start"])
    bench_start_rows = idx_df[idx_df["trade_date"] >= period_start].sort_values("trade_date")
    if not bench_start_rows.empty and bench_close is not None:
        bench_start_close = float(bench_start_rows.iloc[0]["close"])
        benchmark_pct = (bench_close / bench_start_close - 1) * 100
        alpha_pct = net_profit_pct - benchmark_pct
    else:
        # No IHSG close on record for period_start or today -- leave both
        # null rather than writing a silently-wrong 0 (the exact bug this
        # fixes). paper-trading-client.tsx renders null as "--", not a fake
        # 0.00% (updated alongside this fix, not a pre-existing guard).
        benchmark_pct = None
        alpha_pct = None

    prior_equity_res = _retry(lambda: supabase.table("backtest_equity").select("portfolio_value").eq("run_id", run_id).order("date").execute())
    prior_equity = [float(row["portfolio_value"]) for row in prior_equity_res.data]
    drawdown_pct, cvar_95 = pc.compute_drawdown_and_cvar(prior_equity, total_equity)
    prior_max_dd_res = _retry(lambda: supabase.table("backtest_runs").select("max_drawdown").eq("id", run_id).limit(1).execute())
    prior_max_dd = float(prior_max_dd_res.data[0]["max_drawdown"] or 0.0)
    running_max_dd = min(prior_max_dd, drawdown_pct)

    # Deliberately NOT wrapped in retry: bare INSERT, no unique constraint on
    # (run_id, date) visible in this repo (backtest_equity predates
    # sql/paper_trading_schema.sql and isn't defined there at all). The
    # last_signal_date == today guard at the top of main() prevents a whole
    # second RUN of this script from re-inserting today's snapshot, but does
    # not make retrying this specific insert call safe -- if the first
    # attempt actually succeeded server-side and only the response was lost,
    # a retry here would silently create a second equity row for the same
    # date, corrupting the equity curve/drawdown history this same function
    # reads on every subsequent run. Same insert-safety reasoning as
    # backtest_trades.insert() in _close_position() above.
    supabase.table("backtest_equity").insert({
        "run_id": run_id, "date": today.isoformat(), "portfolio_value": total_equity,
        "drawdown_pct": drawdown_pct, "regime": regime,
    }).execute()
    # Retry-safe: absolute overwrite keyed by this run's own id.
    _retry(lambda: supabase.table("backtest_runs").update({
        "period_end": today.isoformat(), "final_capital": total_equity, "net_profit_pct": net_profit_pct,
        "total_trades": total_trades, "win_rate": win_rate, "profit_factor": profit_factor,
        "max_drawdown": running_max_dd, "cvar_95": cvar_95,
        "benchmark_pct": benchmark_pct, "alpha_pct": alpha_pct,
    }).eq("id", run_id).execute())
    # Retry-safe: absolute overwrite keyed by this run's own id.
    _retry(lambda: supabase.table("paper_account").update({
        "cash": cash, "last_signal_date": today.isoformat(), "log_adtv_p90": float(log_adtv_p90),
        "concentration_p90": float(concentration_p90),
    }).eq("run_id", run_id).execute())

    print(f"[EOD] equity=Rp{total_equity:,.0f} ({net_profit_pct:+.2f}%) cash=Rp{cash:,.0f} open={len(still_open)}")

    lines = [
        "\U0001F4CA *Neira Paper Trading -- EOD*",
        f"\U0001F4C5 `{today}`",
        f"Equity: Rp{total_equity:,.0f} ({net_profit_pct:+.2f}%)",
        f"Open positions: {len(still_open)} | Win rate: {win_rate:.1f}% ({total_trades} trades)",
    ]
    if new_candidates_notes:
        lines.append("New candidates queued for tomorrow's open: " + ", ".join(new_candidates_notes))
    # A retired run (pc.RETIRED_PAPER_VERSIONS) never has new_candidates_notes
    # (stop_new_entries gates that above) -- so on a day where none of its
    # remaining open positions exited either, this EOD summary is pure
    # routine noise (same equity/open-count restated, nothing changed).
    # Skip it; EXPIRE/corp-action-guard messages above still fire immediately
    # on their own since those are real events, not routine completions.
    if stop_new_entries and not had_exit_today:
        print("[EOD] Retired run, no exit today -- skipping routine Telegram summary.")
    else:
        pc.notify("\n".join(lines))


if __name__ == "__main__":
    pc.run_guarded(main, "paper_signal_scan.py")
