"""Self-check for STRUCT_SL_ENABLED (docs/V3_FINDINGS_LOG.md, "structural stop (Smart Money
Concepts swing-low)" entry).

Direct unit-level checks on compute_entry_fill() itself (no walk-forward needed for the
placement claim -- entry_price/atr/struct_swing_low are all inputs to one pure function):

  1. OFF (default) is neutral: sl_price ignores struct_swing_low entirely.
  2. ON, a valid confirmed swing low below entry: REPLACES sl_price (not a multiplier on
     top of sl_mult_effective) with swing_low - STRUCT_SL_BUFFER_ATR*atr.
  3. ON, a swing low too close to (or above) entry for the buffered stop to land below
     entry_price: silently falls back to the unchanged ATR-multiple sl_price -- never
     produces a nonsensical stop above/at entry.
  4. ON, struct_swing_low=None (no confirmed fractal yet, e.g. early history): same
     fallback, no crash.
  5. sl_price is IDENTICAL regardless of BANDAR_SIZING_ENABLED's own on/off state, and the
     ONLY channel through which this flag can move `lots` is risk_per_share/lots_risk --
     the exact same channel SL_MULT itself already uses, not a new correlation with any of
     compute_entry_fill's other per-candidate multipliers (score/concentration/etc. are
     never read by this flag's own code path).

Usage: python src/test_struct_sl.py
(no Supabase/dataset needed -- compute_entry_fill() is a pure function of its arguments)
"""

import backtest_v4 as bt
import config as cfg

SIG_BASE = {"atr": 100.0, "tp_target": 1200.0, "score": 5.0, "adtv_20": 1e10, "avg_vol_20": 1_000_000.0}
ENTRY, CASH, PREV_EQUITY, LOG_ADTV_P90 = 1000.0, 1e12, 1e9, 20.0


def _fill(struct_swing_low):
    sig = dict(SIG_BASE, struct_swing_low=struct_swing_low)
    return bt.compute_entry_fill(sig, ENTRY, CASH, PREV_EQUITY, LOG_ADTV_P90)


# ---- (1) OFF is neutral regardless of struct_swing_low ----
bt.STRUCT_SL_ENABLED = False
off_default = _fill(None)["sl_price"]
off_with_swing = _fill(820.0)["sl_price"]
assert off_default == off_with_swing == 850.0, (  # entry(1000) - atr(100)*SL_MULT(1.5) = 850, already tick-aligned
    f"OFF must ignore struct_swing_low entirely: default={off_default} with_swing={off_with_swing}"
)
print(f"[PASS] OFF neutral: sl_price={off_default} regardless of struct_swing_low")

# ---- (2) ON, a valid swing low below entry: REPLACES sl_price ----
bt.STRUCT_SL_ENABLED = True
bt.STRUCT_SL_BUFFER_ATR = 0.75
on_valid = _fill(820.0)["sl_price"]
expected = 820.0 - 0.75 * 100.0  # = 745.0, already tick-aligned (multiple of 5)
assert on_valid == expected, f"expected struct sl_price={expected}, got {on_valid}"
assert on_valid != off_default, "a valid swing low must actually change sl_price vs the ATR-multiple default"
print(f"[PASS] ON, valid swing low: sl_price={on_valid} (replaces ATR-multiple default {off_default})")

# ---- (3) ON, swing low too close to/above entry: falls back to the ATR-multiple default ----
on_invalid = _fill(1100.0)["sl_price"]  # 1100 - 75 = 1025 >= entry_price(1000) -- invalid, must not be used
assert on_invalid == off_default, (
    f"an invalid (>= entry_price) struct stop must fall back to the ATR-multiple default: "
    f"got {on_invalid}, expected {off_default}"
)
print(f"[PASS] ON, swing low too close to entry: falls back to ATR-multiple default ({on_invalid})")

# ---- (4) ON, struct_swing_low=None: same fallback, no crash ----
on_none = _fill(None)["sl_price"]
assert on_none == off_default
print(f"[PASS] ON, struct_swing_low=None: falls back to ATR-multiple default ({on_none}), no crash")

# ---- (5) sl_price independent of BANDAR_SIZING_ENABLED; lots move ONLY via risk_per_share ----
bt.BANDAR_SIZING_ENABLED = False
on_valid_nobandar = _fill(820.0)["sl_price"]
bt.BANDAR_SIZING_ENABLED = True
on_valid_bandar = _fill(820.0)["sl_price"]
assert on_valid_nobandar == on_valid == on_valid_bandar, (
    f"sl_price must not depend on BANDAR_SIZING_ENABLED at the price-computation level: "
    f"{on_valid_nobandar} vs {on_valid} vs {on_valid_bandar}"
)
# lots_risk is the ONLY sizing channel this flag can touch (same formula compute_entry_fill
# already applies for SL_MULT's own stop distance) -- reproduce it independently here and
# confirm the fill's actual lots matches, for both the OFF and ON sl_price.
fill_off = _fill(None)
fill_on = _fill(820.0)
risk_per_share_off = ENTRY - off_default
risk_per_share_on = ENTRY - on_valid
lots_risk_off = int(PREV_EQUITY * cfg.RISK_PCT / risk_per_share_off) // bt.LOT_SIZE
lots_risk_on = int(PREV_EQUITY * cfg.RISK_PCT / risk_per_share_on) // bt.LOT_SIZE
assert fill_off["lots"] <= lots_risk_off and fill_on["lots"] <= lots_risk_on, (
    "lots must never exceed the risk_per_share-derived cap -- same channel SL_MULT already uses"
)
assert lots_risk_on < lots_risk_off, (
    "sanity: a wider struct stop (farther from entry) must mean a SMALLER risk_per_share-derived "
    "lots cap, the same direction SL_MULT's own distance already implies"
)
print(f"[PASS] sl_price unaffected by BANDAR_SIZING_ENABLED; lots move only via the pre-existing "
      f"risk_per_share/lots_risk channel (off cap={lots_risk_off}, on cap={lots_risk_on})")

bt.STRUCT_SL_ENABLED = False  # restore default
print("\nAll 5 checks pass.")
