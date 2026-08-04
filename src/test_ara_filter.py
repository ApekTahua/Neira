"""Self-check for the V3.1 ARA (auto-reject atas) entry filter.

Anchored on the real bar that motivated it: BAJA 2026-08-03 (prev 244 ->
close 304 = +24.59%, close == high == 304), which the live engine queued
and which then went suspended (open=0, volume=0) and could never fill.

Run:  python src/test_ara_filter.py
"""

import os

os.environ.setdefault("V3_ARA_FILTER", "1")

import backtest_v3 as bt  # noqa: E402


def test_ara_limit_tiers():
    assert bt.ara_limit_pct(150) == 0.35   # < Rp200
    assert bt.ara_limit_pct(244) == 0.25   # Rp200-5000 (BAJA's band)
    assert bt.ara_limit_pct(5000) == 0.25  # boundary stays in the 25% band
    assert bt.ara_limit_pct(12050) == 0.20  # > Rp5000


def test_baja_real_bar_is_flagged():
    # The actual 2026-08-03 bar, from ihsg_eod.
    assert bt.is_ara_locked(prev_close=244, close=304, high=304)


def test_dooh_real_bar_is_not_flagged():
    # DOOH 2026-08-03: +5.65% and closed 262 well below its 278 high.
    # Volatile, but genuinely two-sided -- the ATR ceiling is what should
    # catch this one, not the ARA filter. Guards against the filter
    # quietly widening into "reject anything that went up".
    assert not bt.is_ara_locked(prev_close=248, close=262, high=278)


def test_big_gain_that_closed_off_the_high_is_not_flagged():
    # +24% but closed below the high => there was a real offer to buy from.
    assert not bt.is_ara_locked(prev_close=244, close=302, high=304)


def test_close_at_high_but_small_gain_is_not_flagged():
    # SMLE 2026-07-30: closed at its high on +2.6%. Closing at the high is
    # ordinary; only the high AND the tier-limit gain together mean locked.
    assert not bt.is_ara_locked(prev_close=154, close=158, high=158)


def test_tolerance_catches_tick_rounded_lock():
    # BAJA locked at 24.59%, not a clean 25% -- tick rounding. A strict
    # >= limit test would have missed the exact bar this filter exists for.
    assert bt.ARA_LIMIT_TOLERANCE < 1.0
    assert (304 / 244 - 1) < 0.25
    assert bt.is_ara_locked(prev_close=244, close=304, high=304)


def test_missing_data_is_not_flagged():
    assert not bt.is_ara_locked(prev_close=None, close=304, high=304)
    assert not bt.is_ara_locked(prev_close=0, close=304, high=304)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("\nAll ARA-filter checks passed.")
