"""Self-check for the index_eod-missing guard added to paper_signal_scan.py
(F-023, 2026-10-01): a 13-trading-day n8n outage left index_eod with zero
rows for 2026-09-14..09-30 while ihsg_eod (per-stock) kept loading normally.
regime_by_date.get(today, "NEUTRAL") can't tell "the index genuinely read
neutral" apart from "there is no index row for today at all" -- both
defaulted identically, so daily_gate_summary/daily_scoreboard quietly wrote
a fabricated NEUTRAL regime for 13 sessions with nothing loud enough to
notice. index_missing_today = idx_df.empty or not (idx_df["trade_date"] ==
today).any() is the exact expression paper_signal_scan.py now evaluates
right after build_full_dataset() -- this file locks in its behavior against
synthetic idx_df shapes without needing a live DB (same no-DB-dependency
style as test_split_guard.py).

Run: python src/test_index_missing_guard.py
"""
from datetime import date

import pandas as pd


def _index_missing_today(idx_df: pd.DataFrame, today: date) -> bool:
    """Exact expression from paper_signal_scan.py's main(), copied verbatim
    (that script is a monolithic main(), not a callable) so this test
    exercises the real logic, not a reimplementation that could drift."""
    return idx_df.empty or not (idx_df["trade_date"] == today).any()


def test_empty_dataframe_is_missing():
    idx_df = pd.DataFrame(columns=["trade_date", "close"])
    assert _index_missing_today(idx_df, date(2026, 9, 15)) is True
    print("[OK] a fully empty idx_df (no index_eod rows at all) is detected as missing")


def test_gap_day_is_missing_even_with_history_either_side():
    # Exactly F-023's real shape: rows exist before and after the outage,
    # but the specific trading day in question has none -- not an empty
    # table, a hole in the middle of one.
    idx_df = pd.DataFrame({
        "trade_date": [date(2026, 9, 11), date(2026, 10, 1)],
        "close": [6541.4, 6090.0],
    })
    assert _index_missing_today(idx_df, date(2026, 9, 15)) is True
    print("[OK] a gap day surrounded by real history on both sides is still detected as missing")


def test_real_row_for_today_is_not_missing():
    idx_df = pd.DataFrame({
        "trade_date": [date(2026, 9, 14), date(2026, 9, 15)],
        "close": [6534.7, 6461.2],
    })
    assert _index_missing_today(idx_df, date(2026, 9, 15)) is False
    print("[OK] a real row for today is NOT flagged as missing (no false positive)")


def test_multi_index_code_rows_for_today_count_as_present():
    # build_full_dataset only ever fetches index_code='COMPOSITE' into idx_df
    # (data_fetch.fetch_data), so in practice this is one row per day -- but
    # the guard must not accidentally depend on exactly-one-row-per-day
    # being true, since nothing enforces that at the type level here.
    idx_df = pd.DataFrame({
        "trade_date": [date(2026, 9, 15), date(2026, 9, 15)],
        "close": [6461.2, 6461.2],
    })
    assert _index_missing_today(idx_df, date(2026, 9, 15)) is False
    print("[OK] duplicate/multiple rows for today still correctly read as present")


if __name__ == "__main__":
    test_empty_dataframe_is_missing()
    test_gap_day_is_missing_even_with_history_either_side()
    test_real_row_for_today_is_not_missing()
    test_multi_index_code_rows_for_today_count_as_present()
    print("\n[DONE] index-missing guard self-check passed")
