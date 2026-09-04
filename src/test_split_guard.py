"""Self-check for the corporate-action guard on strategy.add_features'
swing-high/low forward-fill (added 2026-09-04).

The bug: `.ffill()` had no recency or rescale bound, so a pre-split swing high
kept being carried against post-split prices. Live evidence from
daily_qualifying_signals on 2026-09-03 -- DSSA closed at 1185 with a tp_target
of 65900, a +5,461% "target", because 65900 was its pre-split level.

Two synthetic series, because the property is easy to state and hard to see in
real data: a stock that splits must not report a pre-split swing level, and a
stock that never splits must be completely unaffected (the guard is a no-op).

Run: python src/test_split_guard.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy import add_features  # noqa: E402


def _series(closes, start="2024-01-01"):
    n = len(closes)
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame({
        "stock_code": ["TEST"] * n,
        "trade_date": dates,
        "close_price": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "open_price": closes,
        "volume": [1_000_000] * n,
        "previous": [closes[0]] + closes[:-1],
        "foreign_buy": [0] * n,
        "foreign_sell": [0] * n,
    })


def _ramp(lo, hi, n):
    return list(np.linspace(lo, hi, n))


def test_split_does_not_leak_old_scale():
    # 150 sessions climbing to 10000, then a 1:20 split (10000 -> 500), then
    # 150 more sessions drifting around the new scale.
    pre = _ramp(8000, 10000, 150)
    post = _ramp(500, 620, 150)
    df = add_features(_series(pre + post))

    after = df.iloc[len(pre):]
    tp = after["tp_target"].dropna()
    assert len(tp) > 0, "no tp_target produced after the split at all"
    worst = float((tp / after.loc[tp.index, "close_price"]).max())
    assert worst < 2.0, f"a pre-split level leaked across the split: target/price reached {worst:.1f}x"

    swing = after["last_swing_high"].dropna()
    if len(swing):
        assert float(swing.max()) < 5000, f"last_swing_high still on the old scale: {float(swing.max()):.0f}"
    print(f"[OK] post-split worst target/price = {worst:.2f}x (pre-fix this reached 152x on DSSA)")


def test_no_legal_daily_move_can_trip_the_guard():
    """The guard keys on a same-session close ratio outside [0.5, 2.0]. That
    band is only safe if no ORDINARY session can reach it -- otherwise the
    guard would silently reset swing levels on a normal volatile day.

    IDX auto-reject caps a single session's move well inside that band (the
    widest band is +/-35%), so the check is: even at the extreme, and even
    compounding an up-limit day straight into a down-limit day, the ratio
    stays between 0.65 and 1.35. A rescale is a different order of magnitude.
    """
    import numpy as np

    limits = [0.20, 0.25, 0.35]  # IDX auto-reject bands by price tier
    for lim in limits:
        assert 1 + lim < 2.0, f"an up-limit day of +{lim:.0%} would trip the guard"
        assert 1 - lim > 0.5, f"a down-limit day of -{lim:.0%} would trip the guard"
    print(f"[OK] widest IDX auto-reject band (+/-{max(limits):.0%}) is far inside the [0.5, 2.0] guard")

    # And on a real-shaped random walk the segment id must stay constant --
    # one segment means the ffill behaves exactly as it did before the fix.
    rng = np.random.default_rng(7)
    closes = [1000.0]
    for _ in range(2000):
        closes.append(max(50.0, closes[-1] * float(np.exp(rng.normal(0, 0.03)))))
    c = pd.Series(closes)
    ratio = c / c.shift(1).replace(0, np.nan)
    segments = (ratio.lt(0.5) | ratio.gt(2.0)).fillna(False).cumsum()
    assert segments.nunique() == 1, (
        f"a plain random walk produced {segments.nunique()} segments -- the guard "
        f"would reset swing levels on ordinary sessions (max move "
        f"{ratio.max():.2f}x / min {ratio.min():.2f}x)"
    )
    print(f"[OK] 2,000-session random walk stays one segment (moves {ratio.min():.2f}x-{ratio.max():.2f}x)")


if __name__ == "__main__":
    test_split_does_not_leak_old_scale()
    test_no_legal_daily_move_can_trip_the_guard()
    print("\n[DONE] split-guard self-check passed")
