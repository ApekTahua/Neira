"""Independent, read-only pull of V4_PAPER's real live record since
2026-08-12 (the day it started live trading) -- separate from the blind
backtest holdout in scratch_v4_blind_holdout_2026h2.py, does not touch
backtest_v4.py or the walk-forward dataset at all. See
docs/V3_FINDINGS_LOG.md 2026-09-01 entry for the write-up this fed.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/scratch_v4paper_live_record_pull.py
"""
import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
from supabase import create_client  # noqa: E402

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

run = supabase.table("backtest_runs").select("*").eq("version", "V4_PAPER").order("id", desc=True).limit(1).execute().data[0]
run_id = run["id"]
print("[RUN] backtest_runs row:", run)

positions = supabase.table("paper_positions").select("*").eq("run_id", run_id).execute().data
pdf = pd.DataFrame(positions)
print(f"\n[ALL POSITIONS] n={len(pdf)}")
if len(pdf):
    print(pdf["status"].value_counts())

closed = pdf[pdf["status"] == "CLOSED"].copy() if len(pdf) else pdf
print(f"\n[CLOSED] n={len(closed)}")
if len(closed):
    closed["entry_date"] = pd.to_datetime(closed["entry_date"])
    closed["exit_date"] = pd.to_datetime(closed["exit_date"])
    since = pd.Timestamp("2026-08-12")
    live_since = closed[closed["entry_date"] >= since]
    print(f"\n[CLOSED, entry_date >= 2026-08-12] n={len(live_since)}")
    print(live_since[["stock_code", "entry_date", "exit_date", "avg_price", "exit_price", "pnl", "pnl_pct", "exit_reason"]].to_string(index=False))
    wins = (live_since["pnl"] > 0).sum()
    if len(live_since):
        print(f"\nwin rate: {wins}/{len(live_since)} = {100*wins/len(live_since):.1f}%")
    print(f"total pnl: {live_since['pnl'].sum():,.0f}")
    gross_win = live_since[live_since['pnl'] > 0]['pnl'].sum()
    gross_loss = -live_since[live_since['pnl'] < 0]['pnl'].sum()
    print(f"gross win: {gross_win:,.0f}  gross loss: {gross_loss:,.0f}  PF: {gross_win/gross_loss if gross_loss else float('inf')}")

still_open = pdf[pdf["status"].isin(["OPEN", "PENDING"])] if len(pdf) else pdf
print(f"\n[STILL OPEN/PENDING] n={len(still_open)}")
if len(still_open):
    print(still_open[["stock_code", "status", "signal_date", "entry_date", "avg_price"]].to_string(index=False))

equity = supabase.table("backtest_equity").select("*").eq("run_id", run_id).execute().data
edf = pd.DataFrame(equity)
if len(edf):
    edf["date"] = pd.to_datetime(edf["date"])
    edf = edf.sort_values("date")
    print(f"\n[EQUITY] n={len(edf)} rows, {edf['date'].min()}..{edf['date'].max()}")
    print(edf[["date", "portfolio_value", "drawdown_pct", "regime"]].to_string(index=False))
