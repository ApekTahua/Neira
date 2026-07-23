"""
phase0i_significance_test.py — is the weekly-trend + sector-RRG rule
actually better than randomly picking from the same regime-gated pool,
or could random selection produce a similarly good result?

Tonight involved testing many features/rules/thresholds across the whole
session -- implicit multiple-hypothesis-testing. A backtest looking good
after that much searching isn't automatically proof of skill; it could
be what you'd expect to find eventually by chance. This is a Monte Carlo
permutation test for the SELECTION step specifically (not the portfolio
mechanics, which are identical either way and don't need re-simulating):

  Null hypothesis: the weekly_ma_spread/sector_rs_momentum top-quintile
  filter has no real selection skill beyond "liquid stock, bullish
  regime" -- i.e. random picks from the same opportunity set would do
  just as well.

For each OOS window: take the opportunity set (liquid + bullish bars),
compute the actual rule's mean net-of-cost 20d return, then draw N random
same-size subsets from the opportunity set and build a null distribution
of mean returns. p-value = fraction of random draws that beat the actual
rule's mean. A small p-value (e.g. <0.05) means the rule is doing
something beyond chance.

Read-only, no Supabase writes, no portfolio simulation -- reuses
phase0e_ml_combined_model.build_dataset() rather than re-fetching.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0i_significance_test.py
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd
from supabase import create_client

from phase0e_ml_combined_model import build_dataset

N_PERMUTATIONS = 5000
RNG_SEED = 42

WINDOWS = [
    ("Window 1", date(2021, 1, 1), date(2024, 6, 30), date(2024, 7, 31), date(2026, 6, 30)),
    ("Window 2", date(2021, 1, 1), date(2023, 6, 30), date(2023, 7, 31), date(2024, 12, 31)),
]
QUANTILE_CUT = 0.80


def run_window(data: pd.DataFrame, label: str, train_end: date, test_start: date, test_end: date, rng: np.random.Generator):
    train = data[data["trade_date"] <= train_end]
    test = data[(data["trade_date"] >= test_start) & (data["trade_date"] <= test_end)]

    weekly_cut = train[train["is_bullish"] == 1]["weekly_ma_spread"].quantile(QUANTILE_CUT)
    sector_cut = train[train["is_bullish"] == 1]["sector_rs_momentum"].quantile(QUANTILE_CUT)

    opportunity = test[test["is_bullish"] == 1].copy()
    rule_mask = (opportunity["weekly_ma_spread"] >= weekly_cut) & (opportunity["sector_rs_momentum"] >= sector_cut)
    rule_picks = opportunity[rule_mask]

    n_picks = len(rule_picks)
    actual_mean = rule_picks["net_ret_20"].mean()
    actual_winrate = (rule_picks["net_ret_20"] > 0).mean()

    pool_returns = opportunity["net_ret_20"].dropna().to_numpy()
    n_pool = len(pool_returns)

    null_means = np.empty(N_PERMUTATIONS)
    for i in range(N_PERMUTATIONS):
        sample = rng.choice(pool_returns, size=n_picks, replace=False)
        null_means[i] = sample.mean()

    p_value = (null_means >= actual_mean).mean()

    print(f"\n{'=' * 100}\n{label} ({test_start}..{test_end})\n{'=' * 100}")
    print(f"  Opportunity set (liquid + bullish bars): {n_pool}")
    print(f"  Rule-selected picks: {n_picks}  |  actual mean net_ret_20: {actual_mean*100:.2f}%  |  actual win rate: {actual_winrate*100:.1f}%")
    print(f"  Null distribution (random {n_picks}-sized draws from opportunity set, {N_PERMUTATIONS} trials):")
    print(f"    mean={null_means.mean()*100:.2f}%  std={null_means.std()*100:.2f}%  "
          f"p5={np.percentile(null_means,5)*100:.2f}%  p50={np.percentile(null_means,50)*100:.2f}%  p95={np.percentile(null_means,95)*100:.2f}%")
    print(f"  P-VALUE (fraction of random draws beating the actual rule's mean): {p_value:.4f}")
    verdict = "SIGNIFICANT (p<0.05) -- rule beats chance" if p_value < 0.05 else "NOT significant at p<0.05 -- can't rule out chance"
    print(f"  VERDICT: {verdict}")


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 100)
    print("PHASE 0i -- Monte Carlo permutation significance test: rule vs random selection")
    print("=" * 100)

    data = build_dataset(supabase)
    rng = np.random.default_rng(RNG_SEED)

    for label, _fetch_start, train_end, test_start, test_end in WINDOWS:
        run_window(data, label, train_end, test_start, test_end, rng)


if __name__ == "__main__":
    main()
