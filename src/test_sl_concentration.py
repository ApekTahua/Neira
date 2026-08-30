"""Self-check for SL_CONCENTRATION_ENABLED (docs/V3_FINDINGS_LOG.md, "concentration-scaled
stop-loss width" entry -- idea #3 of this session's three-idea SL-width thread).

Direct unit-level checks on compute_entry_fill() itself (no walk-forward needed for the
polarity claim -- entry_price/atr/concentration are all inputs to one pure function):

  1. OFF (default) is neutral: sl_mult_effective == SL_MULT regardless of concentration.
  2. ON, high concentration (>= p90*MAX) widens the stop (sl_price farther from entry
     than OFF's).
  3. ON, low concentration (<= p90*MIN) tightens the stop (sl_price closer to entry).
  4. Missing concentration (None, the ~25% coverage gap) stays neutral, does not crash --
     same "missing data never blocks" convention BANDAR_SIZING_ENABLED's own bandar_mult
     uses.
  5. sl_price is IDENTICAL regardless of BANDAR_SIZING_ENABLED's own on/off state --
     confirms the SL-width path and the position-SIZE path are structurally separate at
     the price-computation level (the two multipliers are computed independently and
     never multiply each other). This does NOT by itself rule out the downstream sizing
     interaction the council flagged: sl_price feeds risk_per_share, which feeds
     lots_risk = prev_equity*RISK_PCT/risk_per_share, and alloc (which bandar_mult scales)
     is capped by lots_risk -- so the two effects can still interact at the LOTS level even
     though they don't interact at the PRICE level. That interaction is checked at the
     walk-forward level (src/sweep_sl_concentration.py, BANDAR_SIZING forced off), not here.

Usage: python src/test_sl_concentration.py
(no Supabase/dataset needed -- compute_entry_fill() is a pure function of its arguments)
"""

import backtest_v4 as bt

SIG_BASE = {"atr": 100.0, "tp_target": 1200.0, "score": 5.0, "adtv_20": 1e10, "avg_vol_20": 1_000_000.0}
ENTRY, CASH, PREV_EQUITY, LOG_ADTV_P90, CONC_P90 = 1000.0, 1e12, 1e9, 20.0, 1.0


def _fill(concentration):
    sig = dict(SIG_BASE, concentration=concentration)
    return bt.compute_entry_fill(sig, ENTRY, CASH, PREV_EQUITY, LOG_ADTV_P90,
                                  concentration_p90=CONC_P90)


# ---- (1) OFF is neutral regardless of concentration ----
bt.SL_CONCENTRATION_ENABLED = False
off_high = _fill(1.3)["sl_price"]
off_low = _fill(0.1)["sl_price"]
off_none = _fill(None)["sl_price"]
assert off_high == off_low == off_none, (
    f"OFF must ignore concentration entirely: got high={off_high} low={off_low} none={off_none}"
)
print(f"[PASS] OFF neutral: sl_price={off_high} regardless of concentration")

# ---- (2)/(3)/(4) ON: polarity + missing-data neutrality ----
bt.SL_CONCENTRATION_ENABLED = True
bt.SL_CONCENTRATION_MIN, bt.SL_CONCENTRATION_MAX = 0.8, 1.3
on_high = _fill(1.3)["sl_price"]   # ratio clipped to MAX -> widest stop -> lowest (farthest) sl_price
on_low = _fill(0.1)["sl_price"]    # ratio clipped to MIN -> tightest stop -> highest (closest) sl_price
on_none = _fill(None)["sl_price"]  # missing concentration -> neutral, same as OFF

assert on_high < off_high, f"high concentration must WIDEN the stop (lower sl_price): on={on_high} off={off_high}"
assert on_low > off_low, f"low concentration must TIGHTEN the stop (higher sl_price): on={on_low} off={off_low}"
assert on_high < on_low, f"high-concentration stop must be wider (farther) than low-concentration's: {on_high} vs {on_low}"
assert on_none == off_none, f"missing concentration must stay neutral even with the flag ON: on_none={on_none} off={off_none}"
print(f"[PASS] ON polarity correct: high_conc sl={on_high} (wider) < off={off_high} < low_conc sl={on_low} (tighter); "
      f"missing-data sl={on_none} == OFF")

# ---- (5) sl_price independent of BANDAR_SIZING_ENABLED ----
bt.BANDAR_SIZING_ENABLED = False
on_high_nobandar = _fill(1.3)["sl_price"]
bt.BANDAR_SIZING_ENABLED = True
on_high_bandar = _fill(1.3)["sl_price"]
assert on_high_nobandar == on_high == on_high_bandar, (
    f"sl_price must not depend on BANDAR_SIZING_ENABLED at the price-computation level: "
    f"{on_high_nobandar} vs {on_high} vs {on_high_bandar}"
)
print(f"[PASS] sl_price unaffected by BANDAR_SIZING_ENABLED toggle (structurally separate at the price level; "
      f"lots-level interaction is checked by the walk-forward sweep, not this unit check)")

bt.SL_CONCENTRATION_ENABLED = False  # restore default
print("\nAll 5 checks pass.")
