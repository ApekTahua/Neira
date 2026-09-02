"""Walk-forward sweep of the extension gate (V4_EXTENSION_GATE).

Question: does refusing to name a stock that has already run more than X% above
its own moving average improve anything, or is "you always buy the top" a true
observation about the entries that costs nothing?

Swept, not tested at one value, deliberately. The hysteresis-band episode in
docs/V3_FINDINGS_LOG.md is the precedent: a single threshold looked like a
validated optimum and turned out to be one lucky point in a landscape that
swung 61%-501% across neighbouring values. A gate worth shipping should improve
things across a band of thresholds, not at exactly one.

Baseline is run once and reused for every cell -- the gate cannot affect it, and
re-running it per cell would burn 9 windows of compute to reproduce the same
numbers.

Read-only against the cached dataset. Changes no live config.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/sweep_extension_gate.py
"""

import csv
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from feature_test_harness import _aggregate  # noqa: E402

# (moving average column, max fraction above it before a candidate is dropped)
#
# Thresholds picked off the qualifying pool's OWN distribution (350k liquid
# rows, 2022+, measured before running anything), not round numbers: above
# ma50 the pool's median is +11.2%, p70 +20.7%, p80 +30.1%, p90 +50.8%; above
# ma20 it is +4.6% / +9.7% / +14.6% / +25.5%. So ma50>0.10 cuts roughly the top
# half, 0.20 the top ~30%, 0.30 the top ~20%, 0.50 the top ~10%. A gate set
# above p90 would barely bind and would tell us nothing.
CELLS = [
    ("ma50", 0.10), ("ma50", 0.15), ("ma50", 0.20), ("ma50", 0.30), ("ma50", 0.50),
    ("ma20", 0.05), ("ma20", 0.10), ("ma20", 0.15), ("ma20", 0.25),
]
OUT = os.path.join(os.path.dirname(__file__), "..", ".cache", "extension_gate_sweep.csv")

# Cells already present in OUT are skipped on restart -- the first run of this
# sweep was killed at 6/10 when its session ended, and the ma50 half plus the
# baseline are identical work to redo.
_done = set()
if os.path.exists(OUT):
    import csv as _csv
    with open(OUT, encoding="utf-8") as _f:
        _done = {r["cell"] for r in _csv.DictReader(_f)}
    CELLS = [(m, t) for m, t in CELLS if f"{m}>{t:.2f}" not in _done]


def row_of(agg: dict, res_df) -> dict:
    """_aggregate's own keys, plus the trade count, which it does not carry but
    which matters here: a gate that improves every ratio by refusing to trade is
    not an improvement, it is a smaller strategy."""
    return {
        "windows_beating_bench": agg["beat_bench"],
        "windows_win_gt_50": agg["win_gt50"],
        "win_rate_mean": agg["win_mean"],
        "win_rate_median": agg["win_median"],
        "profit_mean": agg["profit_mean"],
        "profit_median": agg["profit_median"],
        "alpha_mean": agg["alpha_mean"],
        "alpha_median": agg["alpha_median"],
        "pf_mean": agg["pf_mean"],
        "pf_median": agg["pf_median"],
        "dd_worst": agg["dd_worst"],
        "trades_total": int(res_df["trades"].sum()),
    }


def main():
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset(
        create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        if os.environ.get("SUPABASE_URL") else None)
    print(f"\n{len(schedule)} windows, {len(CELLS)} gate settings + 1 baseline\n")

    bt.EXTENSION_GATE_ENABLED = False
    if _done:
        # Carry forward the rows already on disk instead of starting a new
        # list -- otherwise finishing the remaining cells silently deletes
        # the finished ones from the CSV, which is exactly what the first
        # version of this resume path did to five completed ma50 cells.
        import csv as _csv2
        with open(OUT, encoding="utf-8") as _f2:
            results = list(_csv2.DictReader(_f2))
        print(f"resuming -- {len(results)} rows on disk, {len(CELLS)} cells left")
    else:
        print("=" * 100)
        print("BASELINE (gate off)")
        print("=" * 100)
        base_res = wf.run_schedule(df, idx_df, schedule)
        results = [{"cell": "baseline", "ma": "-", "max_pct": "-",
                    **row_of(_aggregate(base_res), base_res)}]

    for ma, thr in CELLS:
        print("=" * 100 + f"\nGATE ON -- drop candidates more than {thr:.0%} above {ma}\n" + "=" * 100)
        bt.EXTENSION_GATE_ENABLED = True
        bt.EXTENSION_GATE_MA = ma
        bt.EXTENSION_GATE_MAX = thr
        res = wf.run_schedule(df, idx_df, schedule)
        results.append({"cell": f"{ma}>{thr:.2f}", "ma": ma, "max_pct": thr,
                        **row_of(_aggregate(res), res)})
        # Written after every cell, not at the end: a sweep this long should not
        # lose everything if it is interrupted partway.
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)

    bt.EXTENSION_GATE_ENABLED = False

    print("\n" + "=" * 110)
    print(f"{'cell':<14}{'alpha mean':>12}{'alpha med':>12}{'win mean':>10}"
          f"{'profit mean':>13}{'PF mean':>10}{'worst DD':>10}{'trades':>9}")
    print("=" * 110)
    for r in results:
        def f(v, d=2):
            return f"{v:.{d}f}" if isinstance(v, (int, float)) else "-"
        print(f"{r['cell']:<14}{f(r['alpha_mean']):>12}{f(r['alpha_median']):>12}"
              f"{f(r['win_rate_mean'],1):>10}{f(r['profit_mean']):>13}"
              f"{f(r['pf_mean']):>10}{f(r['dd_worst']):>10}{str(r['trades_total']):>9}")
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    from supabase import create_client  # noqa: E402  (only needed on a cache miss)
    main()
