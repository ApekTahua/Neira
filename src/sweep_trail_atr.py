"""sweep_trail_atr.py -- SCRATCH/RESEARCH ONLY, full 9-window walk-forward + key_value sweep
for V4_TRAIL_ATR_ENABLED (docs/V3_FINDINGS_LOG.md 2026-08-30 entry, "ATR-scaled trailing
stop (UT Bot style)"). Same in-process technique as sweep_sl_concentration.py: reuse
walk_forward_v4's own load_dataset() cache once, mutate bt.TRAIL_ATR_ENABLED/
TRAIL_ATR_KEY_VALUE directly per cell.

V4_ATR_PRICE_RATIO_MAX pinned to 0.08 (V4_PAPER's live config), same baseline convention as
every other sweep this session.

Single pass only (unlike the SL-width ideas' BANDAR_SIZING-isolation two-pass design): this
flag only moves WHEN/at what price an already-open position exits -- lots/alloc/
risk_per_share are all fixed at ENTRY time, before any trailing-stop logic ever runs, so
there is no lots-level sizing channel for this flag to interact with at all (confirmed by
grep: TRAIL_ATR_ENABLED/TRAIL_ATR_KEY_VALUE are read only inside evaluate_position_exit,
never inside compute_entry_fill).

Grid: TRAIL_ATR_KEY_VALUE in {1.5, 2.0, 2.5} (the task's own suggested small sweep).

Usage: python src/sweep_trail_atr.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl)
"""

import os

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import pandas as pd  # noqa: E402

import walk_forward_v4 as wf  # noqa: E402
from feature_test_harness import _aggregate  # noqa: E402

bt = wf.bt

GRID = [1.5, 2.0, 2.5]


def main():
    from datetime import date
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset()

    bt.TRAIL_ATR_ENABLED = False
    off_res = wf.run_schedule(df, idx_df, schedule)
    off_agg = _aggregate(off_res)
    print(f"\n{'='*100}\nOFF (baseline, ATR<=0.08)\n{'='*100}")
    print(off_res.to_string(index=False))

    rows = [{"cell": "OFF (baseline)", "key_value": None, **off_agg,
             **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in off_res.itertuples()},
             **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in off_res.itertuples()}}]

    for key_value in GRID:
        bt.TRAIL_ATR_ENABLED = True
        bt.TRAIL_ATR_KEY_VALUE = key_value
        print(f"\n{'='*100}\n[SWEEP] key_value={key_value}\n{'='*100}")
        res = wf.run_schedule(df, idx_df, schedule)
        print(res.to_string(index=False))
        agg = _aggregate(res)
        rows.append({"cell": f"key_value={key_value}", "key_value": key_value, **agg,
                      **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in res.itertuples()},
                      **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in res.itertuples()}})

    bt.TRAIL_ATR_ENABLED = False  # restore default
    out = pd.DataFrame(rows)
    show_cols = ["cell", "key_value", "beat_bench", "win_gt50", "win_mean", "profit_mean",
                 "alpha_mean", "pf_mean", "dd_mean", "dd_worst"]
    print(f"\n{'='*110}\nTRAIL_ATR_KEY_VALUE SWEEP\n{'='*110}")
    print(out[show_cols].to_string(index=False))
    out.to_csv("sweep_trail_atr.csv", index=False)
    print("\n[OK] Saved sweep_trail_atr.csv")


if __name__ == "__main__":
    main()
