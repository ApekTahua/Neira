"""Dry-run self-check for backtest_v3._accdist_aggregate() -- the core
aggregation step behind ACCDIST_SIZING_ENABLED (see attach_accdist_signal's
docstring and docs/BANDARMOLOGY_DESIGN.md, "Directional Big/Small
Accumulation/Distribution classifier"). No Supabase or local Parquet
backfill needed -- tests the signed, magnitude-weighted aggregation
directly against small synthetic broker_net/movers frames.

Usage: python src/test_accdist_signal.py
"""

import os
from datetime import date

os.environ.setdefault("V3_TEST_END", "2026-06-30")

import pandas as pd  # noqa: E402

from backtest_v3 import _accdist_aggregate  # noqa: E402

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
print("\nAll backtest_v3._accdist_aggregate checks passed.")
