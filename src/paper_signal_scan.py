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
     backtest uses (src/backtest_v3.py) -- zero drift.
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
from datetime import date

import numpy as np

os.environ.setdefault("V3_TEST_END", date.today().isoformat())

import config as cfg  # noqa: E402
import backtest_v3 as bt  # noqa: E402
import paper_common as pc  # noqa: E402
from supabase import create_client  # noqa: E402

LOT_SIZE = bt.LOT_SIZE


def _position_dict_from_row(row: dict) -> dict:
    """paper_positions columns -> the dict shape evaluate_position_exit()
    expects (same keys backtest_v3's own position dicts use)."""
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
    supabase.table("paper_positions").update(payload).eq("id", position_id).execute()


def _close_position(supabase, run_id: int, position_id: int, pos: dict, trade_record: dict) -> None:
    supabase.table("paper_positions").update({
        "status": "CLOSED", "remaining_lots": pos["remaining_lots"],
        "exit_date": trade_record["exit_date"].isoformat(), "exit_price": trade_record["exit_price"],
        "exit_reason": trade_record["exit_reason"], "pnl": trade_record["pnl"], "pnl_pct": trade_record["pnl_pct"],
        "hold_days": trade_record["hold_days"],
    }).eq("id", position_id).execute()
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

    latest_res = supabase.table("ihsg_eod").select("trade_date").order("trade_date", desc=True).limit(1).execute()
    if not latest_res.data:
        sys.exit("ihsg_eod is empty -- nothing to scan.")
    today = date.fromisoformat(latest_res.data[0]["trade_date"])

    run_id = pc.get_paper_run_id(supabase)
    acct_res = supabase.table("paper_account").select("*").eq("run_id", run_id).limit(1).execute()
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

    open_res = (
        supabase.table("paper_positions").select("*").eq("run_id", run_id).eq("status", "OPEN").execute()
    )
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

    new_candidates_notes = []
    for row in open_positions:
        if row["entry_date"] == today.isoformat():
            continue  # filled today by paper_monitor.py -- don't exit-check same-day, matches backtest_v3.py's own guard

        if row["stock_code"] not in today_bars.index:
            # No EOD print today -- suspension or delisting. Same DELISTING_GAP_DAYS force-exit
            # the backtest applies (src/backtest_v3.py's simulate_window "no bar found" branch):
            # without this, a delisted position would sit open forever, frozen at its last
            # mark-to-market price, never contributing its real loss.
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
                print(f"  [EOD-RECONCILE] {row['stock_code']}: DELISTED_GAP (no print for {no_data_days}d) pnl={pnl:+,.0f}")
            else:
                supabase.table("paper_positions").update({"no_data_days": no_data_days, "hold_days": hold_days}).eq("id", row["id"]).execute()
            continue

        bar_row = today_bars.loc[row["stock_code"]]
        bar = (float(bar_row["open_price"]), float(bar_row["close_price"]), float(bar_row["high"]), float(bar_row["low"]))

        prev_close = prev_close_by_stock.get(row["stock_code"])
        if pc.looks_like_unadjusted_corporate_action(prev_close, bar[1]):
            msg = (f"⚠️ *{row['stock_code']}*: close Rp{bar[1]:,.0f} vs prev Rp{prev_close:,.0f} "
                   f"looks like an unadjusted split/corporate action -- SKIPPING SL/TP check today, "
                   f"please verify and correct avg_price/sl_price/tp1_price manually.")
            print(f"  [CORP-ACTION-GUARD] {msg}")
            pc.notify(msg)
            hold_days = int(row["hold_days"]) + 1
            supabase.table("paper_positions").update({"hold_days": hold_days}).eq("id", row["id"]).execute()
            continue

        pos = _position_dict_from_row(row)
        trade_record, cash_delta = bt.evaluate_position_exit(pos, bar, regime, trend_strength, today, prev_equity, cash)
        cash += cash_delta

        if trade_record is not None:
            _close_position(supabase, run_id, row["id"], pos, trade_record)
            print(f"  [EOD-RECONCILE] {trade_record['stock_code']}: {trade_record['exit_reason']} "
                  f"pnl={trade_record['pnl']:+,.0f}")
            if trade_record["exit_reason"] == "TP1":
                pos["hold_days"] += 1
                _persist_position(supabase, row["id"], pos)
                supabase.table("paper_positions").update({"no_data_days": 0, "last_valid_close": bar[1]}).eq("id", row["id"]).execute()
            continue

        pos["hold_days"] += 1
        _persist_position(supabase, row["id"], pos)
        supabase.table("paper_positions").update({"no_data_days": 0, "last_valid_close": bar[1]}).eq("id", row["id"]).execute()

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
    # Refreshed daily and persisted (paper_account.log_adtv_p90) so paper_monitor.py can
    # fill entries with the exact same LIQ_SIZING reference without rebuilding the full
    # dataset every 15 minutes -- see compute_entry_fill()'s docstring in backtest_v3.py.
    train_log_adtv = np.log(train_liquid_bullish["adtv_20"].clip(lower=1))
    log_adtv_p90 = train_log_adtv.quantile(0.90) if len(train_log_adtv) > 0 else 1.0
    if not np.isfinite(log_adtv_p90) or log_adtv_p90 <= 0:
        log_adtv_p90 = 1.0

    regime_ok = (regime == "BULLISH" and bullish_streak_by_date.get(today, 0) >= bt.REGIME_CONFIRM_DAYS
                 and trend_strength >= bt.TREND_STRENGTH_MIN)

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
    if scoreboard:
        supabase.table("daily_scoreboard").upsert([{
            "trade_date": today.isoformat(), "stock_code": row["stock_code"], "score": row["score"],
            "label": row["label"], "percentile": row["percentile"], "weekly_ma_spread": row["weekly_ma_spread"],
            "sector_rs_momentum": row["sector_rs_momentum"], "close_price": row["close_price"],
            "adtv_20": row["adtv_20"],
        } for row in scoreboard], on_conflict="trade_date,stock_code").execute()
        print(f"[SCOREBOARD] {len(scoreboard)} tickers scored for {today}")

    candidates = []
    if regime_ok:
        open_count = supabase.table("paper_positions").select("id", count="exact").eq("run_id", run_id).in_(
            "status", ["OPEN", "PENDING"]
        ).execute().count
        slots_free = max(0, bt.MAX_POSITIONS - open_count)
        max_new = min(slots_free, bt.MAX_NEW_ENTRIES_PER_DAY)
        if max_new > 0:
            day_data = df[df["trade_date"] == today]
            scored = bt.score_candidates(day_data, weekly_cut, sector_cut, top_n=15)
            for sig in scored:
                if len(candidates) >= max_new:
                    break
                already_open = any(p["stock_code"] == sig["stock_code"] for p in open_positions)
                if already_open:
                    continue
                sl_res = (
                    supabase.table("paper_positions").select("exit_date")
                    .eq("run_id", run_id).eq("stock_code", sig["stock_code"]).eq("exit_reason", "SL")
                    .order("exit_date", desc=True).limit(1).execute()
                )
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
                supabase.table("paper_positions").insert({
                    "run_id": run_id, "stock_code": sig["stock_code"], "status": "PENDING",
                    "signal_date": today.isoformat(), "trigger": sig["trigger"], "score": sig["score"],
                    "adtv_20": sig["adtv_20"], "avg_vol_20": sig["avg_vol_20"], "atr_at_entry": sig["atr"],
                    "entry_price_original": sig["signal_close"], "avg_price": sig["signal_close"],
                    "target_price": sig["tp_target"],
                    "total_lots": 0, "remaining_lots": 0, "cost_basis": 0,
                }).execute()
                new_candidates_notes.append(f"{sig['stock_code']} (score {sig['score']:.2f})")

    # ---- EOD equity snapshot + backtest_runs summary ----
    still_open = supabase.table("paper_positions").select("*").eq("run_id", run_id).eq("status", "OPEN").execute().data
    # Reset day_high/day_low so paper_monitor.py starts fresh tracking tomorrow's
    # intraday range from scratch (see that script's docstring).
    for row in still_open:
        supabase.table("paper_positions").update({"day_high": None, "day_low": None}).eq("id", row["id"]).execute()
    market_value = 0.0
    for row in still_open:
        if row["stock_code"] in today_bars.index:
            close_px = float(today_bars.loc[row["stock_code"]]["close_price"])
        else:
            close_px = float(row["avg_price"])
        market_value += close_px * int(row["remaining_lots"]) * LOT_SIZE
    total_equity = cash + market_value

    idx_today = idx_df[idx_df["trade_date"] == today]
    bench_close = float(idx_today.iloc[0]["close"]) if not idx_today.empty else None

    all_trades = supabase.table("backtest_trades").select("pnl").eq("run_id", run_id).execute().data
    wins = sum(1 for t in all_trades if t["pnl"] > 0)
    total_trades = len(all_trades)
    win_rate = 100 * wins / total_trades if total_trades else 0.0
    gross_win = sum(t["pnl"] for t in all_trades if t["pnl"] > 0)
    gross_loss = -sum(t["pnl"] for t in all_trades if t["pnl"] < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    run_res = supabase.table("backtest_runs").select("initial_capital, period_start").eq("id", run_id).limit(1).execute()
    initial_capital = float(run_res.data[0]["initial_capital"])
    net_profit_pct = (total_equity / initial_capital - 1) * 100

    prior_equity_res = supabase.table("backtest_equity").select("portfolio_value").eq("run_id", run_id).order("date").execute()
    prior_equity = [float(row["portfolio_value"]) for row in prior_equity_res.data]
    drawdown_pct, cvar_95 = pc.compute_drawdown_and_cvar(prior_equity, total_equity)
    prior_max_dd_res = supabase.table("backtest_runs").select("max_drawdown").eq("id", run_id).limit(1).execute()
    prior_max_dd = float(prior_max_dd_res.data[0]["max_drawdown"] or 0.0)
    running_max_dd = min(prior_max_dd, drawdown_pct)

    supabase.table("backtest_equity").insert({
        "run_id": run_id, "date": today.isoformat(), "portfolio_value": total_equity,
        "drawdown_pct": drawdown_pct, "regime": regime,
    }).execute()
    supabase.table("backtest_runs").update({
        "period_end": today.isoformat(), "final_capital": total_equity, "net_profit_pct": net_profit_pct,
        "total_trades": total_trades, "win_rate": win_rate, "profit_factor": profit_factor,
        "max_drawdown": running_max_dd, "cvar_95": cvar_95,
    }).eq("id", run_id).execute()
    supabase.table("paper_account").update({
        "cash": cash, "last_signal_date": today.isoformat(), "log_adtv_p90": float(log_adtv_p90),
    }).eq("run_id", run_id).execute()

    print(f"[EOD] equity=Rp{total_equity:,.0f} ({net_profit_pct:+.2f}%) cash=Rp{cash:,.0f} open={len(still_open)}")

    lines = [
        "\U0001F4CA *Neira Paper Trading -- EOD*",
        f"\U0001F4C5 `{today}`",
        f"Equity: Rp{total_equity:,.0f} ({net_profit_pct:+.2f}%)",
        f"Open positions: {len(still_open)} | Win rate: {win_rate:.1f}% ({total_trades} trades)",
    ]
    if new_candidates_notes:
        lines.append("New candidates queued for tomorrow's open: " + ", ".join(new_candidates_notes))
    pc.notify("\n".join(lines))


if __name__ == "__main__":
    pc.run_guarded(main, "paper_signal_scan.py")
