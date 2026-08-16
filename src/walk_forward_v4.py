"""
walk_forward_v4.py -- runs backtest_v4's simulate_window() across many
rolling out-of-sample test windows instead of 3 hand-picked ones.

Why: 3 manually-chosen windows can't distinguish "the rule is weak in a
certain market character" from "one bad-luck episode" -- confirmed
directly this session, where "window 3" (2023 H1) turned out to be a
single 12-day bull-trap cluster, not sustained weakness (see
docs/V3_FINDINGS_LOG.md). A real distribution across many windows is
needed before trusting any further tuning aimed at a specific window's
shape.

Fetches the FULL history ONCE (the expensive part, ~15min after the
data_fetch.py pagination fix), then simulates each rolling window
in-memory against that single fetch -- re-fetching per window (the old
approach) would take hours for a schedule this size.

Train window: EXPANDING from FETCH_START (2021-01-01), matching the
existing single-window methodology exactly (simulate_window's threshold
learning already filters on trade_date <= train_end with no lower
bound) -- this script does not introduce a new rolling-train-window
concept, just repeats the validated approach across more test slices.

Test windows: consecutive 6-month blocks, non-overlapping, from
2022-01-01 through the latest available data. Includes the exact
existing "window 3" (2023-01-01..2023-06-30) as a built-in consistency
check -- should reproduce -5.44%/41.7% win if the harness is correct.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/walk_forward_v4.py
"""

import os
import pickle
import sys
from datetime import date, timedelta

# Must be set before importing backtest_v4 -- it reads these as
# module-level constants at import time. FETCH_START stays at the
# existing default (2021-01-01); TEST_END is widened to cover the whole
# schedule below so build_full_dataset's one fetch spans everything.
os.environ.setdefault("V3_TEST_END", "2026-06-30")

import backtest_v4 as bt  # noqa: E402
from supabase import create_client  # noqa: E402


def month_add(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def build_schedule(first_test_start: date, final_test_end: date, test_months: int = 6):
    """Non-overlapping [train_end, test_start, test_end] triples, train
    always expanding from FETCH_START (see module docstring)."""
    schedule = []
    test_start = first_test_start
    while test_start <= final_test_end:
        test_end = min(month_add(test_start, test_months) - timedelta(days=1), final_test_end)
        train_end = test_start - timedelta(days=1)
        schedule.append((train_end, test_start, test_end))
        test_start = month_add(test_start, test_months)
    return schedule


def load_dataset(supabase=None):
    """Returns (df, idx_df) for bt.FETCH_START..bt.TEST_END -- local
    .cache pickle if present (see cache comment below), else fetches via
    `supabase` (required in that case) and caches for next time.

    Extracted from main() so other callers (src/feature_test_harness.py)
    can get the exact same fetch-once/cache-reuse dataset without
    duplicating this logic or re-fetching per call."""
    # Local cache: every sweep run tonight (TP1_MULT, TRAILING_PCT,
    # QUANTILE_CUT, PYRAMID*) used the exact same FETCH_START/TEST_END,
    # meaning identical data was re-downloaded from Supabase ~10+ times in
    # a few hours -- real, avoidable load on a live production project.
    # None of those parameters affect what data gets fetched, only how
    # simulate_window() uses it, so one fetch can serve every sweep point.
    cache_dir = os.path.join(os.path.dirname(__file__), "..", ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"walk_forward_data_{bt.FETCH_START}_{bt.TEST_END}.pkl")
    if os.path.exists(cache_path) and os.environ.get("V3_FORCE_REFETCH", "0") != "1":
        print(f"\n[FETCH] Using local cache ({cache_path}) -- no Supabase query. "
              f"Set V3_FORCE_REFETCH=1 to force a fresh pull.")
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    if supabase is None:
        sys.exit(f"No local cache at {cache_path} and no Supabase client given -- "
                  f"need SUPABASE_URL/SUPABASE_KEY to fetch.")
    print("\n[FETCH] One fetch for the whole schedule (this is the slow part) ...")
    df, idx_df = bt.build_full_dataset(supabase)
    with open(cache_path, "wb") as f:
        pickle.dump((df, idx_df), f)
    print(f"[OK] Cached to {cache_path} for reuse by future sweep runs.")
    return df, idx_df


def run_schedule(df, idx_df, schedule):
    """Runs bt.simulate_window() once per (train_end, test_start, test_end)
    in `schedule` against the given already-loaded df/idx_df, and returns
    one results row per window (pandas DataFrame) -- same per-window
    metrics main() has always computed.

    Extracted from main() so a caller can run the SAME schedule against the
    SAME loaded dataset more than once (e.g. a feature flag off, then on --
    see src/feature_test_harness.py) without re-fetching or re-deriving
    this per-window computation by hand each time."""
    results = []
    for i, (tr_end, te_start, te_end) in enumerate(schedule, 1):
        print(f"\n{'-'*100}\nWindow {i}/{len(schedule)}\n{'-'*100}")
        metrics, df_trades, _df_equity, _regime = bt.simulate_window(df, idx_df, tr_end, te_start, te_end, label=f"W{i}")
        if metrics is None:
            results.append({"window": i, "test_start": te_start, "test_end": te_end, "trades": 0})
            continue
        top5 = df_trades.groupby("stock_code")["pnl"].sum().sort_values(ascending=False).head(5)
        pos_total = df_trades[df_trades["pnl"] > 0]["pnl"].sum()
        conc_pct = 100 * top5.clip(lower=0).sum() / pos_total if pos_total > 0 else float("nan")
        results.append({
            "window": i, "test_start": te_start, "test_end": te_end,
            "trades": metrics["total_trades"], "win_rate": metrics["win_rate"],
            "profit_pct": metrics["total_return_pct"], "bench_pct": metrics["bench_ret"],
            "alpha_pct": metrics["total_return_pct"] - metrics["bench_ret"],
            "profit_factor": metrics["profit_factor"], "max_dd": metrics["max_drawdown"],
            "cvar_95": metrics["cvar_95"],
            "concentration_pct": conc_pct,
        })
    import pandas as pd
    return pd.DataFrame(results)


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    schedule = build_schedule(date(2022, 1, 1), bt.TEST_END)
    print("=" * 100)
    print(f"WALK-FORWARD V3 -- {len(schedule)} rolling windows, {schedule[0][1]} .. {schedule[-1][2]}")
    print("=" * 100)
    for i, (tr_end, te_start, te_end) in enumerate(schedule, 1):
        print(f"  W{i}: train<= {tr_end}  test {te_start}..{te_end}")

    df, idx_df = load_dataset(supabase)
    res_df = run_schedule(df, idx_df, schedule)
    print("\n" + "=" * 100)
    print("WALK-FORWARD SUMMARY -- one row per rolling window")
    print("=" * 100)
    print(res_df.to_string(index=False))

    traded = res_df[res_df["trades"] > 0]
    if not traded.empty:
        print("\n" + "-" * 100)
        print("AGGREGATE ACROSS ALL WINDOWS WITH TRADES")
        print("-" * 100)
        print(f"  Windows with trades   : {len(traded)} / {len(res_df)}")
        print(f"  Windows beating bench : {(traded['alpha_pct'] > 0).sum()} / {len(traded)}")
        print(f"  Windows win-rate > 50%: {(traded['win_rate'] > 50).sum()} / {len(traded)}")
        print(f"  Win rate   : mean {traded['win_rate'].mean():.1f}%  median {traded['win_rate'].median():.1f}%  "
              f"min {traded['win_rate'].min():.1f}%  max {traded['win_rate'].max():.1f}%")
        print(f"  Profit     : mean {traded['profit_pct'].mean():+.2f}%  median {traded['profit_pct'].median():+.2f}%  "
              f"min {traded['profit_pct'].min():+.2f}%  max {traded['profit_pct'].max():+.2f}%")
        print(f"  Alpha      : mean {traded['alpha_pct'].mean():+.2f}%  median {traded['alpha_pct'].median():+.2f}%")
        print(f"  Profit fac : mean {traded['profit_factor'].mean():.2f}  median {traded['profit_factor'].median():.2f}")
        print(f"  Max DD     : mean {traded['max_dd'].mean():.2f}%  worst {traded['max_dd'].min():.2f}%")
        print(f"  CVaR(95%)  : mean {traded['cvar_95'].mean():.2f}%  worst {traded['cvar_95'].min():.2f}%")

    res_df.to_csv("walk_forward_v4_summary.csv", index=False)
    print("\n[OK] Saved walk_forward_v4_summary.csv")


if __name__ == "__main__":
    main()
