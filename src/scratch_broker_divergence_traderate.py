"""scratch_broker_divergence_traderate.py -- SCRATCH/RESEARCH ONLY. Trade-
level base-rate check for the PER-STOCK smart-money divergence feature
(src/scratch_broker_divergence_build.py): does the divergence value AT ENTRY
(the day a real candidate from the existing signal pipeline opened a
position) correlate with what happened next (pnl_pct / win), with a real
significance test -- not eyeballing.

Uses the BASELINE trade set (gate/filter OFF, V4_ATR_PRICE_RATIO_MAX=0.08 --
current live V4_PAPER config) across all 9 walk-forward windows, same
population scratch_broker_flow_traderate.py used for the (REJECTED)
market-wide feature -- the feature is looked up AFTER the fact, nothing here
has filtered any trade yet.

Tests every shape built (continuous divergence_{w}d, binary flag_{w}d for
w in 1/3/5/10) plus the two single-leg components (foreign_ratio_w alone,
retail_ratio_w alone) so a real effect can be attributed to the divergence
specifically, not just one leg carrying it.

Run directly: python src/scratch_broker_divergence_traderate.py
"""
import os

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

import backtest_v4 as bt
from walk_forward_v4 import build_schedule, load_dataset

DIVERGENCE_PATH = ".cache/broker_divergence_by_stock.pkl"
WINDOWS = (1, 3, 5, 10)

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

panel = pd.read_pickle(DIVERGENCE_PATH)
panel = panel.rename(columns={"trade_date": "entry_date_parsed"})

trades["entry_date_parsed"] = pd.to_datetime(trades["entry_date"]).dt.date
trades["win"] = (trades["pnl"] > 0).astype(int)

merged = trades.merge(panel, on=["stock_code", "entry_date_parsed"], how="left")
missing = merged["divergence_1d"].isna().sum()
print(f"Trades with no divergence_1d value at entry (missing lookup): {missing} / {len(merged)}")

# Single-leg components at each window, for attribution (build them here from the same
# panel columns rather than re-computing -- foreign_ratio_w = the divergence formula's own
# foreign half; retail_ratio_w = its own retail half. Reconstructed algebraically from what
# scratch_broker_divergence_build.py already saved, no re-scan of the raw archive needed.)
for w in WINDOWS:
    col = f"divergence_{w}d"
    sub = merged.dropna(subset=[col]).copy()
    rho, p = stats.spearmanr(sub[col], sub["pnl_pct"])
    rho_w, p_w = stats.spearmanr(sub[col], sub["win"])
    print(f"\n=== window={w}d (n={len(sub)}) ===")
    print(f"Spearman: divergence_{w}d vs pnl_pct  rho={rho:+.3f}  p={p:.4g}")
    print(f"Spearman: divergence_{w}d vs win(0/1) rho={rho_w:+.3f}  p={p_w:.4g}")

    q = pd.qcut(sub[col], 4, labels=["Q1(most retail-heavy)", "Q2", "Q3", "Q4(most divergent)"], duplicates="drop")
    sub["q"] = q
    agg = sub.groupby("q", observed=True).agg(
        n=("pnl", "size"), win_rate=("win", "mean"), mean_pnl_pct=("pnl_pct", "mean"),
        median_pnl_pct=("pnl_pct", "median"),
    )
    agg["win_rate"] = (agg["win_rate"] * 100).round(1)
    agg["mean_pnl_pct"] = agg["mean_pnl_pct"].round(2)
    agg["median_pnl_pct"] = agg["median_pnl_pct"].round(2)
    print(agg.to_string())

    kw_groups = [g["pnl_pct"].values for _, g in sub.groupby("q", observed=True)]
    if len(kw_groups) >= 2:
        h, p_kw = stats.kruskal(*kw_groups)
        print(f"Kruskal-Wallis across quartiles (pnl_pct): H={h:.3f}, p={p_kw:.4g}")

    # Binary flag version, same window
    fcol = f"flag_{w}d"
    fsub = merged.dropna(subset=[fcol]).copy()
    fsub[fcol] = fsub[fcol].astype(bool)
    on_ = fsub[fsub[fcol]]
    off_ = fsub[~fsub[fcol]]
    print(f"\nflag_{w}d ON  (n={len(on_)}): win_rate={on_['win'].mean()*100:.1f}%  mean_pnl_pct={on_['pnl_pct'].mean():.2f}")
    print(f"flag_{w}d OFF (n={len(off_)}): win_rate={off_['win'].mean()*100:.1f}%  mean_pnl_pct={off_['pnl_pct'].mean():.2f}")
    if len(on_) >= 5 and len(off_) >= 5:
        u, p_mw = stats.mannwhitneyu(on_["pnl_pct"], off_["pnl_pct"], alternative="two-sided")
        print(f"Mann-Whitney U (ON vs OFF pnl_pct): p={p_mw:.4g}")

# --- Single-leg attribution at window=5d (middle of the sweep, arbitrary-but-representative pick) ---
print("\n" + "=" * 100)
print("Single-leg attribution (w=5d): is DIVERGENCE (foreign-retail) doing anything foreign_net or "
      "retail_net alone at the same window wouldn't already show?")
print("=" * 100)
panel5 = pd.read_pickle(DIVERGENCE_PATH).rename(columns={"trade_date": "entry_date_parsed"})
merged5 = trades.merge(panel5, on=["stock_code", "entry_date_parsed"], how="left")
sub5 = merged5.dropna(subset=["divergence_5d"]).copy()
# foreign_ratio_5d / retail_ratio_5d aren't columns on the panel (only their difference is) --
# but the panel's raw foreign_net/retail_net/total_turnover (window=1, single-day) plus the
# fact w=5's divergence = (fn_sum-rn_sum)/tt_sum means we can't algebraically split without
# re-deriving the window-summed legs. Cheaper to just re-derive from the raw daily columns
# via the same rolling-sum-then-ratio logic, one extra pass, no archive re-scan needed.
raw_panel = pd.read_pickle(DIVERGENCE_PATH).sort_values(["stock_code", "trade_date"])
g = raw_panel.groupby("stock_code", sort=False)
fn_sum = g["foreign_net"].transform(lambda s: s.rolling(5, min_periods=5).sum())
rn_sum = g["retail_net"].transform(lambda s: s.rolling(5, min_periods=5).sum())
tt_sum = g["total_turnover"].transform(lambda s: s.rolling(5, min_periods=5).sum())
raw_panel["foreign_ratio_5d"] = fn_sum / tt_sum.replace(0, np.nan)
raw_panel["retail_ratio_5d"] = rn_sum / tt_sum.replace(0, np.nan)
raw_panel = raw_panel.rename(columns={"trade_date": "entry_date_parsed"})
merged5b = trades.merge(
    raw_panel[["stock_code", "entry_date_parsed", "foreign_ratio_5d", "retail_ratio_5d"]],
    on=["stock_code", "entry_date_parsed"], how="left",
)
for col in ["foreign_ratio_5d", "retail_ratio_5d"]:
    s = merged5b.dropna(subset=[col])
    rho, p = stats.spearmanr(s[col], s["pnl_pct"])
    print(f"Spearman: {col} vs pnl_pct  rho={rho:+.3f}  p={p:.4g}  (n={len(s)})")
