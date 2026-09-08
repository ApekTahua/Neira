"""scratch_broker_flow_traderate.py -- SCRATCH/RESEARCH ONLY. Trade-level
base-rate check for the market_broker_flow feature: does win rate / mean pnl
actually differ by bucket of the feature's value AT ENTRY, with a real
significance check (Spearman), not just eyeballing the aggregate walk-forward
numbers. Uses the BASELINE (gate OFF, V4_ATR_PRICE_RATIO_MAX=0.08) trade set
across all 9 walk-forward windows -- the feature's value at each trade's own
entry_date is looked up AFTER the fact, the gate itself never filtered any of
these trades, so this is a clean base-rate read on the existing trade
population, not a result already shaped by the gate under test.

Run directly: python src/scratch_broker_flow_traderate.py
"""
import os

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

from datetime import date

import pandas as pd
from scipy import stats

import backtest_v4 as bt
from walk_forward_v4 import build_schedule, load_dataset

df, idx_df = load_dataset()  # local cache, no Supabase needed
schedule = build_schedule(date(2022, 1, 1), bt.TEST_END)

all_trades = []
for i, (tr_end, te_start, te_end) in enumerate(schedule, 1):
    metrics, df_trades, df_equity, _regime = bt.simulate_window(df, idx_df, tr_end, te_start, te_end, label=f"W{i}")
    if metrics is None or df_trades.empty:
        continue
    df_trades = df_trades.copy()
    df_trades["window"] = i
    all_trades.append(df_trades)

trades = pd.concat(all_trades, ignore_index=True)
print(f"\nTotal trades across 9 windows: {len(trades)}")

flow5 = bt.compute_market_broker_flow(df, window_days=5)
flow1_raw = bt._daily_liquid_net_ratio(df)  # unsmoothed daily ratio, for comparison

trades["entry_date_parsed"] = pd.to_datetime(trades["entry_date"]).dt.date
trades["broker_flow_5d"] = trades["entry_date_parsed"].map(flow5)
trades["broker_flow_1d"] = trades["entry_date_parsed"].map(flow1_raw)
trades["win"] = (trades["pnl"] > 0).astype(int)

missing = trades["broker_flow_5d"].isna().sum()
print(f"Trades with no broker_flow_5d value at entry (missing lookup): {missing} / {len(trades)}")
sub = trades.dropna(subset=["broker_flow_5d"]).copy()

for col in ["broker_flow_5d", "broker_flow_1d"]:
    rho, p = stats.spearmanr(sub[col], sub["pnl_pct"])
    rho_w, p_w = stats.spearmanr(sub[col], sub["win"])
    print(f"\n--- Spearman: {col} vs pnl_pct  rho={rho:+.3f}  p={p:.4g}  (n={len(sub)}) ---")
    print(f"--- Spearman: {col} vs win(0/1) rho={rho_w:+.3f}  p={p_w:.4g} ---")

print("\n--- Quartile breakdown (broker_flow_5d at entry) ---")
sub["q"] = pd.qcut(sub["broker_flow_5d"], 4, labels=["Q1 (most selling)", "Q2", "Q3", "Q4 (most buying)"])
agg = sub.groupby("q", observed=True).agg(
    n=("pnl", "size"), win_rate=("win", "mean"), mean_pnl_pct=("pnl_pct", "mean"),
    median_pnl_pct=("pnl_pct", "median"), flow_range=("broker_flow_5d", lambda s: (s.min(), s.max())),
)
agg["win_rate"] = (agg["win_rate"] * 100).round(1)
agg["mean_pnl_pct"] = agg["mean_pnl_pct"].round(2)
agg["median_pnl_pct"] = agg["median_pnl_pct"].round(2)
print(agg.to_string())

kw_groups = [g["pnl_pct"].values for _, g in sub.groupby("q", observed=True)]
h, p_kw = stats.kruskal(*kw_groups)
print(f"\nKruskal-Wallis across quartiles (pnl_pct): H={h:.3f}, p={p_kw:.4g}")
