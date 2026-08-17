"""check_slot_boundary_gap.py -- the "one thing to do first" from the 2026-08-17
council session (see docs/V3_FINDINGS_LOG.md's "council session on today's
research yield" entry): before building a rank-by-score fix for the
scarce-slot fragility, check whether the ranking function's resolution is
even good enough for that fix to matter.

Reuses diagnose_slot_queue.py's exact same diag hook and cached dataset --
purely additive read of simulate_window's per-day admitted/dropped lists,
now paired by DATE (the earlier diagnostic only kept an unpaired flat list
of scores, discarding which day each admitted score belonged to). No
trading logic touched, no new backtest mechanism, no live-path files
involved.

On each day break_reason == "max_positions": boundary_gap = min(admitted
score that day) - max(dropped score that day). A large, consistently
positive gap means the cutoff is crisp (the fix matters, but candidates
below the line are genuinely worse). A gap near zero or often negative
means Contrarian's "89% == noise" concern was right -- the ranking can't
reliably tell a kept candidate from a dropped one, and no allocation-side
fix (rank-by-score included) would move the needle much.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/check_slot_boundary_gap.py
(no creds needed -- reuses the same cached dataset diagnose_slot_queue.py did.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V3_BANDAR_SIZING", "0")  # same baseline pin as diagnose_slot_queue.py

import walk_forward_v4 as wf  # noqa: E402
from diagnose_slot_queue import run_with_diag  # noqa: E402

if __name__ == "__main__":
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    sb = None
    if url and key:
        from supabase import create_client
        sb = create_client(url, key)

    df, idx_df = wf.load_dataset(sb)
    schedule = wf.build_schedule(date(2022, 1, 1), wf.bt.TEST_END)
    results = run_with_diag(df, idx_df, schedule)

    rows = []
    for w in results:
        for d in w["diag"].get("days", []):
            if d["break_reason"] != "max_positions" or not d["dropped"]:
                continue
            admitted_min = min(a["score"] for a in d["admitted"]) if d["admitted"] else float("nan")
            dropped_max = max(s["score"] for s in d["dropped"])
            rows.append({
                "window": w["window"], "date": d["date"],
                "admitted_min": admitted_min, "dropped_max": dropped_max,
                "boundary_gap": admitted_min - dropped_max,
            })

    gap_df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)

    print("\n" + "=" * 100)
    print(f"SLOT BOUNDARY GAP -- {len(gap_df)} capped days across {gap_df['window'].nunique()} windows")
    print("=" * 100)
    print(gap_df["boundary_gap"].describe().to_string())

    inverted = gap_df[gap_df["boundary_gap"] < 0]
    print(f"\nDays where the boundary INVERTED (a dropped candidate outscored the worst admitted one): "
          f"{len(inverted)}/{len(gap_df)} ({100*len(inverted)/len(gap_df):.1f}%)")

    near_zero = gap_df[gap_df["boundary_gap"].abs() < 1.0]
    print(f"Days where the gap is within +-1.0 score points (a near-tie by any reasonable read): "
          f"{len(near_zero)}/{len(gap_df)} ({100*len(near_zero)/len(gap_df):.1f}%)")

    out_path = "D:/Neira/Neira/.claude/worktrees/v2-hmm-screener/.cache/slot_boundary_gap.csv"
    gap_df.to_csv(out_path, index=False)
    print(f"\n[OK] Saved {out_path}")
