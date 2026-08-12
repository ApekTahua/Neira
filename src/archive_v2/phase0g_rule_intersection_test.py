"""
phase0g_rule_intersection_test.py — does the EXPLICIT intersection of the
two validated real features (weekly-trend alignment, sector RRG) in
BULLISH regime beat either alone? Tested as a plain rule, not ML — Phase
0e's combined gradient-boosted model came back weak (AUC~0.50) and gave
the two known-good univariate features NEGATIVE permutation importance,
which smells like noise-drowning from the 8 other weak/dead features fed
into that model, or the model failing to find the interaction cleanly.
This tests the direct hypothesis with no black box in between.

Thresholds for "top quintile" are learned ONLY on a TRAIN split
(2021-01-01..2024-06-30) and applied as fixed numeric cutoffs to a
held-out TEST split (2024-07-01..2026-06-30) — avoids the in-sample
cherry-picking that a single qcut over the whole dataset would allow.

Reports win rate / mean / median forward return at 5/10/20d for:
  - full liquid baseline
  - BULLISH regime alone
  - BULLISH + weekly_ma_spread top-quintile alone
  - BULLISH + sector_rs_momentum top-quintile alone
  - BULLISH + BOTH top-quintile (the intersection)
plus the top-5-ticker concentration check on the intersection at 20d —
same discipline as the ML model.

Read-only, no Supabase writes.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0g_rule_intersection_test.py
"""

import os
import sys
from datetime import date

import pandas as pd
from supabase import create_client

from phase0e_ml_combined_model import build_dataset, concentration_check

TRAIN_END = date(2024, 6, 30)
TEST_START = date(2024, 7, 31)
QUANTILE_CUT = 0.80  # "top quintile" cutoff learned on train only


def report(label: str, mask: pd.Series, test: pd.DataFrame):
    sub = test[mask]
    if sub.empty:
        print(f"{label:55s} n=0 (no rows)")
        return
    row = {"n": len(sub)}
    for h in (5, 10, 20):
        col = f"fwd_ret_{h}"
        r = sub[col].dropna()
        if r.empty:
            continue
        row[f"win_{h}d"] = f"{(r>0).mean()*100:.1f}%"
        row[f"mean_{h}d"] = f"{r.mean()*100:.2f}%"
        row[f"median_{h}d"] = f"{r.median()*100:.2f}%"
    print(f"{label:55s} " + "  ".join(f"{k}={v}" for k, v in row.items()))


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 110)
    print("PHASE 0g — Explicit rule intersection: BULLISH + weekly-trend Q5 + sector-RRG Q5 (no ML)")
    print("=" * 110)

    data = build_dataset(supabase)
    train = data[data["trade_date"] <= TRAIN_END]
    test = data[data["trade_date"] >= TEST_START]
    print(f"[SPLIT] train n={len(train)} ({data['trade_date'].min()}..{TRAIN_END}), "
          f"test n={len(test)} ({TEST_START}..{data['trade_date'].max()})")

    weekly_cut = train["weekly_ma_spread"].quantile(QUANTILE_CUT)
    sector_cut = train["sector_rs_momentum"].quantile(QUANTILE_CUT)
    print(f"[THRESHOLDS from train only] weekly_ma_spread >= {weekly_cut:.2f}, sector_rs_momentum >= {sector_cut:.4f}")

    bullish = test["is_bullish"] == 1
    weekly_top = test["weekly_ma_spread"] >= weekly_cut
    sector_top = test["sector_rs_momentum"] >= sector_cut

    print("\n" + "-" * 110)
    print(f"{'Rule':55s} stats (out-of-sample test period only)")
    print("-" * 110)
    report("Full liquid baseline (no filter)", pd.Series(True, index=test.index), test)
    report("BULLISH regime alone", bullish, test)
    report("BULLISH + weekly_trend top-quintile ONLY", bullish & weekly_top, test)
    report("BULLISH + sector_RRG top-quintile ONLY", bullish & sector_top, test)
    report("BULLISH + BOTH top-quintile (intersection)", bullish & weekly_top & sector_top, test)

    intersection = test[bullish & weekly_top & sector_top]
    print(f"\n[CONCENTRATION CHECK] intersection rule, 20d net-of-cost contribution:")
    print("  " + concentration_check(intersection) if not intersection.empty else "  n/a (no rows matched)")


if __name__ == "__main__":
    main()
