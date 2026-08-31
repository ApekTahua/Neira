"""sweep_struct_sl.py -- SCRATCH/RESEARCH ONLY, full 9-window walk-forward + lookback/buffer
sweep for V4_STRUCT_SL_ENABLED (docs/V3_FINDINGS_LOG.md 2026-08-30 entry, "structural stop
(Smart Money Concepts swing-low)"). Same in-process technique as sweep_sl_concentration.py:
reuse walk_forward_v4's own load_dataset() cache once, mutate bt.STRUCT_SL_ENABLED/
STRUCT_SL_LOOKBACK/STRUCT_SL_BUFFER_ATR directly per cell.

V4_ATR_PRICE_RATIO_MAX pinned to 0.08 (V4_PAPER's live config), same baseline convention as
every other sweep this session.

Single pass (BANDAR_SIZING left at its live default, ON): unlike SL_CONCENTRATION_ENABLED,
this flag's swing-low signal is pure price geometry (the `low` column), structurally
unrelated to `concentration` (BANDAR_SIZING_ENABLED's own signal) or any other per-candidate
sizing multiplier -- there is no shared-signal confound for a BANDAR_SIZING-off isolation
pass to catch. It DOES still feed risk_per_share/lots_risk (same channel SL_MULT itself
always has) -- trade counts are expected to move a little for that reason, checked in the
per-cell table below, not assumed away.

Grid: STRUCT_SL_LOOKBACK in {2, 3} (standard fractal N) x STRUCT_SL_BUFFER_ATR in
{0.5, 0.75, 1.0} (the task's own suggested buffer range).

Usage: python src/sweep_struct_sl.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl)
"""

import os

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import pandas as pd  # noqa: E402

import walk_forward_v4 as wf  # noqa: E402
from feature_test_harness import _aggregate  # noqa: E402

bt = wf.bt

LOOKBACKS = [2, 3]
BUFFERS = [0.5, 0.75, 1.0]


def main():
    from datetime import date
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset()

    bt.STRUCT_SL_ENABLED = False
    off_res = wf.run_schedule(df, idx_df, schedule)
    off_agg = _aggregate(off_res)
    print(f"\n{'='*100}\nOFF (baseline, ATR<=0.08)\n{'='*100}")
    print(off_res.to_string(index=False))

    rows = [{"cell": "OFF (baseline)", "lookback": None, "buffer_atr": None, **off_agg,
             **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in off_res.itertuples()},
             **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in off_res.itertuples()}}]

    for lookback in LOOKBACKS:
        for buffer_atr in BUFFERS:
            bt.STRUCT_SL_ENABLED = True
            bt.STRUCT_SL_LOOKBACK, bt.STRUCT_SL_BUFFER_ATR = lookback, buffer_atr
            label = f"lookback={lookback}, buffer_atr={buffer_atr}"
            print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}")
            res = wf.run_schedule(df, idx_df, schedule)
            print(res.to_string(index=False))
            agg = _aggregate(res)
            rows.append({"cell": label, "lookback": lookback, "buffer_atr": buffer_atr, **agg,
                          **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in res.itertuples()},
                          **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in res.itertuples()}})

    bt.STRUCT_SL_ENABLED = False  # restore default
    out = pd.DataFrame(rows)
    show_cols = ["cell", "lookback", "buffer_atr", "beat_bench", "win_gt50", "win_mean",
                 "profit_mean", "alpha_mean", "pf_mean", "dd_mean", "dd_worst"]
    print(f"\n{'='*110}\nSTRUCT_SL LOOKBACK/BUFFER SWEEP\n{'='*110}")
    print(out[show_cols].to_string(index=False))
    out.to_csv("sweep_struct_sl.csv", index=False)
    print("\n[OK] Saved sweep_struct_sl.csv")


if __name__ == "__main__":
    main()
