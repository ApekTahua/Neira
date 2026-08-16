"""
feature_test_harness.py -- run_isolated_feature_test(): the OFF-vs-ON
9-window walk-forward + metrics table that every recent V3/V4 feature-flag
experiment (accdist_score sizing, rotation_pairs sizing, the trend-duration
gate, the market-participation gate...) hand-rolled from scratch. Extracted
so the next candidate is a few lines, not ~30 re-typed by hand each time --
see docs/V3_FINDINGS_LOG.md and docs/BANDARMOLOGY_DESIGN.md for what those
hand-written tables looked like.

This is scaffolding, not a decay-monitoring/registry system: no database,
no history across runs, no automated promote/reject verdict. It runs the
schedule twice against one already-loaded dataset and formats the same
table shape those commits already used by hand. The prose (why the feature
might work, what was tried and ruled out, the promotion verdict) still gets
written by hand in the findings log -- that part isn't mechanical.

How the OFF/ON toggle works: backtest_v4.py reads its env vars into
module-level constants once, at import time -- re-importing the module in
the same process is a no-op (Python caches by module name), so an env var
can't toggle a flag mid-process. run_isolated_feature_test() instead takes
a `set_flag(enabled: bool)` callback that mutates the already-imported
backtest_v4 module's attribute(s) directly. That's also exactly how the
ad-hoc sweep scripts behind the trend-duration/participation-gate commits
did it (see .cache/participation_sweep_results.csv's "config" column).

------------------------------------------------------------------------
Usage template for the NEXT feature test (attempt #7+):

    import backtest_v4 as bt
    from feature_test_harness import run_isolated_feature_test

    def set_my_gate(enabled: bool) -> None:
        bt.MY_GATE_ENABLED = enabled
        # if the candidate has its own threshold, leave it at its env-var
        # default here -- set_flag only toggles on/off, it doesn't sweep.

    rows, table_md = run_isolated_feature_test("my_gate", set_my_gate)
    print(table_md)  # paste straight into docs/V3_FINDINGS_LOG.md

Produces (and returns) the same table shape as every hand-written one in
the findings log:

    | Metric | OFF | ON (my_gate) |
    |---|---|---|
    | Windows beating benchmark | 6/9 | ... |
    | Windows win-rate > 50% | 4/9 | ... |
    | Win rate (mean / median) | ... | ... |
    | Profit (mean / median) | ... | ... |
    | Alpha (mean / median) | ... | ... |
    | Profit factor (mean / median) | ... | ... |
    | Max drawdown (mean / worst) | ... | ... |

Run standalone (`python src/feature_test_harness.py`) to see this against
the actual V3_PARTICIPATION_GATE flag -- the correctness check for this
module: it should reproduce the OFF and ON_0.95 rows from commit f9cd458
(docs/V3_FINDINGS_LOG.md, "Market-wide participation gate...") exactly.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/feature_test_harness.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists,
matching walk_forward_v4.load_dataset's own fetch-once/cache-reuse rule.)
"""

import os
from datetime import date

import pandas as pd

import walk_forward_v4 as wf  # noqa: E402 -- sets V3_TEST_END default before bt import

bt = wf.bt  # the exact module object wf's own bt reads/writes -- see module docstring


def _aggregate(res_df: pd.DataFrame) -> dict:
    """One row's worth of the OFF/ON table, from a run_schedule() result --
    same numbers walk_forward_v4.main()'s own AGGREGATE block prints."""
    traded = res_df[res_df["trades"] > 0]
    if traded.empty:
        return {"beat_bench": "0/0", "win_gt50": "0/0", "win_mean": float("nan"), "win_median": float("nan"),
                "profit_mean": float("nan"), "profit_median": float("nan"), "alpha_mean": float("nan"),
                "alpha_median": float("nan"), "pf_mean": float("nan"), "pf_median": float("nan"),
                "dd_mean": float("nan"), "dd_worst": float("nan")}
    return {
        "beat_bench": f"{(traded['alpha_pct'] > 0).sum()}/{len(traded)}",
        "win_gt50": f"{(traded['win_rate'] > 50).sum()}/{len(traded)}",
        "win_mean": traded["win_rate"].mean(), "win_median": traded["win_rate"].median(),
        "profit_mean": traded["profit_pct"].mean(), "profit_median": traded["profit_pct"].median(),
        "alpha_mean": traded["alpha_pct"].mean(), "alpha_median": traded["alpha_pct"].median(),
        "pf_mean": traded["profit_factor"].mean(), "pf_median": traded["profit_factor"].median(),
        "dd_mean": traded["max_dd"].mean(), "dd_worst": traded["max_dd"].min(),
    }


def _format_table(off: dict, on: dict, on_label: str) -> str:
    def pct(v):
        return "n/a" if pd.isna(v) else f"{v:+.2f}%"

    def plain(v, fmt="{:.1f}%"):
        return "n/a" if pd.isna(v) else fmt.format(v)

    rows = [
        ("Windows beating benchmark", off["beat_bench"], on["beat_bench"]),
        ("Windows win-rate > 50%", off["win_gt50"], on["win_gt50"]),
        ("Win rate (mean / median)",
         f"{plain(off['win_mean'])} / {plain(off['win_median'])}",
         f"{plain(on['win_mean'])} / {plain(on['win_median'])}"),
        ("Profit (mean / median)", f"{pct(off['profit_mean'])} / {pct(off['profit_median'])}",
         f"{pct(on['profit_mean'])} / {pct(on['profit_median'])}"),
        ("Alpha (mean / median)", f"{pct(off['alpha_mean'])} / {pct(off['alpha_median'])}",
         f"{pct(on['alpha_mean'])} / {pct(on['alpha_median'])}"),
        ("Profit factor (mean / median)", f"{plain(off['pf_mean'], '{:.2f}')} / {plain(off['pf_median'], '{:.2f}')}",
         f"{plain(on['pf_mean'], '{:.2f}')} / {plain(on['pf_median'], '{:.2f}')}"),
        ("Max drawdown (mean / worst)", f"{pct(off['dd_mean'])} / {pct(off['dd_worst'])}",
         f"{pct(on['dd_mean'])} / {pct(on['dd_worst'])}"),
    ]
    lines = [f"| Metric | OFF | ON ({on_label}) |", "|---|---|---|"]
    lines += [f"| {name} | {off_v} | {on_v} |" for name, off_v, on_v in rows]
    return "\n".join(lines)


def run_isolated_feature_test(label: str, set_flag, supabase=None, schedule=None):
    """Runs the 9-window walk-forward (walk_forward_v4's own schedule,
    2022-01-01.. bt.TEST_END, unless `schedule` overrides it) once with
    `set_flag(False)`, once with `set_flag(True)`, against one shared
    dataset fetch. Restores the flag to False when done either way.

    Returns (rows, table_md): `rows` is {"OFF": {...}, "ON": {...}} (the
    _aggregate() dicts, for programmatic use); `table_md` is the markdown
    table ready to paste into the findings log.
    """
    if schedule is None:
        schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset(supabase)

    try:
        set_flag(False)
        off_res = wf.run_schedule(df, idx_df, schedule)
        set_flag(True)
        on_res = wf.run_schedule(df, idx_df, schedule)
    finally:
        set_flag(False)

    off_agg, on_agg = _aggregate(off_res), _aggregate(on_res)
    table_md = _format_table(off_agg, on_agg, label)
    print("\n" + "=" * 100)
    print(f"ISOLATED FEATURE TEST -- {label}")
    print("=" * 100)
    print(table_md)
    return {"OFF": off_agg, "ON": on_agg}, table_md


if __name__ == "__main__":
    # Retrofit / correctness check: V3_PARTICIPATION_GATE, isolated the same
    # way commit f9cd458 (docs/V3_FINDINGS_LOG.md) ran it by hand. Should
    # reproduce that commit's OFF and ON_0.95 (PARTICIPATION_MIN's own
    # default, 0.95) rows exactly.
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    sb = None
    if url and key:
        from supabase import create_client
        sb = create_client(url, key)

    def set_participation_gate(enabled: bool) -> None:
        bt.PARTICIPATION_GATE_ENABLED = enabled

    run_isolated_feature_test("participation_gate @ 0.95", set_participation_gate, supabase=sb)
