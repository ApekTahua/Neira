"""scratch_broker_divergence_correlation.py -- SCRATCH/RESEARCH ONLY. Independence
check for the per-stock divergence feature (src/scratch_broker_divergence_build.py):
does it add information ON TOP OF what's already in score_candidates()'s own scoring
(weekly_ma_spread, sector_rs_momentum) and the regime/trend_strength gate, or the
already-tested market-wide broker_flow axis (REJECTED, docs/V3_FINDINGS_LOG.md) --
same question scratch_broker_flow_correlation.py asked for the market-wide version,
now asked for the per-stock one, at the ACTUAL CANDIDATE level (df's own liquid
qualifying rows), not an arbitrary sample.

Note: neither foreign_buy/foreign_sell (df's own coarser ihsg_eod-sourced columns)
nor the broker-level market-wide flow is used anywhere in backtest_v4.py's live
scoring/gating today (grepped, zero hits) -- so this checks whether the per-stock
divergence feature is redundant with the price-based features that DO drive scoring,
plus the other broker-flow axis, for completeness.

Run directly: python src/scratch_broker_divergence_correlation.py
"""
import pickle

import numpy as np
import pandas as pd
from scipy import stats

import backtest_v4 as bt

CACHE_PATH = ".cache/walk_forward_data_2021-01-01_2026-06-30.pkl"
DIVERGENCE_PATH = ".cache/broker_divergence_by_stock.pkl"

with open(CACHE_PATH, "rb") as f:
    df, idx_df = pickle.load(f)

regime_by_date, bullish_streak_by_date, trend_strength_by_date = bt.compute_regime_with_hysteresis(idx_df)
market_flow_by_date = bt.compute_market_broker_flow(df, window_days=5)

panel = pd.read_pickle(DIVERGENCE_PATH)  # stock_code, trade_date, divergence_{1,3,5,10}d, flag_{...}

# Restrict to the SAME liquid population score_candidates() actually screens to (adtv_20 >=
# ADTV_MIN, weekly_ma_spread/sector_rs_momentum present) -- correlating against every
# (stock,day) in the archive would mix in illiquid noise that never reaches a real candidate.
import config as cfg  # noqa: E402
liquid = df[
    (df["adtv_20"] >= cfg.ADTV_MIN) & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
][["stock_code", "trade_date", "weekly_ma_spread", "sector_rs_momentum"]].copy()
liquid["trend_strength"] = liquid["trade_date"].map(trend_strength_by_date)
liquid["market_flow_5d"] = liquid["trade_date"].map(market_flow_by_date)

merged = liquid.merge(panel, on=["stock_code", "trade_date"], how="inner")
print(f"Liquid qualifying-population rows with a divergence value: {len(merged)} / {len(liquid)} liquid rows")

for w in (1, 3, 5, 10):
    col = f"divergence_{w}d"
    sub = merged.dropna(subset=[col])
    print(f"\n=== divergence_{w}d (n={len(sub)}) vs already-live/already-tested features ===")
    for other in ["weekly_ma_spread", "sector_rs_momentum", "trend_strength", "market_flow_5d"]:
        s2 = sub.dropna(subset=[other])
        if len(s2) < 30:
            print(f"  vs {other}: n too small ({len(s2)}), skipped")
            continue
        rho, p = stats.spearmanr(s2[col], s2[other])
        print(f"  vs {other:<20s}: Spearman rho={rho:+.3f}  p={p:.4g}  (n={len(s2)})")

# Does divergence_5d vary WITHIN the population that already passes the existing
# weekly/sector gate at a given day's own train-derived cuts? (Same "does it add
# something beyond re-deriving 'this day/stock already looks good'" check
# scratch_broker_flow_correlation.py ran for the market-wide axis, adapted per-stock:
# split by within-day top-half vs bottom-half score, using EACH ROW'S OWN qualifying
# weekly_ma_spread/sector_rs_momentum values as a crude score stand-in since train-cut
# thresholds vary by window and this is a cross-window check.)
merged["score_proxy"] = merged["weekly_ma_spread"].rank(pct=True) + merged["sector_rs_momentum"].rank(pct=True)
top_half = merged[merged["score_proxy"] >= merged["score_proxy"].median()]
bot_half = merged[merged["score_proxy"] < merged["score_proxy"].median()]
for w in (1, 5):
    col = f"divergence_{w}d"
    th, bh = top_half[col].dropna(), bot_half[col].dropna()
    print(f"\ndivergence_{w}d, top-half score_proxy (n={len(th)}): mean={th.mean():+.4f} std={th.std():.4f}")
    print(f"divergence_{w}d, bottom-half score_proxy (n={len(bh)}): mean={bh.mean():+.4f} std={bh.std():.4f}")
    if len(th) >= 5 and len(bh) >= 5:
        u, p_mw = stats.mannwhitneyu(th, bh, alternative="two-sided")
        print(f"Mann-Whitney U (top vs bottom score_proxy): p={p_mw:.4g}")
