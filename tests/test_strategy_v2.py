import pandas as pd
import pytest

from strategy import add_features


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
