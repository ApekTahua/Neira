"""Self-check for TRAIL_ATR_ENABLED (docs/V3_FINDINGS_LOG.md, "ATR-scaled trailing stop
(UT Bot style)" entry).

Direct unit-level checks on evaluate_position_exit() itself (no walk-forward needed for the
mechanical claim -- pos/bar/current_atr are all plain inputs to one function):

  1. OFF (default): current_atr is read but ignored -- reproduces the exact flat-%
     TRAILING outcome test_paper_trading_math.py's own
     test_evaluate_position_exit_trailing fixture already asserts (regression check).
  2. ON, current_atr present and finite: trailing_stop is genuinely recomputed off TODAY's
     ATR, not the flat %, and fires at a bar the flat version would NOT have -- the real
     behavior-change claim, not just "does it run without crashing."
  3. ON, current_atr=None (a real data gap): falls back to the exact same flat-% trail as
     OFF on the same bar -- no crash, no silently-stale value used.
  4. ON, current_atr=0.0 / NaN (a real bad-data value, not just missing): same fallback,
     same "never crashes" guarantee.

Usage: python src/test_trail_atr.py
(no Supabase/dataset needed -- evaluate_position_exit() is a pure function of its arguments)
"""

from datetime import date

import backtest_v4 as bt
import config as cfg


def _base_position(**overrides):
    pos = {
        "stock_code": "TEST", "entry_date": date(2026, 7, 20), "avg_price": 1015.0,
        "tp1_price": 1030.0, "sl_price": 1000.0, "total_lots": 373, "remaining_lots": 373,
        "cost_basis": 373 * bt.LOT_SIZE * 1015.0 * (1 + cfg.BUY_FEE),
        "hold_days": 5, "tp1_hit": True, "tp2_hit": False, "highest_price": 1100.0,
        "trigger": "TEST", "checkpoint_day": None, "target_price": 1200.0,
        "entry_price_original": 1015.0, "atr_at_entry": 20.0, "avg_vol_20": 1e7,
    }
    pos.update(overrides)
    return pos


ARGS = ("BULLISH", 0.02, date(2026, 7, 28), 100_000_000.0, 20_000_000.0)

# ---- (1) OFF: current_atr is read but ignored, byte-identical to the existing flat-%
# TRAILING regression fixture ----
bt.TRAIL_ATR_ENABLED = False
bar1 = (1050.0, 1010.0, 1060.0, 1005.0)  # low stays above sl_price(1000); close breaches flat trailing stop (1012)
trade_off, _ = bt.evaluate_position_exit(_base_position(), bar1, *ARGS, current_atr=999.0)  # present but must be ignored
assert trade_off is not None and trade_off["exit_reason"] == "TRAILING"
assert abs(trade_off["exit_price"] - 1010.0) < 0.01
print(f"[PASS] OFF: current_atr ignored, flat-% TRAILING fires exactly as before (exit={trade_off['exit_price']})")

# ---- fixture assumption check: at bar2, the flat 8% trail (stop=1012) should NOT fire ----
bar2 = (1030.0, 1035.0, 1040.0, 1025.0)
trade_assumption, _ = bt.evaluate_position_exit(_base_position(), bar2, *ARGS)
assert trade_assumption is None, "fixture assumption broken -- flat trail should NOT fire at close=1035"

# ---- (2) ON: a real behavior change -- a tighter ATR-derived trail (stop=1100-30*2=1040)
# fires at close=1035, where the flat 8% trail (stop=1012) does not ----
bt.TRAIL_ATR_ENABLED = True
bt.TRAIL_ATR_KEY_VALUE = 2.0
trade_atr, _ = bt.evaluate_position_exit(_base_position(), bar2, *ARGS, current_atr=30.0)
assert trade_atr is not None and trade_atr["exit_reason"] == "TRAILING", (
    "ATR-derived trail (1040) should fire at close=1035 where the flat 8% trail (1012) would not"
)
assert abs(trade_atr["exit_price"] - 1035.0) < 0.01
print("[PASS] ON: ATR-derived trail (1040) fires at close=1035 where flat trail (1012) would not")

# ---- (3) ON, current_atr=None: falls back to the flat trail, matches the assumption
# check above (no exit at bar2) ----
trade_none, _ = bt.evaluate_position_exit(_base_position(), bar2, *ARGS, current_atr=None)
assert trade_none is None, "missing current_atr must fall back to the flat trail (which does not fire on bar2)"
print("[PASS] ON, current_atr=None: falls back to flat trail, no crash")

# ---- (4) ON, current_atr=0.0 / NaN: same fallback, never crashes ----
trade_zero, _ = bt.evaluate_position_exit(_base_position(), bar2, *ARGS, current_atr=0.0)
assert trade_zero is None
trade_nan, _ = bt.evaluate_position_exit(_base_position(), bar2, *ARGS, current_atr=float("nan"))
assert trade_nan is None
print("[PASS] ON, current_atr=0.0/NaN: falls back to flat trail, no crash")

bt.TRAIL_ATR_ENABLED = False  # restore default
print("\nAll 4 checks pass.")
