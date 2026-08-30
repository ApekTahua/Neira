"""sweep_sl_confidence.py -- SCRATCH/RESEARCH ONLY, bounds sensitivity sweep for
V4_SL_CONFIDENCE (docs/V3_FINDINGS_LOG.md 2026-08-30 entry). In-process (not
subprocess-per-cell like sweep_broker_flow_gate.py) since this needs no fresh
Supabase credentials at all -- reuses walk_forward_v4's own load_dataset()
cache once, then mutates bt.SL_CONFIDENCE_MIN/MAX directly per cell, same
"set_flag() on the already-imported module" technique feature_test_harness.py
uses.

V4_ATR_PRICE_RATIO_MAX pinned to 0.08 (must be set before backtest_v4 import)
-- same baseline convention as test_sl_confidence.py / the two most recent
broker-flow/divergence sessions (mean alpha +26.17%, mean PF 1.95, 366 trades).

Grid: (MIN, MAX) pairs -- (1.0, 1.0) is a deliberate sanity check (forces
confidence_adjustment==1.0 regardless of score, so must reproduce OFF exactly);
(0.7, 1.0) / (1.0, 1.3) isolate the tighten-only / widen-only halves of the
default band; (0.5, 2.0) matches size_mult's own bound magnitude as the wide
extreme.

Usage: python src/sweep_sl_confidence.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl)
"""

import os

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import pandas as pd  # noqa: E402

import walk_forward_v4 as wf  # noqa: E402
from feature_test_harness import _aggregate  # noqa: E402

bt = wf.bt

GRID = [
    ("sanity (1.0,1.0)", 1.0, 1.0),
    ("tighten-only (0.7,1.0)", 0.7, 1.0),
    ("widen-only (1.0,1.3)", 1.0, 1.3),
    ("narrow (0.85,1.15)", 0.85, 1.15),
    ("default (0.7,1.3)", 0.7, 1.3),
    ("wide (0.5,1.5)", 0.5, 1.5),
    ("size_mult-scale (0.5,2.0)", 0.5, 2.0),
]


def main():
    from datetime import date
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset()

    bt.SL_CONFIDENCE_ENABLED = False
    off_res = wf.run_schedule(df, idx_df, schedule)
    off_agg = _aggregate(off_res)
    print("\n" + "=" * 100)
    print("OFF (baseline, ATR<=0.08)")
    print("=" * 100)
    print(off_res.to_string(index=False))

    rows = [{"cell": "OFF (baseline)", "sl_min": None, "sl_max": None, **off_agg}]

    for label, lo, hi in GRID:
        bt.SL_CONFIDENCE_ENABLED = True
        bt.SL_CONFIDENCE_MIN, bt.SL_CONFIDENCE_MAX = lo, hi
        print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}")
        res = wf.run_schedule(df, idx_df, schedule)
        print(res.to_string(index=False))
        agg = _aggregate(res)
        rows.append({"cell": label, "sl_min": lo, "sl_max": hi, **agg,
                      **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in res.itertuples()},
                      **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in res.itertuples()}})

    bt.SL_CONFIDENCE_ENABLED = False  # restore, same discipline as run_isolated_feature_test's finally-block

    out = pd.DataFrame(rows)
    print("\n" + "=" * 110)
    print("SL_CONFIDENCE BOUNDS SWEEP -- one row per (MIN, MAX) cell")
    print("=" * 110)
    show_cols = ["cell", "sl_min", "sl_max", "beat_bench", "win_gt50", "win_mean", "profit_mean",
                 "alpha_mean", "pf_mean", "dd_mean", "dd_worst"]
    print(out[show_cols].to_string(index=False))
    out.to_csv("sweep_sl_confidence_summary.csv", index=False)
    print("\n[OK] Saved sweep_sl_confidence_summary.csv")


if __name__ == "__main__":
    main()
