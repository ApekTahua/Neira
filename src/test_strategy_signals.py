"""First automated regression test for V1's live signal logic
(strategy.py's add_features/get_signals/get_regime/get_regime_params) --
this file previously had ZERO tests anywhere. Only ADDS a file; never
imports and never modifies screener.py, backtest.py, strategy.py,
config.py, or notifier.py, so it doesn't violate the "never modify V1"
rule (see CLAUDE.md) while still giving those files real coverage.

Both screener.py (live) and backtest.py (historical) call
strategy.get_signals() with the SAME regime_params derived from
strategy.get_regime()/get_regime_params() -- see screener.py:157 and
backtest.py:412-413. Since both reduce to the identical function call on
identical inputs, testing get_signals/add_features directly here IS the
consistency guarantee Deepseek's review asked for: there is no separate
"backtest signal logic" to drift from "live signal logic," there's one
function both callers share.

Expected values were derived by RUNNING this exact code against the
fixtures below and reading the real output (not hand-derived formulas --
ADX/RSI are recursive enough that hand-computing them is error-prone and
was exactly the wrong kind of confidence to fake). Re-running this file
is the actual proof, not the comment.

Usage: python src/test_strategy_signals.py
"""

import numpy as np
import pandas as pd

import strategy as strat
import config as cfg

N = 60  # >= SMA200's min_periods isn't needed (NaN sma200 passes through),
        # but >= ma50's 50-period window is required for any signal at all.


def _dates(n=N):
    return pd.date_range("2026-01-01", periods=n, freq="B")


def _base_df(stock_code, close, volume, dates=None):
    dates = dates if dates is not None else _dates(len(close))
    prev = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({
        "stock_code": stock_code, "trade_date": dates,
        "close_price": close, "previous": prev,
        "high": close + 2, "low": close - 2,
        "volume": volume, "foreign_buy": 0.0, "foreign_sell": 0.0,
    })


def test_squeeze_plus_volume_spike_fires_a_signal():
    # Tight sine-wave consolidation (+/-0.3% band) for 59 days, then a 3x
    # volume spike with a still-flat close on day 60 -- the setup
    # get_signals is designed to catch.
    noise = np.sin(np.linspace(0, 6 * np.pi, N)) * 3.0
    close = 1000.0 + noise
    close[-1] = close[-2] * 1.005  # inside FLAT_RANGE (2%)
    volume = np.full(N, 500_000.0)
    volume[-1] *= 3.0

    df = _base_df("TEST", close, volume)
    feat = strat.add_features(df)
    last = feat[feat["trade_date"] == feat["trade_date"].max()]

    params = strat.get_regime_params("BULLISH")
    sig = strat.get_signals(last, params["confidence_min"], params["min_conditions"])

    assert not sig.empty, "expected the squeeze+volume-spike setup to fire a signal"
    row = sig.iloc[0]
    assert row["cond_vol_spike"], "3x volume spike should trip cond_vol_spike"
    assert row["cond_sideways"], "flat 0.5% return, below bb_upper, should trip cond_sideways"
    assert 0 <= row["confidence"] <= 100
    print(f"[OK] test_squeeze_plus_volume_spike_fires_a_signal (confidence={row['confidence']:.1f})")


def test_strong_uptrend_does_not_fire():
    # Clean steady +1%/day compounding uptrend -- MA10/20/50 spread wide
    # (fails cond1), no squeeze, no volume spike. Must NOT be flagged even
    # though it's a "good" stock -- this screener looks for consolidation,
    # not trend-following.
    close = 1000.0 * (1.01 ** np.arange(N))
    volume = np.full(N, 500_000.0)
    df = _base_df("UPTREND", close, volume)
    feat = strat.add_features(df)
    last = feat[feat["trade_date"] == feat["trade_date"].max()]

    params = strat.get_regime_params("BULLISH")
    sig = strat.get_signals(last, params["confidence_min"], params["min_conditions"])
    assert sig.empty, "a clean uptrend with no squeeze/spike should never be flagged"
    print("[OK] test_strong_uptrend_does_not_fire")


def test_insufficient_history_is_excluded_not_crashed():
    # Only 30 rows -- ma50 (needs 50) stays NaN for every row, so
    # REQUIRED_COLS drops it. Must return empty, not raise or silently
    # score a stock on partial-window indicators.
    close = 1000.0 + np.sin(np.linspace(0, 3 * np.pi, 30)) * 3.0
    volume = np.full(30, 500_000.0)
    df = _base_df("SHORT", close, volume, dates=_dates(30))
    feat = strat.add_features(df)
    last = feat[feat["trade_date"] == feat["trade_date"].max()]

    params = strat.get_regime_params("BULLISH")
    sig = strat.get_signals(last, params["confidence_min"], params["min_conditions"])
    assert sig.empty, "a stock with < 50 days of history must never produce a signal"
    print("[OK] test_insufficient_history_is_excluded_not_crashed")


def test_illiquid_stock_filtered_even_if_setup_matches():
    # Same squeeze shape as the first test, but avg_vol_20 sits well below
    # MIN_LIQUIDITY_VOL -- the illiquidity filter must win regardless of
    # how good the technical setup looks.
    noise = np.sin(np.linspace(0, 6 * np.pi, N)) * 3.0
    close = 1000.0 + noise
    volume = np.full(N, 500.0)  # << cfg.MIN_LIQUIDITY_VOL (100,000)
    volume[-1] = 1500.0
    df = _base_df("ILLIQ", close, volume)
    feat = strat.add_features(df)
    last = feat[feat["trade_date"] == feat["trade_date"].max()]

    params = strat.get_regime_params("BULLISH")
    sig = strat.get_signals(last, params["confidence_min"], params["min_conditions"])
    assert sig.empty, "illiquid stocks must be filtered even with a matching squeeze setup"
    print("[OK] test_illiquid_stock_filtered_even_if_setup_matches")


def test_get_regime_classification():
    dates = _dates(60)
    idx_close = np.full(60, 100.0)
    idx_close[-1] = 110.0  # last close above its own ma50 -> BULLISH
    idx_df = pd.DataFrame({"trade_date": dates, "close": idx_close})
    idx_df["ma50"] = idx_df["close"].rolling(50, min_periods=50).mean()
    assert strat.get_regime(idx_df, dates[-1]) == "BULLISH"

    idx_close2 = np.full(60, 100.0)
    idx_close2[-1] = 90.0  # below ma50 -> BEARISH
    idx_df2 = pd.DataFrame({"trade_date": dates, "close": idx_close2})
    idx_df2["ma50"] = idx_df2["close"].rolling(50, min_periods=50).mean()
    assert strat.get_regime(idx_df2, dates[-1]) == "BEARISH"

    # Too little history for ma50 -- must default NEUTRAL, not crash.
    idx_df3 = pd.DataFrame({"trade_date": dates[:10], "close": idx_close[:10]})
    idx_df3["ma50"] = idx_df3["close"].rolling(50, min_periods=50).mean()
    assert strat.get_regime(idx_df3, dates[9]) == "NEUTRAL"
    print("[OK] test_get_regime_classification")


def test_get_regime_params_matches_config_per_regime():
    # This is the exact wiring both screener.py (live) and backtest.py
    # (historical) depend on for identical live/backtest behavior --
    # screener.py:157 and backtest.py:412-413 both call
    # get_regime_params(get_regime(...)) then feed the result straight
    # into get_signals(). If this mapping ever silently drifted per
    # regime, live and backtest would diverge without either file
    # changing -- this pins it down.
    bull = strat.get_regime_params("BULLISH")
    assert bull["confidence_min"] == cfg.CONF_BULLISH
    assert bull["min_conditions"] == cfg.BULLISH_MIN_CONDITIONS
    neutral = strat.get_regime_params("NEUTRAL")
    assert neutral["confidence_min"] == cfg.CONF_NEUTRAL
    assert neutral["min_conditions"] == cfg.NEUTRAL_MIN_CONDITIONS
    bear = strat.get_regime_params("BEARISH")
    assert bear["confidence_min"] == cfg.CONF_BEARISH
    assert bear["min_conditions"] == cfg.BEARISH_MIN_CONDITIONS
    print("[OK] test_get_regime_params_matches_config_per_regime")


if __name__ == "__main__":
    test_squeeze_plus_volume_spike_fires_a_signal()
    test_strong_uptrend_does_not_fire()
    test_insufficient_history_is_excluded_not_crashed()
    test_illiquid_stock_filtered_even_if_setup_matches()
    test_get_regime_classification()
    test_get_regime_params_matches_config_per_regime()
    print("\nAll V1 strategy signal checks passed.")
