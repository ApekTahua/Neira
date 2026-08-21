"""Self-check for V4_TREND_DURATION_GATE (docs/V3_FINDINGS_LOG.md, "Trend-
duration/episode-quality gate ..."). Two things a broken implementation
could silently get wrong:

  1. compute_trend_duration_streak() actually counts CONSECUTIVE days above
     threshold, resetting on any dip below it -- not a cumulative/leaky
     count. Checked directly against a synthetic series shaped like the
     real Feb 2023 episode (bounces above/below 1% repeatedly).
  2. The flag defaults OFF, still overrides both ways via env var, and
     leaves TREND_STRENGTH_MIN/REGIME_CONFIRM_DAYS's own defaults
     untouched -- this is a NEW, separate gate, not a change to either
     existing mechanism.

Usage: python src/test_trend_duration_gate.py
"""

import os
import subprocess
import sys
from datetime import date, timedelta

os.environ.setdefault("V4_TEST_END", "2026-06-30")

REPO_SRC = os.path.dirname(os.path.abspath(__file__))

import backtest_v4 as bt  # noqa: E402

# ---- compute_trend_duration_streak: consecutive-days-above-threshold, resets on any dip ----
d0 = date(2023, 2, 1)
dates = [d0 + timedelta(days=i) for i in range(9)]
# Shaped like the real 2023-02-03..02-20 episode: crosses 1%, dips, re-crosses, dips again.
values = [0.0121, 0.0071, 0.0163, 0.0173, 0.0115, 0.0095, 0.0127, 0.0190, 0.0074]
trend_strength_by_date = dict(zip(dates, values))
streak = bt.compute_trend_duration_streak(trend_strength_by_date, threshold=0.01)
expected = [1, 0, 1, 2, 3, 0, 1, 2, 0]  # 0.0071 and 0.0095 dip below 0.01 -> reset; 0.0074 too
assert list(streak.values()) == expected, f"streak mismatch: {list(streak.values())} != {expected}"
print("[PASS] compute_trend_duration_streak resets on any dip below threshold, "
      "matches the hand-traced Feb 2023 episode shape")

# A day that never dips should just count up.
sustained = {d0 + timedelta(days=i): 0.05 for i in range(5)}
sustained_streak = bt.compute_trend_duration_streak(sustained, threshold=0.01)
assert list(sustained_streak.values()) == [1, 2, 3, 4, 5], "sustained separation must count up cleanly"
print("[PASS] compute_trend_duration_streak counts up cleanly with no dips (window-1-like)")


# ---- Flag defaults OFF, env var overrides both ways, cold-process import (real CI shape) ----
def _gate_flags(env_overrides: dict) -> str:
    env = dict(os.environ)
    env.pop("V4_TREND_DURATION_GATE", None)
    env.pop("V4_TREND_DURATION_MIN_DAYS", None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c",
         "import backtest_v4 as bt; print(bt.TREND_DURATION_GATE_ENABLED, bt.TREND_DURATION_MIN_DAYS, "
         "bt.TREND_STRENGTH_MIN, bt.REGIME_CONFIRM_DAYS)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()

assert _gate_flags({}) == "False 3 0.01 3", (
    "default must be OFF (min_days=3), and must NOT touch TREND_STRENGTH_MIN (0.01) "
    "or REGIME_CONFIRM_DAYS's (3) own defaults"
)
assert _gate_flags({"V4_TREND_DURATION_GATE": "1", "V4_TREND_DURATION_MIN_DAYS": "5"}) == "True 5 0.01 3"
print("[PASS] V4_TREND_DURATION_GATE defaults OFF, overrides both ways, "
      "TREND_STRENGTH_MIN/REGIME_CONFIRM_DAYS defaults untouched")

print("\nAll trend-duration-gate checks passed.")
