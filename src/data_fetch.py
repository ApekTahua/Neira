"""
data_fetch.py — Shared Supabase data-fetch helper for V2 scripts
(train_hmm.py, backtest_v2.py, screener_v2.py).

Deliberately NOT imported by V1's backtest.py/screener.py — those keep
their own inline fetch logic untouched (see plan Global Constraints).
"""

import time
from datetime import date, timedelta

import pandas as pd


def _retry(fn, attempts=4, base_delay=2.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (i + 1))


def fetch_data(supabase, start_date: date, end_date: date, lookback_days: int = 280):
    """Fetches IHSG index + per-stock OHLCV data for
    [start_date - lookback_days, end_date]. Returns (df, idx_df)."""
    fetch_start = start_date - timedelta(days=lookback_days)

    all_idx = []
    offset = 0
    while True:
        batch = _retry(lambda: (
            supabase.table("index_eod")
            .select("trade_date,close")
            .eq("index_code", "COMPOSITE")
            .gte("trade_date", fetch_start.isoformat())
            .lte("trade_date", end_date.isoformat())
            .order("trade_date")
            .range(offset, offset + 999)
            .execute()
        ))
        if not batch.data:
            break
        all_idx.extend(batch.data)
        offset += 1000

    idx_df = pd.DataFrame(all_idx) if all_idx else pd.DataFrame()
    if not idx_df.empty:
        idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"]).dt.date
        idx_df["close"] = pd.to_numeric(idx_df["close"], errors="coerce")
        idx_df = idx_df.sort_values("trade_date").reset_index(drop=True)
        idx_df["ma50"] = idx_df["close"].rolling(50, min_periods=50).mean()

    idx_in_range = idx_df[
        (idx_df["trade_date"] >= start_date) & (idx_df["trade_date"] <= end_date)
    ] if not idx_df.empty else idx_df
    code_date = (
        idx_in_range["trade_date"].max().isoformat()
        if not idx_in_range.empty else end_date.isoformat()
    )

    codes_batch = _retry(lambda: (
        supabase.table("ihsg_eod")
        .select("stock_code")
        .eq("trade_date", code_date)
        .limit(2000)
        .execute()
    ))
    unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))
    if not unique_codes:
        codes_batch = _retry(lambda: (
            supabase.table("ihsg_eod")
            .select("stock_code")
            .eq("trade_date", start_date.isoformat())
            .limit(2000)
            .execute()
        ))
        unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))

    all_stocks = []
    batch_size = 50
    for i in range(0, len(unique_codes), batch_size):
        batch_codes = unique_codes[i:i + batch_size]
        offset = 0
        while True:
            batch = _retry(lambda: (
                supabase.table("ihsg_eod")
                .select("stock_code,trade_date,open_price,close_price,high,low,previous,volume,foreign_buy,foreign_sell")
                .in_("stock_code", batch_codes)
                .gte("trade_date", fetch_start.isoformat())
                .lte("trade_date", end_date.isoformat())
                .order("trade_date")
                .range(offset, offset + 999)
                .execute()
            ))
            if not batch.data:
                break
            all_stocks.extend(batch.data)
            offset += 1000

    if not all_stocks:
        raise RuntimeError("No stock data retrieved from ihsg_eod")

    df = pd.DataFrame(all_stocks)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    for col in ["open_price", "close_price", "high", "low", "volume", "previous", "foreign_buy", "foreign_sell"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df, idx_df
