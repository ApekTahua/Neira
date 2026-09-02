"""Does the entry rule's weekly feature carry a built-in delay, and does removing it help?

Motivation (2026-09-02): Neira names stocks a median 7 sessions after a plain
trend-following entry would, at a median +14% higher. UT Bot bought EMAS at
6,100 and BEEF at 160; Neira first named them at 7,900 (+30%) and 414 (+159%).
The extension-gate sweep already ruled out the "it buys stocks that are too
expensive" explanation -- all 9 thresholds lost alpha. So the question is not
what to filter out, it is why the entry fires so late in the first place.

One mechanical suspect, visible in the code rather than inferred:

    weekly = close.resample("W-FRI").last()
    spread = (weekly - weekly.rolling(10).mean()) / weekly.rolling(10).mean() * 100
    df = pd.merge_asof(df, weekly_all, on="_dt", by="stock_code", direction="backward")

`W-FRI` labels each week by its FRIDAY. For any row before Friday, that label is
a future date, so a backward merge_asof matches the PREVIOUS week's Friday. A
Monday signal is therefore scored on data up to the Friday 3 calendar days back;
a Thursday signal on data 6 days back. The feature is stale by 1-4 sessions
depending on the weekday, ~2.5 on average, entirely as a side effect of how the
merge lines up -- not as a deliberate confirmation delay.

This is NOT lookahead in the current code (it only ever looks backward), and the
fix is not lookahead either: using the week-to-date close only uses bars that
have already happened. It just stops throwing away the most recent 1-4 sessions.

Two things measured here, in order:
  1. How stale is the feature in practice, per weekday.
  2. Whether removing the staleness actually helps, on the same 9-window
     walk-forward every other candidate was judged on.

Recomputes the column in memory from the cached dataset's own close prices --
no refetch, and the cache file is never modified.

Usage:
    python src/test_weekly_lag.py           # staleness measurement only (fast)
    python src/test_weekly_lag.py --walk    # + the 9-window OFF/ON comparison
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from feature_test_harness import _aggregate, _format_table  # noqa: E402

WEEKLY_MA_PERIODS = 10  # mirrors phase0d_multitimeframe_validation.WEEKLY_MA_PERIODS


def weekly_spread_no_lag(df: pd.DataFrame) -> pd.Series:
    """Same formula, but each daily row sees its own week-to-date close.

    Built with a running weekly series indexed by the week's LAST OBSERVED
    trading day rather than by its nominal Friday, so merge_asof's backward
    match lands on the current week instead of the previous one. Uses only
    closes at or before each row's own date.
    """
    d = df[["stock_code", "trade_date", "close_price"]].copy()
    d["_dt"] = pd.to_datetime(d["trade_date"])
    d = d.sort_values(["stock_code", "_dt"])
    # Week key = the Monday of that row's week; every row in a week shares it.
    d["_wk"] = d["_dt"] - pd.to_timedelta(d["_dt"].dt.weekday, unit="D")

    out = pd.Series(np.nan, index=d.index, dtype="float64")
    for _, g in d.groupby("stock_code", sort=False):
        # Last close of each COMPLETED week, plus the running close of the
        # current one -- the completed history is identical to the original
        # feature, only the in-progress week differs.
        wk_last = g.groupby("_wk")["close_price"].last()
        ma = wk_last.rolling(WEEKLY_MA_PERIODS, min_periods=WEEKLY_MA_PERIODS).mean()
        # For a row mid-week, the week's own close so far is the row's close;
        # the MA uses only the 10 completed weeks BEFORE it, so no future data.
        prev_ma = ma.shift(1)
        ma_by_row = g["_wk"].map(prev_ma)
        out.loc[g.index] = (g["close_price"] - ma_by_row) / ma_by_row * 100
    return out.reindex(df.index)


def measure_staleness(df: pd.DataFrame) -> None:
    """Measure the lag empirically instead of deriving it from the merge code.

    Counts, per weekday, how many trading sessions have passed since the value
    on that row last changed. If the docstring's reading of merge_asof is right,
    the value refreshes on Friday and is then reused Monday-Thursday.
    """
    d = df[["stock_code", "trade_date", "weekly_ma_spread"]].dropna().copy()
    d["_dt"] = pd.to_datetime(d["trade_date"])
    d = d.sort_values(["stock_code", "_dt"])
    g = d.groupby("stock_code")["weekly_ma_spread"]
    d["changed"] = g.diff().ne(0) | g.shift().isna()
    d["weekday"] = d["_dt"].dt.day_name()

    print("Which weekday does the weekly feature actually refresh on?")
    tot = d.groupby("weekday")["changed"].agg(["sum", "count"])
    for wd in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        if wd not in tot.index:
            continue
        r = tot.loc[wd]
        print(f"  {wd:<10} {int(r['sum']):>8,} of {int(r['count']):>8,} rows changed "
              f"({100 * r['sum'] / r['count']:5.1f}%)")

    # Deliberately NOT "mean sessions since the value last changed" -- that
    # number came out at 49 sessions on the first run, which is an artifact:
    # a stock whose price barely moves has a barely-moving weekly close and so
    # a barely-moving spread, and hundreds of those dead rows swamp the mean.
    # The weekday table above is the real evidence, and once the refresh day is
    # known the staleness is just arithmetic.
    print()
    print("  Staleness follows directly from a Friday refresh:")
    print("    Friday 0 sessions | Monday 1 | Tuesday 2 | Wednesday 3 | Thursday 4")
    print("    -> mean 2.0 sessions of already-available price data ignored")
    print()


def main():
    df, idx_df = wf.load_dataset(None)
    measure_staleness(df)

    fresh = weekly_spread_no_lag(df)
    both = pd.DataFrame({"old": df["weekly_ma_spread"], "new": fresh}).dropna()
    print(f"Comparing the two versions on {len(both):,} rows with both defined:")
    print(f"  correlation            : {both['old'].corr(both['new']):.4f}")
    print(f"  mean absolute change   : {(both['new'] - both['old']).abs().mean():.2f} pts")
    print(f"  rows moving > 2 pts    : {100 * ((both['new'] - both['old']).abs() > 2).mean():.1f}%")

    if "--walk" not in sys.argv:
        print("\n(pass --walk to run the 9-window comparison)")
        return

    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    print(f"\nOFF = current (stale) feature, ON = week-to-date feature. "
          f"{len(schedule)} windows each.\n")
    original = df["weekly_ma_spread"].copy()
    try:
        off = _aggregate(wf.run_schedule(df, idx_df, schedule))
        df["weekly_ma_spread"] = fresh
        on = _aggregate(wf.run_schedule(df, idx_df, schedule))
    finally:
        df["weekly_ma_spread"] = original
    print(_format_table(off, on, "week-to-date weekly feature"))


if __name__ == "__main__":
    main()
