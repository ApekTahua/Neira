"""Dry-run self-check for backtest_v4._rotation_aggregate() and
_rotation_score_p90() -- the aggregation step and the train-derived scaling
step behind ROTATION_SIZING_ENABLED (see attach_rotation_signal's docstring
and docs/BANDARMOLOGY_DESIGN.md, "rotation_pairs V4 sizing candidate").
No Supabase or local Parquet backfill needed -- tests both directly against
small synthetic frames.

Usage: python src/test_rotation_signal.py
"""

import os
from datetime import date

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import pandas as pd  # noqa: E402

from backtest_v4 import _rotation_aggregate, _rotation_score_p90  # noqa: E402

D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)

# Two flagged rotation pairs: (AA, BB) for BBCA, (CC, DD) for TLKM.
# find_rotation_pairs sorts broker_a/broker_b alphabetically, but this
# aggregation must not care which side ends up "a" vs "b" -- symmetric by
# construction, no predicted_sign the way candidate_movers has one.
pairs = pd.DataFrame([
    {"stock_code": "BBCA", "broker_a": "AA", "broker_b": "BB"},
    {"stock_code": "TLKM", "broker_a": "CC", "broker_b": "DD"},
])

broker_net = pd.DataFrame([
    # D1, BBCA: AA net-buys 2.0B, BB net-sells 1.0B -- OPPOSITE sides,
    # overlap = min(2.0B, 1.0B) = 1.0B.
    {"trade_date": D1, "stock_code": "BBCA", "broker_code": "AA", "net_lot": 500, "net_val": 2_000_000_000.0},
    {"trade_date": D1, "stock_code": "BBCA", "broker_code": "BB", "net_lot": -300, "net_val": -1_000_000_000.0},
    # D2, BBCA: AA net-buys, BB ALSO net-buys -- SAME side, does not qualify
    # as a rotation event no matter how large the value.
    {"trade_date": D2, "stock_code": "BBCA", "broker_code": "AA", "net_lot": 400, "net_val": 1_500_000_000.0},
    {"trade_date": D2, "stock_code": "BBCA", "broker_code": "BB", "net_lot": 200, "net_val": 900_000_000.0},
    # D3, BBCA: only AA active, BB not active at all -- must not appear
    # (inner join on both sides required, not a partial match).
    {"trade_date": D3, "stock_code": "BBCA", "broker_code": "AA", "net_lot": 100, "net_val": 300_000_000.0},
    # D1, TLKM: CC net-sells 3.0B, DD net-buys 500M -- opposite sides,
    # overlap = min(3.0B, 500M) = 500M (the SMALLER side caps the overlap).
    {"trade_date": D1, "stock_code": "TLKM", "broker_code": "CC", "net_lot": -800, "net_val": -3_000_000_000.0},
    {"trade_date": D1, "stock_code": "TLKM", "broker_code": "DD", "net_lot": 150, "net_val": 500_000_000.0},
    # D1, GOTO: no flagged pair at all for this stock -- inner-joins away.
    {"trade_date": D1, "stock_code": "GOTO", "broker_code": "ZZ", "net_lot": 100, "net_val": 300_000_000.0},
])

out = _rotation_aggregate(broker_net, pairs)
by_key = {(r.stock_code, r.trade_date): r.rotation_score for r in out.itertuples()}

# BBCA/D1: opposite sides -> overlap = min(2.0B, 1.0B) = 1.0B, UNSIGNED
# (not accdist's signed sum -- rotation has no predicted_sign to weight by).
assert by_key[("BBCA", D1)] == 1_000_000_000.0, by_key[("BBCA", D1)]
# BBCA/D2: same side -> excluded entirely, no row.
assert ("BBCA", D2) not in by_key, "same-side day must be excluded, not scored"
# BBCA/D3: only one broker active -> excluded (inner join, no partial match).
assert ("BBCA", D3) not in by_key, "day with only one side active must be excluded"
# TLKM/D1: opposite sides -> overlap = min(3.0B, 0.5B) = 0.5B (smaller side wins).
assert by_key[("TLKM", D1)] == 500_000_000.0, by_key[("TLKM", D1)]
# GOTO: no flagged pair for this stock -> excluded by the inner join.
assert ("GOTO", D1) not in by_key, "stock with no flagged rotation pair must be excluded"
assert len(out) == 2, f"expected exactly 2 (stock_code, trade_date) groups, got {len(out)}"
assert (out["rotation_score"] >= 0).all(), "rotation_score must be unsigned (magnitude, not signed)"

print("[PASS] unsigned overlap-magnitude aggregation matches expected sums")
print("[PASS] same-side days excluded, not scored")
print("[PASS] days with only one side of a flagged pair active are excluded")
print("[PASS] stocks with no flagged rotation pair produce no row")

# Empty pairs frame (e.g. a data slice with no flagged pairs at all) ->
# empty result with the right columns, not a crash.
empty_out = _rotation_aggregate(broker_net, pairs.iloc[0:0])
assert list(empty_out.columns) == ["stock_code", "trade_date", "rotation_score"]
assert len(empty_out) == 0
print("[PASS] empty pairs frame produces an empty, correctly-shaped result")

# _rotation_score_p90: same sparsity failure mode as accdist_score_p90 --
# a plain quantile(0.90) over a mostly-zero population lands at/near 0.0,
# which would trip the degenerate <=0 fallback almost every window instead
# of only for the genuine no-signal case.
mostly_zero = pd.Series([0.0] * 92 + [2_000_000_000.0, 1_500_000_000.0, 3_000_000_000.0,
                                       800_000_000.0, 1_200_000_000.0, 900_000_000.0,
                                       700_000_000.0, 4_000_000_000.0])
assert mostly_zero.quantile(0.90) == 0.0, "fixture no longer reproduces the sparsity failure mode"
p90 = _rotation_score_p90(mostly_zero)
assert p90 > 0, f"fixed p90 must be a positive Rupiah-scale reference, got {p90}"
expected = mostly_zero[mostly_zero != 0].quantile(0.90)
assert p90 == expected, (p90, expected)

# All-zero train population (genuine edge case: zero nonzero days) -> the
# degenerate fallback should still trip.
assert _rotation_score_p90(pd.Series([0.0, 0.0, 0.0])) == 1.0
# Empty series -> same fallback.
assert _rotation_score_p90(pd.Series([], dtype=float)) == 1.0

print("[PASS] _rotation_score_p90 is not dominated by the zero-mass "
      f"(mostly-zero fixture: plain quantile=0.0, fixed p90={p90:,.0f})")
print("[PASS] _rotation_score_p90 still falls back to 1.0 for a genuinely "
      "all-zero/empty train population")

print("\nAll backtest_v4._rotation_aggregate / _rotation_score_p90 checks passed.")
