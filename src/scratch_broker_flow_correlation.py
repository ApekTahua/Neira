"""scratch_broker_flow_correlation.py -- SCRATCH/RESEARCH ONLY. Checks whether
the new market_broker_flow feature (src/backtest_v4.py, V4_BROKER_FLOW_GATE) is
independent information or just a proxy for the price-based regime/
trend_strength signal already gating entries, and for the OTHER market-wide
axis already tried (market_participation, turnover-based, REJECTED --
docs/V3_FINDINGS_LOG.md). Uses the SAME local cache (no Supabase needed) and
the SAME compute_regime_with_hysteresis/compute_market_participation/
compute_market_broker_flow functions the real backtest uses -- no re-typed
copy that could drift.

Run directly: python src/scratch_broker_flow_correlation.py
"""
import pickle

import numpy as np
import pandas as pd
from scipy import stats

import backtest_v4 as bt

CACHE_PATH = ".cache/walk_forward_data_2021-01-01_2026-06-30.pkl"

with open(CACHE_PATH, "rb") as f:
    df, idx_df = pickle.load(f)

regime_by_date, bullish_streak_by_date, trend_strength_by_date = bt.compute_regime_with_hysteresis(idx_df)
participation_by_date = bt.compute_market_participation(df)
flow_by_date = bt.compute_market_broker_flow(df, window_days=5)

dates = sorted(set(trend_strength_by_date) & set(flow_by_date))
print(f"overlapping days (trend_strength & broker_flow both defined): {len(dates)}")

trend = pd.Series({d: trend_strength_by_date[d] for d in dates})
flow = pd.Series({d: flow_by_date[d] for d in dates})
partic = pd.Series({d: participation_by_date.get(d, np.nan) for d in dates})

for name_a, a, name_b, b in [
    ("trend_strength", trend, "broker_flow (5d)", flow),
    ("market_participation (turnover)", partic, "broker_flow (5d)", flow),
]:
    mask = a.notna() & b.notna()
    rho, p = stats.spearmanr(a[mask], b[mask])
    pear, pp = stats.pearsonr(a[mask], b[mask])
    print(f"\n{name_a} vs {name_b} (n={mask.sum()}):")
    print(f"  Spearman rho = {rho:+.3f} (p={p:.4g})")
    print(f"  Pearson  r   = {pear:+.3f} (p={pp:.4g})")

# Also: does broker_flow separate the days regime_ok_today would ALREADY be True on
# (i.e. is it adding new information conditional on already-BULLISH-and-confirmed days,
# or just re-deriving the same "is the market up" read)?
regime_ok_mask = pd.Series({
    d: (regime_by_date.get(d, "NEUTRAL") == "BULLISH"
        and bullish_streak_by_date.get(d, 0) >= bt.REGIME_CONFIRM_DAYS
        and trend_strength_by_date.get(d, 0.0) >= bt.TREND_STRENGTH_MIN)
    for d in dates
})
flow_ok = flow[regime_ok_mask]
flow_not_ok = flow[~regime_ok_mask]
print(f"\nOn days regime_ok_today is already True (n={regime_ok_mask.sum()}): "
      f"broker_flow mean={flow_ok.mean():+.4f}, std={flow_ok.std():.4f}")
print(f"On days regime_ok_today is False (n={(~regime_ok_mask).sum()}): "
      f"broker_flow mean={flow_not_ok.mean():+.4f}, std={flow_not_ok.std():.4f}")
print(f"-> if broker_flow varies about as much WITHIN the already-qualifying days as "
      f"across all days, it's adding information on top of the existing gate, not just "
      f"re-flagging the same days as bullish.")
frac_flow_below_zero_when_ok = (flow_ok < 0).mean()
print(f"Fraction of already-regime_ok days where broker_flow < 0 (net selling despite "
      f"price-based bullish regime): {frac_flow_below_zero_when_ok:.1%}")
