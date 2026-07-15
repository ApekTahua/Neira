from datetime import date

import data_fetch


class _FakeQuery:
    """Chainable stand-in for supabase.table(...).select(...).eq(...)... .execute()."""

    def __init__(self, rows_by_call, call_counter, key):
        self._rows_by_call = rows_by_call
        self._call_counter = call_counter
        self._key = key

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def range(self, offset, limit):
        return self

    def execute(self):
        i = self._call_counter[self._key]
        self._call_counter[self._key] += 1
        rows = self._rows_by_call[self._key][i] if i < len(self._rows_by_call[self._key]) else []
        return type("Result", (), {"data": rows})()


class _FakeTable:
    def __init__(self, name, rows_by_call, call_counter):
        self._name = name
        self._rows_by_call = rows_by_call
        self._call_counter = call_counter

    def select(self, *a, **k):
        return _FakeQuery(self._rows_by_call, self._call_counter, self._name)


class _FakeSupabase:
    def __init__(self, rows_by_call):
        self._rows_by_call = rows_by_call
        self._call_counter = {k: 0 for k in rows_by_call}

    def table(self, name):
        return _FakeTable(name, self._rows_by_call, self._call_counter)


def test_fetch_data_paginates_until_empty_batch():
    idx_rows = [{"trade_date": "2024-01-01", "close": "7000"}]
    codes_rows = [{"stock_code": "BBCA"}]
    stock_rows = [{
        "stock_code": "BBCA", "trade_date": "2024-01-01", "open_price": "9000",
        "close_price": "9100", "high": "9150", "low": "8950", "previous": "9050",
        "volume": "1000000", "foreign_buy": "100", "foreign_sell": "50",
    }]
    rows_by_call = {
        "index_eod": [idx_rows, []],   # first page has data, second page empty -> stop
        "ihsg_eod": [codes_rows, stock_rows, []],
    }
    supabase = _FakeSupabase(rows_by_call)

    df, idx_df = data_fetch.fetch_data(supabase, date(2024, 1, 1), date(2024, 1, 1), lookback_days=0)

    assert len(idx_df) == 1
    assert idx_df.iloc[0]["close"] == 7000.0
    assert len(df) == 1
    assert df.iloc[0]["stock_code"] == "BBCA"
    assert df.iloc[0]["close_price"] == 9100.0


def test_fetch_data_raises_when_no_stock_data():
    rows_by_call = {
        "index_eod": [[{"trade_date": "2024-01-01", "close": "7000"}], []],
        "ihsg_eod": [[{"stock_code": "BBCA"}], [], []],  # codes found but no OHLCV rows
    }
    supabase = _FakeSupabase(rows_by_call)
    import pytest
    with pytest.raises(RuntimeError):
        data_fetch.fetch_data(supabase, date(2024, 1, 1), date(2024, 1, 1), lookback_days=0)
