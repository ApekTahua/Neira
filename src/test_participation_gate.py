"""Self-check for V3_PARTICIPATION_GATE (docs/V3_FINDINGS_LOG.md, "Market-
wide participation gate ..."). Structurally different follow-up to the
REJECTED V3_TREND_DURATION_GATE (src/test_trend_duration_gate.py) -- this
gates on total market turnover (close_price * volume, summed across every
stock_code that day) vs its own trailing 20-day average, not on any
trend_strength/ma50-distance series. Two things a broken implementation
could silently get wrong:

  1. compute_market_participation() computes turnover_today / trailing_20d_
     average_turnover correctly (INCLUDING today in its own 20-day window,
     matching pandas' default rolling() behavior), and defaults early days
     with no 20-day history yet to a NEUTRAL 1.0 (gate always passes), not
     NaN (which would silently break any >= comparison) or 0.0 (which would
     silently block every entry until day 20).
  2. The flag defaults OFF, still overrides both ways via env var, and
     leaves TREND_DURATION_GATE_ENABLED/TREND_STRENGTH_MIN/REGIME_CONFIRM_
     DAYS's own defaults untouched -- this is a NEW, separate, isolated
     gate, not a change to any existing mechanism.

Usage: python src/test_participation_gate.py
"""

import os
import subprocess
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

os.environ.setdefault("V3_TEST_END", "2026-06-30")

REPO_SRC = os.path.dirname(os.path.abspath(__file__))

import backtest_v4 as bt  # noqa: E402

# ---- compute_market_participation: turnover_today / trailing-20d-average(including today) ----
n_days = 25
dates = [date(2023, 1, 2) + timedelta(days=i) for i in range(n_days)]  # calendar days fine, just needs to be sortable
# Two "stocks" whose close*volume sums to 100 every day except the last, which drops to 50.
rows = []
for i, d in enumerate(dates):
    turnover_total = 50.0 if i == n_days - 1 else 100.0
    rows.append({"stock_code": "AAA", "trade_date": d, "close_price": turnover_total / 2, "volume": 1.0})
    rows.append({"stock_code": "BBB", "trade_date": d, "close_price": turnover_total / 2, "volume": 1.0})
df = pd.DataFrame(rows)

ratio_by_date = bt.compute_market_participation(df)

# First 19 days (indices 0..18): rolling(20, min_periods=20) has no 20-day window yet -> neutral 1.0.
for i in range(19):
    r = ratio_by_date[dates[i]]
    assert r == 1.0, f"day {i} (no 20-day history yet) should default to neutral 1.0, got {r}"
print("[PASS] compute_market_participation defaults to neutral 1.0 before 20 days of history exist")

# Day 24 (0-indexed): its own trailing 20-day window covers days 5..24 -- 19 days at
# turnover=100 plus day 24 itself at turnover=50 -> mean = (19*100 + 50) / 20 = 97.5,
# ratio = 50 / 97.5.
expected_ratio_last = 50.0 / ((19 * 100.0 + 50.0) / 20.0)
got_ratio_last = ratio_by_date[dates[-1]]
assert abs(got_ratio_last - expected_ratio_last) < 1e-9, (
    f"day 24 ratio mismatch: got {got_ratio_last}, expected {expected_ratio_last}"
)
print(f"[PASS] compute_market_participation's rolling window includes today's own turnover "
      f"(ratio={got_ratio_last:.4f}, matches hand-computed {expected_ratio_last:.4f})")

# A quiet day (day 20, still turnover=100, well inside a 100-only trailing window) should
# read a full 1.0 -- no false signal on an unremarkable day.
mid_ratio = ratio_by_date[dates[20]]
assert abs(mid_ratio - 1.0) < 1e-9, f"unremarkable day should read ratio 1.0, got {mid_ratio}"
print("[PASS] compute_market_participation reads 1.0 on a day with no turnover deviation")


# ---- Flag defaults OFF, env var overrides both ways, cold-process import (real CI shape) ----
def _gate_flags(env_overrides: dict) -> str:
    env = dict(os.environ)
    for k in ("V3_PARTICIPATION_GATE", "V3_PARTICIPATION_MIN", "V3_TREND_DURATION_GATE", "V3_TREND_DURATION_MIN_DAYS"):
        env.pop(k, None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c",
         "import backtest_v4 as bt; print(bt.PARTICIPATION_GATE_ENABLED, bt.PARTICIPATION_MIN, "
         "bt.TREND_DURATION_GATE_ENABLED, bt.TREND_DURATION_MIN_DAYS, bt.TREND_STRENGTH_MIN, "
         "bt.REGIME_CONFIRM_DAYS)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()

assert _gate_flags({}) == "False 0.95 False 3 0.01 3", (
    "default must be OFF (min=0.95), and must NOT touch TREND_DURATION_GATE_ENABLED (False), "
    "TREND_DURATION_MIN_DAYS (3), TREND_STRENGTH_MIN (0.01), or REGIME_CONFIRM_DAYS's (3) own defaults"
)
assert _gate_flags({"V3_PARTICIPATION_GATE": "1", "V3_PARTICIPATION_MIN": "0.90"}) == (
    "True 0.9 False 3 0.01 3"
), "flipping the new flag must not flip TREND_DURATION_GATE_ENABLED's own default"
print("[PASS] V3_PARTICIPATION_GATE defaults OFF, overrides both ways, and every other "
      "gate's own default is untouched")

print("\nAll participation-gate checks passed.")
