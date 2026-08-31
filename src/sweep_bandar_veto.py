"""sweep_bandar_veto.py -- SCRATCH/RESEARCH ONLY, 9-window walk-forward + concentration-
threshold sweep for V4_BANDAR_VETO (docs/V3_FINDINGS_LOG.md, 2026-08-31 council session --
hard admit/reject veto, categorically different from BANDAR_SIZING_ENABLED's continuous
size multiplier). Same in-process technique as sweep_sl_concentration.py: reuse
walk_forward_v4's own load_dataset() cache once, mutate bt.BANDAR_VETO_* directly per cell.

V4_ATR_PRICE_RATIO_MAX pinned to 0.08 (V4_PAPER's live config), same baseline convention
as every other sweep this session.

Two passes, per this session's own standing "sizing-interaction confound" requirement:
  PASS A -- BANDAR_SIZING_ENABLED left at its live default (ON).
  PASS B -- BANDAR_SIZING_ENABLED forced OFF. Isolates the veto's own effect from
            concentration's OWN existing role in position SIZING -- an apparent
            improvement in Pass A alone could just be "the veto happens to drop the
            candidates BANDAR_SIZING would have floored to 0.5x anyway," not new
            information.

Grid: BANDAR_VETO_CONCENTRATION_MAX in {0.2, 0.3, 0.4} (default 0.3), NET_LOT_MIN fixed
at 0.0 (a pure sign check -- net_lot's raw units aren't comparable across stocks without
further normalization not built here, see the flag's own module-level comment).

Usage: python src/sweep_bandar_veto.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl)
"""

import os

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import pandas as pd  # noqa: E402

import walk_forward_v4 as wf  # noqa: E402
from feature_test_harness import _aggregate  # noqa: E402

bt = wf.bt

GRID = [0.2, 0.3, 0.4]


def _run_pass(df, idx_df, schedule, bandar_sizing_on: bool) -> pd.DataFrame:
    bt.BANDAR_SIZING_ENABLED = bandar_sizing_on
    label = "BANDAR_SIZING ON (live default)" if bandar_sizing_on else "BANDAR_SIZING FORCED OFF (isolation)"

    bt.BANDAR_VETO_ENABLED = False
    off_res = wf.run_schedule(df, idx_df, schedule)
    off_agg = _aggregate(off_res)
    print(f"\n{'='*100}\nOFF (baseline, ATR<=0.08, {label})\n{'='*100}")
    print(off_res.to_string(index=False))

    rows = [{"cell": "OFF (baseline)", "conc_max": None, "trades": int(off_res["trades"].sum()),
             "vetoed": 0, **off_agg,
             **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in off_res.itertuples()},
             **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in off_res.itertuples()}}]

    for conc_max in GRID:
        bt.BANDAR_VETO_ENABLED = True
        bt.BANDAR_VETO_CONCENTRATION_MAX = conc_max
        bt.BANDAR_VETO_NET_LOT_MIN = 0.0
        bt.BANDAR_VETO_LOG.clear()
        print(f"\n{'='*100}\n[SWEEP] concentration_max={conc_max} -- {label}\n{'='*100}")
        res = wf.run_schedule(df, idx_df, schedule)
        print(res.to_string(index=False))
        agg = _aggregate(res)
        n_vetoed = len(bt.BANDAR_VETO_LOG)
        rows.append({"cell": f"conc_max={conc_max}", "conc_max": conc_max,
                      "trades": int(res["trades"].sum()), "vetoed": n_vetoed, **agg,
                      **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in res.itertuples()},
                      **{f"w{int(r.window)}_dd": round(r.max_dd, 2) for r in res.itertuples()}})
        if bandar_sizing_on:
            # per-window veto count, only needed once (identical between passes -- the
            # veto's own admission decision doesn't depend on BANDAR_SIZING_ENABLED,
            # only what happens AFTER a candidate is admitted does)
            veto_df = pd.DataFrame(bt.BANDAR_VETO_LOG)
            if not veto_df.empty:
                veto_df.to_csv(f"../.cache/bandar_veto_log_conc{conc_max}.csv", index=False)

    bt.BANDAR_VETO_ENABLED = False  # restore between passes / at the end
    out = pd.DataFrame(rows)
    show_cols = ["cell", "conc_max", "trades", "vetoed", "beat_bench", "win_gt50", "win_mean",
                 "profit_mean", "alpha_mean", "pf_mean", "dd_mean", "dd_worst"]
    print(f"\n{'='*110}\nBANDAR_VETO CONCENTRATION-THRESHOLD SWEEP -- {label}\n{'='*110}")
    print(out[show_cols].to_string(index=False))
    return out


def main():
    from datetime import date
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset()

    live_bandar_default = bt.BANDAR_SIZING_ENABLED  # restore at the end regardless

    out_a = _run_pass(df, idx_df, schedule, bandar_sizing_on=True)
    out_a.to_csv("sweep_bandar_veto_bandar_on.csv", index=False)
    print("\n[OK] Saved sweep_bandar_veto_bandar_on.csv")

    out_b = _run_pass(df, idx_df, schedule, bandar_sizing_on=False)
    out_b.to_csv("sweep_bandar_veto_bandar_off.csv", index=False)
    print("\n[OK] Saved sweep_bandar_veto_bandar_off.csv")

    bt.BANDAR_SIZING_ENABLED = live_bandar_default
    bt.BANDAR_VETO_ENABLED = False


if __name__ == "__main__":
    main()
