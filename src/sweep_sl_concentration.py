"""sweep_sl_concentration.py -- SCRATCH/RESEARCH ONLY, bounds sensitivity sweep for
V4_SL_CONCENTRATION (docs/V3_FINDINGS_LOG.md 2026-08-30 entry, idea #3 of this session's
three-idea SL-width thread). Same in-process technique as sweep_sl_confidence.py: reuse
walk_forward_v4's own load_dataset() cache once, mutate bt.SL_CONCENTRATION_MIN/MAX
directly per cell.

V4_ATR_PRICE_RATIO_MAX pinned to 0.08 (V4_PAPER's live config), same baseline convention
as every other sweep this session.

Two passes:
  PASS A -- BANDAR_SIZING_ENABLED left at its live default (ON). Tests the flag as it would
            actually run in the live config.
  PASS B -- BANDAR_SIZING_ENABLED forced OFF. Isolates the SL-width effect from
            concentration's OWN existing role in position SIZING (council correction #2 --
            without this pass, an apparent improvement in Pass A could be the same
            sizing-interaction artifact idea #2's `wide (0.5,1.5)` cell turned out to be,
            just reached via risk_per_share/lots_risk instead of size_mult).

Grid: (MIN, MAX) pairs -- (1.0, 1.0) is a sanity check (forces the adjustment to 1.0
regardless of concentration, must reproduce OFF exactly); (0.8, 1.3) is this flag's own
chosen default (see backtest_v4.py's module-level comment for why); (0.8, 1.0) / (1.0, 1.3)
isolate the tighten-only / widen-only halves; (0.5, 2.0) matches BANDAR_SIZING_ENABLED's own
bound magnitude (same signal, its own sizing multiplier) as the wide extreme.

Usage: python src/sweep_sl_concentration.py
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
    ("tighten-only (0.8,1.0)", 0.8, 1.0),
    ("widen-only (1.0,1.3)", 1.0, 1.3),
    ("default (0.8,1.3)", 0.8, 1.3),
    ("narrow (0.9,1.15)", 0.9, 1.15),
    ("wide (0.5,2.0)", 0.5, 2.0),
]


def _run_pass(df, idx_df, schedule, bandar_sizing_on: bool) -> pd.DataFrame:
    bt.BANDAR_SIZING_ENABLED = bandar_sizing_on
    label = "BANDAR_SIZING ON (live default)" if bandar_sizing_on else "BANDAR_SIZING FORCED OFF (isolation)"

    bt.SL_CONCENTRATION_ENABLED = False
    off_res = wf.run_schedule(df, idx_df, schedule)
    off_agg = _aggregate(off_res)
    print(f"\n{'='*100}\nOFF (baseline, ATR<=0.08, {label})\n{'='*100}")
    print(off_res.to_string(index=False))

    rows = [{"cell": "OFF (baseline)", "sl_min": None, "sl_max": None, **off_agg}]

    for cell_label, lo, hi in GRID:
        bt.SL_CONCENTRATION_ENABLED = True
        bt.SL_CONCENTRATION_MIN, bt.SL_CONCENTRATION_MAX = lo, hi
        print(f"\n{'='*100}\n[SWEEP] {cell_label} -- {label}\n{'='*100}")
        res = wf.run_schedule(df, idx_df, schedule)
        print(res.to_string(index=False))
        agg = _aggregate(res)
        rows.append({"cell": cell_label, "sl_min": lo, "sl_max": hi, **agg,
                      **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in res.itertuples()},
                      **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in res.itertuples()}})

    bt.SL_CONCENTRATION_ENABLED = False  # restore between passes / at the end
    out = pd.DataFrame(rows)
    show_cols = ["cell", "sl_min", "sl_max", "beat_bench", "win_gt50", "win_mean", "profit_mean",
                 "alpha_mean", "pf_mean", "dd_mean", "dd_worst"]
    print(f"\n{'='*110}\nSL_CONCENTRATION BOUNDS SWEEP -- {label}\n{'='*110}")
    print(out[show_cols].to_string(index=False))
    return out


def main():
    from datetime import date
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset()

    live_bandar_default = bt.BANDAR_SIZING_ENABLED  # restore at the end regardless

    out_a = _run_pass(df, idx_df, schedule, bandar_sizing_on=True)
    out_a.to_csv("sweep_sl_concentration_bandar_on.csv", index=False)
    print("\n[OK] Saved sweep_sl_concentration_bandar_on.csv")

    out_b = _run_pass(df, idx_df, schedule, bandar_sizing_on=False)
    out_b.to_csv("sweep_sl_concentration_bandar_off.csv", index=False)
    print("\n[OK] Saved sweep_sl_concentration_bandar_off.csv")

    bt.BANDAR_SIZING_ENABLED = live_bandar_default
    bt.SL_CONCENTRATION_ENABLED = False


if __name__ == "__main__":
    main()
