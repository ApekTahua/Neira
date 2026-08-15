"""Dry-run self-check for backtest_v4._accdist_aggregate() and
_accdist_score_p90() -- the aggregation step and the train-derived scaling
step behind ACCDIST_SIZING_ENABLED (see attach_accdist_signal's docstring
and docs/BANDARMOLOGY_DESIGN.md, "Directional Big/Small
Accumulation/Distribution classifier"). No Supabase or local Parquet
backfill needed -- tests both directly against small synthetic frames.

Usage: python src/test_accdist_signal.py
"""

import os
from datetime import date

os.environ.setdefault("V3_TEST_END", "2026-06-30")

import pandas as pd  # noqa: E402

from backtest_v4 import _accdist_aggregate, _accdist_score_p90  # noqa: E402

D1, D2 = date(2026, 1, 5), date(2026, 1, 6)

# Two candidate movers: broker AA predicted bullish (+1) for BBCA,
# broker BB predicted bearish (-1) for BBCA. Broker CC predicted bullish
# for TLKM but isn't a candidate mover for anything else that day.
movers = pd.DataFrame([
    {"stock_code": "BBCA", "broker_code": "AA", "predicted_sign": 1.0},
    {"stock_code": "BBCA", "broker_code": "BB", "predicted_sign": -1.0},
    {"stock_code": "TLKM", "broker_code": "CC", "predicted_sign": 1.0},
])

broker_net = pd.DataFrame([
    # D1, BBCA: AA net-buys (qualifies, sign(net_lot)=+1 == predicted_sign=+1)
    #           -> contributes +net_val (2_000_000_000)
    {"trade_date": D1, "stock_code": "BBCA", "broker_code": "AA", "net_lot": 500, "net_val": 2_000_000_000.0},
    # D1, BBCA: BB net-SELLS (qualifies, sign(net_lot)=-1 == predicted_sign=-1)
    #           -> contributes predicted_sign(-1) * |net_val| = -1_000_000_000
    #           (the exact case mover_score gets wrong: this is a bearish-
    #           predicting event but an unsigned count would add +1 same as AA's row)
    {"trade_date": D1, "stock_code": "BBCA", "broker_code": "BB", "net_lot": -300, "net_val": -1_000_000_000.0},
    # D1, BBCA: AA net-SELLS -- does NOT qualify (sign(net_lot)=-1 != predicted_sign=+1),
    # must be excluded entirely, not counted with a flipped sign.
    {"trade_date": D2, "stock_code": "BBCA", "broker_code": "AA", "net_lot": -100, "net_val": -400_000_000.0},
    # D1, TLKM: CC net-buys, qualifies -> contributes +net_val
    {"trade_date": D1, "stock_code": "TLKM", "broker_code": "CC", "net_lot": 200, "net_val": 500_000_000.0},
    # D1, GOTO: no candidate-mover row at all for this stock -- inner-joins
    # away entirely, must not appear in the output (this is the "0 vs NaN"
    # boundary attach_accdist_signal's own fillna(0)-after-coverage-start
    # handles one layer up, not this function's job).
    {"trade_date": D1, "stock_code": "GOTO", "broker_code": "ZZ", "net_lot": 100, "net_val": 300_000_000.0},
])

out = _accdist_aggregate(broker_net, movers)
by_key = {(r.stock_code, r.trade_date): r.accdist_score for r in out.itertuples()}

# BBCA/D1: AA's +2.0B and BB's -1.0B sum to +1.0B net -- signed, not the
# unsigned count of 2 that mover_score would have produced for this exact day.
assert by_key[("BBCA", D1)] == 1_000_000_000.0, by_key[("BBCA", D1)]
# BBCA/D2: AA's row that day doesn't qualify (sign mismatch) -> no row at all.
assert ("BBCA", D2) not in by_key, "non-qualifying event must be excluded, not zeroed"
# TLKM/D1: single qualifying bullish event -> +net_val exactly.
assert by_key[("TLKM", D1)] == 500_000_000.0, by_key[("TLKM", D1)]
# GOTO: no candidate-mover row for this stock at all -> excluded by the inner join.
assert ("GOTO", D1) not in by_key, "stock with no flagged movers must be excluded, not zeroed"
assert len(out) == 2, f"expected exactly 2 (stock_code, trade_date) groups, got {len(out)}"

print("[PASS] signed magnitude-weighted aggregation matches expected sums")
print("[PASS] non-qualifying (sign-mismatched) events excluded, not flipped")
print("[PASS] stocks/days with no qualifying events produce no row")

# _accdist_score_p90: reproduces the real bug (mostly-zero population ->
# plain quantile(0.90) lands at 0.0 -> degenerate <=0 fallback trips every
# time) and confirms the fix (restrict to nonzero, take abs magnitude).
mostly_zero = pd.Series([0.0] * 92 + [2_000_000_000.0, -1_500_000_000.0,
                                       3_000_000_000.0, -800_000_000.0,
                                       1_200_000_000.0, 900_000_000.0,
                                       700_000_000.0, 4_000_000_000.0])
# The bug this replaces: a plain quantile(0.90) over this same population
# lands at exactly 0.0 (92%+ of the mass is zero).
assert mostly_zero.quantile(0.90) == 0.0, "fixture no longer reproduces the original bug"
p90 = _accdist_score_p90(mostly_zero)
assert p90 > 0, f"fixed p90 must be a positive Rupiah-scale reference, got {p90}"
expected = mostly_zero[mostly_zero != 0].abs().quantile(0.90)
assert p90 == expected, (p90, expected)

# All-zero train population (genuine edge case: zero nonzero days) -> the
# degenerate fallback should still trip, same as before the fix.
assert _accdist_score_p90(pd.Series([0.0, 0.0, 0.0])) == 1.0
# Empty series -> same fallback.
assert _accdist_score_p90(pd.Series([], dtype=float)) == 1.0

print("[PASS] _accdist_score_p90 is no longer dominated by the zero-mass "
      f"(mostly-zero fixture: broken quantile=0.0, fixed p90={p90:,.0f})")
print("[PASS] _accdist_score_p90 still falls back to 1.0 for a genuinely "
      "all-zero/empty train population")

print("\nAll backtest_v4._accdist_aggregate / _accdist_score_p90 checks passed.")
