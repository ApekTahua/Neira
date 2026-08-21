"""Self-check for the V3.1 auto-reject (ARA/ARB) detection.

Anchored on real bars from ihsg_eod, and on the limit distribution measured
over 2025-01-01+ (bars closing AT their high cluster just under 10 / 20 /
25 / 35% and collapse immediately above each -- see backtest_v4's comment
block for the counts).

The board problem this guards against: IDX sets the limit by BOARD, and
ihsg_eod has no board column, so a Rp1,000 stock may be a 25% name (main
board) or a 10% name (akselerasi / monitoring). The limit is therefore
inferred from each stock's own trailing max move, and only falls back to the
price tier when that reveals nothing.

Run:  python src/test_ara_filter.py
"""

import os

os.environ.setdefault("V4_ARA_FILTER", "1")
os.environ.setdefault("V4_ARB_EXIT_REALISM", "1")

import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402


# ---- limit inference ------------------------------------------------------

def test_price_tier_fallback_bands():
    assert bt.price_tier_limit(150) == 0.35    # < Rp200
    assert bt.price_tier_limit(244) == 0.25    # Rp200-5000 (BAJA's band)
    assert bt.price_tier_limit(5000) == 0.25   # boundary stays in the 25% band
    assert bt.price_tier_limit(12050) == 0.20  # > Rp5000


def test_history_reveals_a_ten_percent_board():
    # A Rp1,000 stock whose largest move in a year is ~10% is an
    # akselerasi/monitoring name, NOT a 25% main-board name. Price alone
    # would get this wrong -- this is the exact case the user flagged.
    assert bt.snap_to_known_limit(0.0999, 1000) == 0.10
    assert bt.price_tier_limit(1000) == 0.25  # what price alone would claim


def test_history_reveals_a_twenty_five_percent_board():
    assert bt.snap_to_known_limit(0.2478, 1000) == 0.25


def test_no_snap_falls_back_to_price_tier():
    # A calm blue chip topping out at 6% matches no known limit. Falling
    # back to the tier is right: it also means a 6% day can't read as locked.
    assert bt.snap_to_known_limit(0.06, 1000) == 0.25
    assert bt.snap_to_known_limit(None, 1000) == 0.25
    assert bt.snap_to_known_limit(float("nan"), 150) == 0.35


# ---- ARA (ceiling) --------------------------------------------------------

def test_baja_real_bar_is_flagged():
    # BAJA 2026-08-03: prev 244 -> close 304 == high. +24.59% against the
    # 25% limit. Went volume=0/open=0 the next session and never filled.
    assert bt.is_ara_locked(prev_close=244, close=304, high=304, observed_max_move=0.2459)


def test_dooh_real_bar_is_not_flagged():
    # DOOH 2026-08-03: +5.65%, closed 262 well under its 278 high. Volatile
    # but genuinely two-sided -- the ATR ceiling is what should catch this,
    # not the ARA rule. Guards against the filter widening into "reject
    # anything that went up".
    assert not bt.is_ara_locked(prev_close=248, close=262, high=278, observed_max_move=0.25)


def test_big_gain_that_closed_off_the_high_is_not_flagged():
    assert not bt.is_ara_locked(prev_close=244, close=302, high=304, observed_max_move=0.25)


def test_close_at_high_but_small_gain_is_not_flagged():
    # SMLE 2026-07-30 closed at its high on +2.6%. Closing at the high is
    # ordinary; only high AND a limit-sized move together mean locked.
    assert not bt.is_ara_locked(prev_close=154, close=158, high=158, observed_max_move=0.25)


def test_ten_percent_board_lock_is_caught():
    # +9.7% closing at the high on a 10%-limit name IS locked...
    assert bt.is_ara_locked(prev_close=1000, close=1097, high=1097, observed_max_move=0.10)


def test_same_move_on_a_25pct_board_is_not_a_lock():
    # ...while the identical bar on a 25%-limit name is just a strong day.
    # Price is the same; only the inferred board differs. This pair is the
    # whole reason the limit is inferred rather than tabulated.
    assert not bt.is_ara_locked(prev_close=1000, close=1097, high=1097, observed_max_move=0.25)


def test_tolerance_catches_tick_rounded_lock():
    # BAJA locked at 24.59%, not a clean 25% -- tick rounding. A strict
    # >= limit test would miss the exact bar this filter exists for.
    assert bt.LIMIT_TOLERANCE < 1.0
    assert (304 / 244 - 1) < 0.25
    assert bt.is_ara_locked(prev_close=244, close=304, high=304, observed_max_move=0.2459)


# ---- ARB (floor) ----------------------------------------------------------

def test_arb_lock_is_flagged():
    # -24.6% closing AT the low: no bid, a stop cannot be assumed to fill.
    assert bt.is_arb_locked(prev_close=1000, close=754, low=754, observed_max_move=0.25)


def test_arb_not_flagged_when_close_is_off_the_low():
    # Bounced off the low => there were bids. A stop fills normally.
    assert not bt.is_arb_locked(prev_close=1000, close=760, low=754, observed_max_move=0.25)


def test_arb_not_flagged_on_ordinary_down_day():
    assert not bt.is_arb_locked(prev_close=1000, close=970, low=970, observed_max_move=0.25)


def test_arb_locked_bar_blocks_the_exit():
    # A position whose stop is breached on an ARB-locked bar must NOT book
    # an exit -- that is the flattering lie this exists to remove.
    pos = {
        "stock_code": "TEST", "entry_date": None, "avg_price": 1000.0,
        "tp1_price": 1100.0, "sl_price": 900.0, "total_lots": 100,
        "remaining_lots": 100, "cost_basis": 10_000_000.0, "hold_days": 5,
        "tp1_hit": False, "tp2_hit": False, "highest_price": 1000.0,
        "trigger": "t", "checkpoint_day": None, "target_price": None,
        "entry_price_original": 1000.0, "atr_at_entry": 30.0,
    }
    bar = (754.0, 754.0, 1000.0, 754.0)  # gapped to the floor and stayed
    trade, cash_delta = bt.evaluate_position_exit(
        pos, bar, "BULLISH", 0.02, None, 100_000_000.0, 50_000_000.0,
        prev_close=1000.0, observed_max_move=0.25,
    )
    assert trade is None, "ARB-locked bar must not produce a fill"
    assert cash_delta == 0.0
    assert pos["remaining_lots"] == 100, "position must still be held"


# ---- board-limit attachment (no lookahead) --------------------------------

def test_attach_board_limit_excludes_the_current_bar():
    # observed_max_move on row i must be computed from rows < i only. If the
    # current bar leaked in, a stock's first-ever limit-up day would define
    # the limit it is then judged against -- and never be flagged.
    df = pd.DataFrame({
        "stock_code": ["X"] * 70,
        "trade_date": pd.date_range("2025-01-01", periods=70, freq="D"),
        "previous": [1000.0] * 70,
        "close_price": [1010.0] * 69 + [1250.0],  # +1% for 69 days, then +25%
    })
    out = bt.attach_board_limit(df)
    last = out.iloc[-1]
    assert abs(last["observed_max_move"] - 0.01) < 1e-9, (
        f"expected the trailing max to be 1% (today's +25% excluded), got {last['observed_max_move']}"
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("\nAll auto-reject checks passed.")
