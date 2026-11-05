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
import paper_common as pc  # noqa: E402

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
print(f"\n[CLOSED, all statuses incl. unfilled expiries] n={len(closed)}")

# F-003: the holdout bar is FILLED closed positions, not raw status='CLOSED'
# -- a stale PENDING order that expired unfilled also lands in CLOSED
# (exit_reason='UNFILLED_EXPIRED', entry_date/filled_at both NULL, pnl=0) and
# is real information about live executability, but it never became a
# traded position and must not inflate progress toward the 60-position bar.
# paper_common.is_filled_closed_position() is the single-source-of-truth
# definition -- this used to rely on an `entry_date >= 2026-08-12` filter
# that only excluded the expiry by accident of its entry_date being NULL,
# not by an explicit rule (see paper_common.py's own comment on this).
if len(closed):
    unfilled_expiries = closed[~closed.apply(pc.is_filled_closed_position, axis=1)]
    if len(unfilled_expiries):
        print(f"\n[UNFILLED EXPIRIES, excluded from the holdout bar] n={len(unfilled_expiries)}")
        print(unfilled_expiries[["stock_code", "signal_date", "exit_date", "exit_reason"]].to_string(index=False))

    live_since = closed[closed.apply(pc.is_filled_closed_position, axis=1)].copy()
    live_since["entry_date"] = pd.to_datetime(live_since["entry_date"])
    live_since["exit_date"] = pd.to_datetime(live_since["exit_date"])
    print(f"\n[HOLDOUT BAR -- filled, closed positions] n={len(live_since)} (of 60 required)")
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
