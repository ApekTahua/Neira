"""sweep_rotation.py -- walk-forward sweep for ROTATION_MARGIN_MULT, the third attempt at
the scarce-MAX_POSITIONS-slot fragility (docs/V3_FINDINGS_LOG.md, "cross-day position
rotation" entry), after widening the cap and a bounded backlog queue were both rejected.
Structurally different from both: instead of admitting MORE candidates (concurrent widening
or temporal reordering), this can force-exit an already-open, rotation-eligible position
early to free a slot for a materially stronger new candidate -- see backtest_v4.py's
ROTATION_ENABLED block comment (module-level flags + inside simulate_window, where it's
consumed) for the full eligibility/mechanics writeup.

ROTATION_MARGIN_MULT=999 (flag ON, an unreachable margin) is included as a boundary/sanity
cell, same discipline sweep_backlog_queue.py's own BACKLOG_EXPIRY_DAYS=0 cell used: no
rotation can ever clear a 999x-score_p90 margin, so this cell should reproduce the flag-OFF
baseline byte-for-byte.

Reports the same per-window/aggregate shape every sweep this session has used, PLUS
n_rotations (from a per-window direct simulate_window() call, not routed through
walk_forward_v4.run_schedule() -- that function returns aggregated metrics only, not the raw
df_trades needed to count ROTATE exits; duplicating ~15 lines of its loop here was judged
simpler and lower-blast-radius than adding a new column to a function four other sweep
scripts already depend on for byte-identical behavior).

Usage:
    python src/sweep_rotation.py
    SWEEP_ROTATION_MARGIN=0.5,1.0,2.0,3.0,999 python src/sweep_rotation.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V3_BANDAR_SIZING", "0")  # matches the reproducible baseline this log has used since the tick-size-bug entry

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

DEFAULT_GRID = "0.5,1.0,2.0,3.0,999"
GRID = [float(v.strip()) for v in os.environ.get("SWEEP_ROTATION_MARGIN", DEFAULT_GRID).split(",") if v.strip()]


def run_schedule_with_rotation_count(df, idx_df, schedule):
    """Same per-window metrics as wf.run_schedule(), plus n_rotations (count of
    exit_reason=='ROTATE' trades) -- needs the raw df_trades wf.run_schedule() doesn't
    return, so this calls bt.simulate_window() directly per window instead."""
    rows = []
    for i, (tr_end, te_start, te_end) in enumerate(schedule, 1):
        print(f"\n{'-'*100}\nWindow {i}/{len(schedule)}\n{'-'*100}", flush=True)
        metrics, df_trades, df_equity, _regime = bt.simulate_window(df, idx_df, tr_end, te_start, te_end, label=f"W{i}")
        if metrics is None:
            rows.append({"window": i, "test_start": te_start, "test_end": te_end, "trades": 0, "n_rotations": 0})
            continue
        top5 = df_trades.groupby("stock_code")["pnl"].sum().sort_values(ascending=False).head(5)
        pos_total = df_trades[df_trades["pnl"] > 0]["pnl"].sum()
        conc_pct = 100 * top5.clip(lower=0).sum() / pos_total if pos_total > 0 else float("nan")
        avg_n_positions = df_equity["n_positions"].mean() if "n_positions" in df_equity.columns else float("nan")
        n_rotations = int((df_trades["exit_reason"] == "ROTATE").sum())
        rows.append({
            "window": i, "test_start": te_start, "test_end": te_end,
            "trades": metrics["total_trades"], "win_rate": metrics["win_rate"],
            "profit_pct": metrics["total_return_pct"], "bench_pct": metrics["bench_ret"],
            "alpha_pct": metrics["total_return_pct"] - metrics["bench_ret"],
            "profit_factor": metrics["profit_factor"], "max_dd": metrics["max_drawdown"],
            "cvar_95": metrics["cvar_95"], "concentration_pct": conc_pct,
            "avg_n_positions": avg_n_positions, "n_rotations": n_rotations,
        })
    return pd.DataFrame(rows)


def main():
    supabase = None
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if url and key:
        from supabase import create_client
        supabase = create_client(url, key)

    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset(supabase)

    orig_enabled, orig_margin = bt.ROTATION_ENABLED, bt.ROTATION_MARGIN_MULT
    all_rows = []

    print(f"\n{'='*100}\n[SWEEP] ROTATION_ENABLED=False (baseline)\n{'='*100}", flush=True)
    bt.ROTATION_ENABLED = False
    off_df = run_schedule_with_rotation_count(df, idx_df, schedule)
    off_df["rotation_margin_mult"] = "OFF"
    all_rows.append(off_df)

    for margin in GRID:
        label = f"ROTATION_ENABLED=True ROTATION_MARGIN_MULT={margin}"
        print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}", flush=True)
        bt.ROTATION_ENABLED = True
        bt.ROTATION_MARGIN_MULT = margin
        res_df = run_schedule_with_rotation_count(df, idx_df, schedule)
        res_df["rotation_margin_mult"] = margin
        all_rows.append(res_df)

    bt.ROTATION_ENABLED, bt.ROTATION_MARGIN_MULT = orig_enabled, orig_margin

    full = pd.concat(all_rows, ignore_index=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "rotation_sweep_full.csv")
    full.to_csv(out_path, index=False)
    print(f"\n[OK] Saved full per-window results to {out_path}")

    agg_rows = []
    for margin, g in full.groupby("rotation_margin_mult"):
        traded = g[g["trades"] > 0]
        if traded.empty:
            agg_rows.append({"rotation_margin_mult": margin, "windows_traded": 0})
            continue
        agg_rows.append({
            "rotation_margin_mult": margin,
            "windows_traded": len(traded),
            "beat_bench": int((traded["alpha_pct"] > 0).sum()),
            "winrate_over_50": int((traded["win_rate"] > 50).sum()),
            "trades_total": int(traded["trades"].sum()),
            "rotations_total": int(traded["n_rotations"].sum()),
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
            "avg_n_positions_mean": round(traded["avg_n_positions"].mean(), 2),
            "avg_n_positions_max": round(traded["avg_n_positions"].max(), 2),
        })
    agg = pd.DataFrame(agg_rows)
    print("\n" + "=" * 110)
    print("ROTATION_MARGIN_MULT SWEEP -- aggregate per value ('OFF' == ROTATION_ENABLED=False)")
    print("=" * 110)
    print(agg.to_string(index=False))
    agg_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "rotation_sweep_agg.csv")
    agg.to_csv(agg_path, index=False)
    print(f"\n[OK] Saved aggregate to {agg_path}")


if __name__ == "__main__":
    main()
