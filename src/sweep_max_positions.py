"""sweep_max_positions.py -- Phase 2 of the slot-queue-fragility research
(docs/V3_FINDINGS_LOG.md): Phase 1 (src/diagnose_slot_queue.py) found
MAX_POSITIONS binds on 84.8% of all candidate-days across the full 9-window
walk-forward schedule (not just Window 8), dropping ~15x more ranked
candidates than get admitted, with dropped candidates' scores averaging
61-97% of admitted candidates' scores in every window -- comparable quality,
not dregs. This sweeps MAX_POSITIONS wider with a correspondingly-scaled
ALLOC_PCT (holding MAX_POSITIONS x ALLOC_PCT -- the nominal max concurrent
notional exposure multiple -- roughly constant at the current default's 1.2x)
to see whether admitting more of the comparably-scored dropped signal
actually helps, hurts, or is neutral.

Same "plateau, not peak" discipline as sweep_vol_band_mult.py / the
hysteresis-band walk-back: reports per-window profit/win/PF/DD/trades/
concentration, not just the aggregate.

Axes: paired (MAX_POSITIONS, ALLOC_PCT) points, not a full 2D grid -- the
task frames this as "MAX_POSITIONS with a correspondingly adjusted
ALLOC_PCT," i.e. one design axis, not two independent ones.

Usage:
    python src/sweep_max_positions.py
    SWEEP_MAX_POS=6:0.20,8:0.15,10:0.12,8:0.20 python src/sweep_max_positions.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V3_BANDAR_SIZING", "0")  # matches the reproducible baseline this log has used since the tick-size-bug entry

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

DEFAULT_GRID = "6:0.20,8:0.15,10:0.12"


def _parse_grid(raw: str):
    pairs = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        mp, alloc = chunk.split(":")
        pairs.append((int(mp), float(alloc)))
    return pairs


GRID = _parse_grid(os.environ.get("SWEEP_MAX_POS", DEFAULT_GRID))


def main():
    supabase = None
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if url and key:
        from supabase import create_client
        supabase = create_client(url, key)

    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset(supabase)

    orig_max_pos, orig_alloc = bt.MAX_POSITIONS, bt.ALLOC_PCT
    all_rows = []
    for max_pos, alloc_pct in GRID:
        label = f"MAX_POSITIONS={max_pos} ALLOC_PCT={alloc_pct}"
        print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}", flush=True)
        bt.MAX_POSITIONS = max_pos
        bt.ALLOC_PCT = alloc_pct
        res_df = wf.run_schedule(df, idx_df, schedule)
        res_df["max_positions"] = max_pos
        res_df["alloc_pct"] = alloc_pct
        all_rows.append(res_df)

    bt.MAX_POSITIONS, bt.ALLOC_PCT = orig_max_pos, orig_alloc

    full = pd.concat(all_rows, ignore_index=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "max_positions_sweep_full.csv")
    full.to_csv(out_path, index=False)
    print(f"\n[OK] Saved full per-window results to {out_path}")

    agg_rows = []
    for (max_pos, alloc_pct), g in full.groupby(["max_positions", "alloc_pct"]):
        traded = g[g["trades"] > 0]
        if traded.empty:
            agg_rows.append({"max_positions": max_pos, "alloc_pct": alloc_pct, "windows_traded": 0})
            continue
        agg_rows.append({
            "max_positions": max_pos, "alloc_pct": alloc_pct,
            "windows_traded": len(traded),
            "beat_bench": int((traded["alpha_pct"] > 0).sum()),
            "winrate_over_50": int((traded["win_rate"] > 50).sum()),
            "trades_total": int(traded["trades"].sum()),
            "win_rate_mean": round(traded["win_rate"].mean(), 1),
            "win_rate_median": round(traded["win_rate"].median(), 1),
            "profit_mean": round(traded["profit_pct"].mean(), 2),
            "profit_median": round(traded["profit_pct"].median(), 2),
            "alpha_mean": round(traded["alpha_pct"].mean(), 2),
            "alpha_median": round(traded["alpha_pct"].median(), 2),
            "pf_mean": round(traded["profit_factor"].mean(), 2),
            "pf_median": round(traded["profit_factor"].median(), 2),
            "dd_mean": round(traded["max_dd"].mean(), 2),
            "dd_worst": round(traded["max_dd"].min(), 2),
            "conc_mean": round(traded["concentration_pct"].mean(), 1),
            "conc_max": round(traded["concentration_pct"].max(), 1),
        })
    agg = pd.DataFrame(agg_rows)
    print("\n" + "=" * 110)
    print("MAX_POSITIONS SWEEP -- aggregate per (max_positions x alloc_pct) cell")
    print("=" * 110)
    print(agg.to_string(index=False))
    agg_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "max_positions_sweep_agg.csv")
    agg.to_csv(agg_path, index=False)
    print(f"\n[OK] Saved aggregate to {agg_path}")


if __name__ == "__main__":
    main()
