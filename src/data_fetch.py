"""
data_fetch.py — Shared Supabase data-fetch helper for V2 scripts
(train_hmm.py, backtest_v2.py, screener_v2.py).

Deliberately NOT imported by V1's backtest.py/screener.py — those keep
their own inline fetch logic untouched (see plan Global Constraints).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from db_retry import retry as _retry

# I/O-bound (network round trips to Supabase), not CPU-bound -- a thread
# pool gets near-linear speedup here despite the GIL. 12 is a middling
# concurrency: enough to turn ~20 minutes of serial requests into ~1-2,
# not so many that it looks like a burst attack against PostgREST.
FETCH_CONCURRENCY = 12

# _retry() itself now lives in db_retry.py (shared with the live paper-
# trading path) -- imported here under its old name so every existing
# `_retry(...)` call site below is untouched. See db_retry.py's docstring.


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

    # Stock universe: union codes seen at multiple checkpoints spread across
    # the whole fetch range (one per month), not just the last day. A
    # single end-date snapshot silently drops any stock that delisted
    # before end_date -- its entire pre-delisting history (including any
    # losses right before delisting) would be invisible to every backtest,
    # a real survivorship-bias bug, not a hypothetical one (confirmed:
    # e.g. FREN/MFIN, liquid stocks that delisted mid-2025 with large
    # prior declines, were completely absent from this universe before
    # this fix). Monthly checkpoints catch any stock that traded for at
    # least part of a calendar month; only a stock that listed AND
    # delisted entirely within one month, on a day between checkpoints,
    # could still be missed.
    if not idx_df.empty:
        all_dates_sorted = sorted(idx_df["trade_date"].unique())
    else:
        all_dates_sorted = []
    checkpoint_dates = {fetch_start.isoformat(), end_date.isoformat()}
    seen_months = set()
    for d in all_dates_sorted:
        if fetch_start <= d <= end_date:
            ym = (d.year, d.month)
            if ym not in seen_months:
                seen_months.add(ym)
                checkpoint_dates.add(d.isoformat())

    def _fetch_codes_at(cd: str):
        return _retry(lambda: (
            supabase.table("ihsg_eod")
            .select("stock_code")
            .eq("trade_date", cd)
            .limit(2000)
            .execute()
        ))

    unique_codes = set()
    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        for codes_batch in pool.map(_fetch_codes_at, sorted(checkpoint_dates)):
            unique_codes.update(row["stock_code"] for row in (codes_batch.data or []))
    unique_codes = sorted(unique_codes)

    # Paginated by bounded calendar-month range, not OFFSET -- a
    # stock_code IN (...) + trade_date-range query with ORDER BY + OFFSET
    # forces Postgres to re-sort the ENTIRE matching row set (spilling to
    # disk past work_mem) on every single page, with cost growing with the
    # offset depth: confirmed via EXPLAIN ANALYZE, a single offset=60000
    # page over a 5-year range took 4+ seconds by itself (external merge
    # sort, ~70k rows re-sorted from scratch just to skip to that page).
    # Multiply across ~20 stock-code chunks x ~30-70 pages each for a
    # multi-year window and total time crosses Postgres's 2min
    # statement_timeout -- this is what made the wider OOS windows
    # (2024-07..2026-06, 2023-07..2024-12) fail outright while the
    # shorter one (2023-01..2023-06) happened to stay under the limit.
    # A month-bounded range query is O(1) per page regardless of how deep
    # into history it is -- one month x 50 stocks is comfortably under
    # 1000 trading-day rows, so no OFFSET/re-sort is needed at all.
    batch_size = 50
    month_starts = []
    cursor = date(fetch_start.year, fetch_start.month, 1)
    while cursor <= end_date:
        month_starts.append(cursor)
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)

    # Every (stock-code-chunk, month) pair is an independent, order-
    # independent request -- df gets sort_values()'d at the end regardless
    # of what order results arrive in, so these are safe to fire concurrently
    # instead of one at a time. This loop was the dominant cost of a daily
    # signal-scan run (~20+ min serial for ~900 stocks x ~5.5yrs of months);
    # concurrency turns it into wall-clock ~1-2 min.
    chunk_specs = []
    for i in range(0, len(unique_codes), batch_size):
        batch_codes = unique_codes[i:i + batch_size]
        for m_start in month_starts:
            m_end = date(m_start.year + (m_start.month == 12), m_start.month % 12 + 1, 1) - timedelta(days=1)
            chunk_specs.append((batch_codes, max(m_start, fetch_start), min(m_end, end_date)))

    def _fetch_chunk(spec):
        batch_codes, gte, lte = spec
        return _retry(lambda: (
            supabase.table("ihsg_eod")
            .select("stock_code,trade_date,open_price,close_price,high,low,previous,volume,foreign_buy,foreign_sell")
            .in_("stock_code", batch_codes)
            .gte("trade_date", gte.isoformat())
            .lte("trade_date", lte.isoformat())
            .order("trade_date")
            .limit(5000)
            .execute()
        ))

    all_stocks = []
    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        for batch in pool.map(_fetch_chunk, chunk_specs):
            if batch.data:
                all_stocks.extend(batch.data)

    if not all_stocks:
        raise RuntimeError("No stock data retrieved from ihsg_eod")

    df = pd.DataFrame(all_stocks)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    for col in ["open_price", "close_price", "high", "low", "volume", "previous", "foreign_buy", "foreign_sell"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df, idx_df
