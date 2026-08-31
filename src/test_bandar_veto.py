"""Self-check for BANDAR_VETO_ENABLED (docs/V3_FINDINGS_LOG.md, 2026-08-31 entry --
hard admit/reject veto, categorically different from BANDAR_SIZING_ENABLED's continuous
size multiplier and from today's three earlier SL-width ideas).

Direct unit-level checks on bandar_veto_fires() itself (no walk-forward/dataset needed --
concentration/concentration_p90/net_lot are its only inputs, same pure-function style as
test_sl_concentration.py's checks on compute_entry_fill()):

  1. Missing concentration (None) never vetoes, regardless of net_lot -- fail open.
  2. Low concentration + net SELLING (negative net_lot) -- the design's actual target
     case -- fires.
  3. Low concentration + net BUYING (positive net_lot) does NOT fire -- concentration
     alone is not enough; net_lot's sign is required (this is the whole point of using
     net_lot at all: concentration is unsigned).
  4. High concentration + net selling does NOT fire -- both conditions are required, not
     either alone.
  5. Threshold is a RATIO to concentration_p90, not an absolute value -- the same raw
     concentration can fire or not depending on concentration_p90 (train-window-relative,
     matching BANDAR_SIZING_ENABLED/SL_CONCENTRATION_ENABLED's own convention).

Usage: python src/test_bandar_veto.py
"""

import backtest_v4 as bt

bt.BANDAR_VETO_CONCENTRATION_MAX = 0.3
bt.BANDAR_VETO_NET_LOT_MIN = 0.0
CONC_P90 = 1.0  # ratio == raw concentration value at this p90

# ---- (1) missing concentration never vetoes ----
assert bt.bandar_veto_fires(None, CONC_P90, net_lot=-5000) is False
print("[PASS] missing concentration never vetoes, regardless of net_lot")

# ---- (2) low concentration + net selling -- fires ----
assert bt.bandar_veto_fires(0.2, CONC_P90, net_lot=-5000) is True
print("[PASS] low concentration (0.2 < 0.3) + net selling (-5000) fires")

# ---- (3) low concentration + net BUYING -- does not fire ----
assert bt.bandar_veto_fires(0.2, CONC_P90, net_lot=5000) is False
print("[PASS] low concentration + net BUYING does not fire -- direction matters")

# ---- (4) high concentration + net selling -- does not fire ----
assert bt.bandar_veto_fires(0.8, CONC_P90, net_lot=-5000) is False
print("[PASS] high concentration + net selling does not fire -- both conditions required")

# ---- (5) ratio-to-p90, not absolute ----
# concentration=0.4 vs a low p90 (0.5) -> ratio 0.8, above the 0.3 threshold -> no veto
assert bt.bandar_veto_fires(0.4, 0.5, net_lot=-5000) is False
# same raw concentration=0.4 vs a high p90 (2.0) -> ratio 0.2, below 0.3 -> vetoes
assert bt.bandar_veto_fires(0.4, 2.0, net_lot=-5000) is True
print("[PASS] threshold is relative to concentration_p90 (train-window-relative), "
      "not an absolute concentration value")

print("\nAll 5 checks pass.")
