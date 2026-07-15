import pandas as pd
import pytest

from strategy import add_features, get_signals


def _synthetic_stock_df(n=60):
    dates = pd.date_range("2024-01-01", periods=n, freq="B").date
    close = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "stock_code": ["TEST"] * n,
        "trade_date": dates,
        "close_price": close,
        "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close],
        "previous": [close[0]] + close[:-1],
        "volume": [1_000_000] * n,
        "foreign_buy": [0] * n,
        "foreign_sell": [0] * n,
    })


def test_add_features_includes_adtv_20():
    df = add_features(_synthetic_stock_df())
    assert "adtv_20" in df.columns
    # adtv_20 at row 19 (20th row, 0-indexed) = mean(close[0:20] * 1_000_000)
    expected = (df["close_price"].iloc[:20] * 1_000_000).mean()
    assert df["adtv_20"].iloc[19] == pytest.approx(expected)


def test_add_features_includes_hmm_columns():
    df = add_features(_synthetic_stock_df())
    for col in ["hmm_return", "hmm_range", "hmm_log_vol_change"]:
        assert col in df.columns


def _synthetic_signal_day(n=5, with_adtv=True, with_hmm=False, hmm_states=None):
    """A day_data frame with enough columns for get_signals() to run past
    the REQUIRED_COLS dropna and red-flag filters."""
    df = pd.DataFrame({
        "stock_code": [f"STK{i}" for i in range(n)],
        "trade_date": [pd.Timestamp("2024-06-01").date()] * n,
        "close_price": [1000.0] * n,
        "previous": [1000.0] * n,
        "high": [1010.0] * n,
        "low": [990.0] * n,
        "volume": [500_000] * n,
        "foreign_buy": [0] * n,
        "foreign_sell": [0] * n,
        "ma10": [1000.0] * n,
        "ma20": [1000.0] * n,
        "ma50": [1000.0] * n,
        "std20": [5.0] * n,
        "bb_bandwidth": [2.0] * n,          # tight -> cond2 True
        "avg_vol_20": [400_000] * n,
        "avg_vol_20_prev": [200_000] * n,   # vol_ratio = 500k/200k = 2.5 -> cond3 True
        "daily_return": [0.0] * n,
        "rolling_min_close": [900.0] * n,
        "rolling_max_close": [1100.0] * n,
        "bb_upper": [1050.0] * n,
        "rsi": [55.0] * n,
        "adx": [25.0] * n,
        "sma200": [900.0] * n,
        "foreign_net_ma": [0.1] * n,
        "atr_14": [10.0] * n,
        "atr_sl": [980.0] * n,
        "ut_position": [1] * n,
        "swing_low": [950.0] * n,
        "last_swing_low": [950.0] * n,
        "buy_zone_low": [940.0] * n,
        "buy_zone_high": [960.0] * n,
        "last_swing_high": [1050.0] * n,
        "tp_target": [1050.0] * n,
    })
    if with_adtv:
        df["adtv_20"] = 2_000_000_000.0  # well above ADTV_MIN
    if with_hmm:
        df["hmm_state"] = hmm_states if hmm_states is not None else ["BULLISH"] * n
    return df


def test_get_signals_v1_call_signature_unaffected_by_missing_v2_columns():
    """V1 callers never compute adtv_20/hmm_state and never pass the new
    kwargs — get_signals() must not require those columns to exist."""
    day = _synthetic_signal_day(with_adtv=False, with_hmm=False)
    assert "adtv_20" not in day.columns
    assert "hmm_state" not in day.columns
    result = get_signals(day, confidence_min=0, min_conditions=2)
    assert isinstance(result, pd.DataFrame)  # ran without KeyError


def test_get_signals_adtv_gate_excludes_illiquid():
    day = _synthetic_signal_day(with_adtv=True)
    day["adtv_20"] = 500_000_000.0  # below ADTV_MIN (1B)
    result = get_signals(day, confidence_min=0, min_conditions=2, adtv_min=1_000_000_000)
    assert result.empty


def test_get_signals_adtv_gate_keeps_liquid():
    day = _synthetic_signal_day(with_adtv=True)  # 2B, above ADTV_MIN
    result = get_signals(day, confidence_min=0, min_conditions=2, adtv_min=1_000_000_000)
    assert not result.empty


def test_get_signals_hmm_gate_excludes_bearish():
    day = _synthetic_signal_day(with_adtv=True, with_hmm=True, hmm_states=["BEARISH"] * 5)
    result = get_signals(day, confidence_min=0, min_conditions=2, hmm_gate=True)
    assert result.empty


def test_get_signals_hmm_gate_keeps_sideways_and_bullish():
    day = _synthetic_signal_day(with_adtv=True, with_hmm=True, hmm_states=["SIDEWAYS", "BULLISH", "BEARISH", "NO_MODEL", "SIDEWAYS"])
    result = get_signals(day, confidence_min=0, min_conditions=2, hmm_gate=True)
    assert set(result["stock_code"]).issubset({"STK0", "STK1", "STK4"})
    assert "STK2" not in set(result["stock_code"])  # BEARISH
    assert "STK3" not in set(result["stock_code"])  # NO_MODEL
