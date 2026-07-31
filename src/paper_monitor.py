"""paper_monitor.py -- intraday job for the live V3 paper-trading engine,
runs every 15 minutes during IDX trading hours (~09:00-11:30 & 13:30-15:00
WIB -> UTC 02:00-04:30 & 06:30-08:00; a little overrun at the session
edges is harmless -- it just finds no fresh price and no-ops).

Responsibilities:
  1. Fill PENDING candidates (queued the prior trading day by
     paper_signal_scan.py) at today's ihsg_realtime open, through the
     exact same sizing/fee math as the backtest (compute_entry_fill()).
  2. Track day_high/day_low per open position across polls -- a
     disclosed proxy for the backtest's true daily high/low, since
     ihsg_realtime only carries a live "close" price + a fixed daily
     "open", not real intraday OHLC (see docs/V3_FINDINGS_LOG.md "Live
     paper trading" section).
  3. Check SL/TP1/TRAILING against that running day_high/day_low via
     evaluate_position_exit() -- the exact same exit logic as the
     backtest and as paper_signal_scan.py's EOD reconciliation pass.
  4. Telegram notification per fill/exit.

Governance: frozen configuration, no LLM in any decision -- see
paper_common.py's module docstring.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/paper_monitor.py
"""

import os
import sys
from datetime import date, datetime, timezone

os.environ.setdefault("V3_TEST_END", date.today().isoformat())

import config as cfg  # noqa: E402
import backtest_v3 as bt  # noqa: E402
import paper_common as pc  # noqa: E402
from supabase import create_client  # noqa: E402

LOT_SIZE = bt.LOT_SIZE
STALE_MINUTES = 30


def _gap_ok(entry_price: float, signal_close: float) -> bool:
    tick = 1 if signal_close < 200 else 2 if signal_close < 500 else 5 if signal_close < 2000 else 10 if signal_close < 5000 else 25
    gap_limit = max(cfg.GAP_MAX, 2 * tick / signal_close)
    return abs(entry_price / signal_close - 1) <= gap_limit


def _position_dict_from_row(row: dict) -> dict:
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


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    today = date.today()
    run_id = pc.get_paper_run_id(supabase)
    acct = supabase.table("paper_account").select("*").eq("run_id", run_id).limit(1).execute().data
    if not acct:
        sys.exit(f"No paper_account row for run_id={run_id} -- run sql/paper_trading_schema.sql's seed first.")
    account = acct[0]
    cash = float(account["cash"])
    log_adtv_p90 = float(account["log_adtv_p90"]) if account.get("log_adtv_p90") else 1.0

    pending = supabase.table("paper_positions").select("*").eq("run_id", run_id).eq("status", "PENDING").lt(
        "signal_date", today.isoformat()
    ).execute().data
    open_positions = supabase.table("paper_positions").select("*").eq("run_id", run_id).eq("status", "OPEN").execute().data

    tickers = sorted({p["stock_code"] for p in pending} | {p["stock_code"] for p in open_positions})
    if not tickers:
        print("[MONITOR] No pending/open positions -- nothing to do.")
        return

    live_res = supabase.table("ihsg_realtime").select("*").in_("stock_code", tickers).execute()
    live = {r["stock_code"]: r for r in live_res.data}

    freshest = max((r["updated_at"] for r in live.values()), default=None)
    if freshest:
        age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(freshest.replace("Z", "+00:00"))).total_seconds() / 60
        if age_min > STALE_MINUTES:
            msg = f"⚠️ ihsg_realtime feed is {age_min:.0f} min stale (>{STALE_MINUTES}m) -- skipping this poll."
            print(f"[MONITOR] {msg}")
            pc.notify(msg)
            return

    # ---- Fill PENDING candidates at today's open ----
    prev_equity = cash + sum(float(p["cost_basis"]) for p in open_positions)
    for row in pending:
        r = live.get(row["stock_code"])
        if r is None or r.get("open") in (None, 0):
            continue  # no live print yet / suspended today
        entry_price = float(r["open"])
        signal_close = float(row["entry_price_original"])
        if not _gap_ok(entry_price, signal_close):
            continue
        sig = {
            "atr": row["atr_at_entry"], "tp_target": row["target_price"], "score": row["score"],
            "adtv_20": row["adtv_20"], "avg_vol_20": row["avg_vol_20"],
        }
        fill = bt.compute_entry_fill(sig, entry_price, cash, prev_equity, log_adtv_p90)
        if fill is None:
            continue

        # compute_entry_fill() already sized lots using the plain percentage BUY_FEE
        # (matches the backtest exactly, so lot count doesn't drift); the real cash
        # outflow adds the flat Rp10,000 surcharge on top when the gross value clears
        # Rp10,000,000 -- a paper-trading-specific real-world fee, not in the backtest.
        gross_value = fill["quantity"] * entry_price
        extra_fee = pc.total_buy_fee(gross_value, buy_fee_pct=0.0)  # buy_fee_pct=0 isolates just the flat surcharge
        cash_out = fill["cost_basis"] + extra_fee
        if cash_out > cash:
            continue  # extra flat fee would overdraw cash -- skip this fill this poll, retried next poll
        cash -= cash_out

        supabase.table("paper_positions").update({
            "status": "OPEN", "entry_date": today.isoformat(), "avg_price": entry_price,
            "tp1_price": fill["tp1_price"], "sl_price": fill["sl_price"],
            "total_lots": fill["lots"], "remaining_lots": fill["lots"], "cost_basis": cash_out,
            "checkpoint_day": fill["checkpoint_day"], "highest_price": entry_price,
            "day_high": entry_price, "day_low": entry_price,
        }).eq("id", row["id"]).execute()
        pc.notify(f"\U0001F7E2 *FILLED* {row['stock_code']} @ Rp{entry_price:,.0f} x {fill['lots']} lot(s)")
        print(f"[MONITOR] FILLED {row['stock_code']} @ {entry_price:.0f} x{fill['lots']}lot cash_out=Rp{cash_out:,.0f}")

    # ---- Check exits on OPEN positions ----
    regime_hint = "BULLISH"  # TIME-exit's regime check only matters at EOD (paper_signal_scan.py);
    # a live intraday poll cannot know tomorrow's regime, and TIME only fires pre-tp1 near
    # MAX_HOLD_DAYS -- immaterial here, this monitor's job is SL/TP1/TRAILING reaction speed.
    for row in open_positions:
        r = live.get(row["stock_code"])
        if r is None or r.get("close") in (None, 0):
            continue
        current_price = float(r["close"])
        day_open = float(r["open"]) if r.get("open") else current_price
        day_high = max(float(row["day_high"]), current_price) if row.get("day_high") else current_price
        day_low = min(float(row["day_low"]), current_price) if row.get("day_low") else current_price

        pos = _position_dict_from_row(row)
        trade_record, cash_delta = bt.evaluate_position_exit(
            pos, (day_open, current_price, day_high, day_low), regime_hint, 0.0,
            today, prev_equity, cash,
        )
        cash += cash_delta

        if trade_record is None:
            supabase.table("paper_positions").update({"day_high": day_high, "day_low": day_low}).eq("id", row["id"]).execute()
            continue

        if trade_record["exit_reason"] == "TP1":
            supabase.table("paper_positions").update({
                "avg_price": pos["avg_price"], "tp1_price": pos["tp1_price"], "sl_price": pos["sl_price"],
                "total_lots": pos["total_lots"], "remaining_lots": pos["remaining_lots"], "cost_basis": pos["cost_basis"],
                "tp1_hit": True, "day_high": day_high, "day_low": day_low,
            }).eq("id", row["id"]).execute()
        else:
            supabase.table("paper_positions").update({
                "status": "CLOSED", "remaining_lots": pos["remaining_lots"],
                "exit_date": today.isoformat(), "exit_price": trade_record["exit_price"],
                "exit_reason": trade_record["exit_reason"], "pnl": trade_record["pnl"], "pnl_pct": trade_record["pnl_pct"],
            }).eq("id", row["id"]).execute()
            supabase.table("backtest_trades").insert({
                "run_id": run_id, "stock_code": trade_record["stock_code"],
                "entry_date": trade_record["entry_date"].isoformat(), "exit_date": today.isoformat(),
                "entry_price": float(trade_record["entry_price"]), "exit_price": float(trade_record["exit_price"]),
                "lots": int(trade_record["lots"]), "pnl": float(trade_record["pnl"]), "pnl_pct": float(trade_record["pnl_pct"]),
                "exit_reason": trade_record["exit_reason"], "trigger": trade_record["trigger"],
                "hold_days": int(trade_record["hold_days"]),
            }).execute()

        emoji = "\U0001F534" if trade_record["pnl"] < 0 else "\U0001F7E2"
        pc.notify(f"{emoji} *{trade_record['exit_reason']}* {trade_record['stock_code']} @ "
                  f"Rp{trade_record['exit_price']:,.0f} pnl=Rp{trade_record['pnl']:+,.0f}")
        print(f"[MONITOR] {trade_record['exit_reason']} {trade_record['stock_code']} pnl={trade_record['pnl']:+,.0f}")

    supabase.table("paper_account").update({"cash": cash}).eq("run_id", run_id).execute()
    print(f"[MONITOR] done. cash=Rp{cash:,.0f}")


if __name__ == "__main__":
    main()
