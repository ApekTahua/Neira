"""sweep_spike_sizing.py -- walk-forward sweep for SPIKE_SIZING_MULT (docs/V3_FINDINGS_LOG.md,
"Spike sizing: reduce, don't exclude/delay"). The size-down follow-up to the REJECTED
SPIKE_CONFIRM_GATE (docs/V3_FINDINGS_LOG.md, "Spike confirmation-delay gate ... REJECTED"):
instead of excluding a spike-flagged candidate from candidacy, let the entry through as normal
and reduce its position size only -- see backtest_v4.py's SPIKE_SIZING_ENABLED block comment
(module-level flags + the is_spike tagging site inside simulate_window) for the full mechanics.

Also reports n_spike_admits / avg_spike_cost_basis per window (from a direct simulate_window()
diag=... call per window, same reason sweep_rotation.py duplicates wf.run_schedule()'s loop
instead of routing through it -- that function only returns aggregated metrics, not the
per-admit diag detail this sweep needs to confirm the mechanism actually fired).

Usage:
    python src/sweep_spike_sizing.py
    SWEEP_SPIKE_MULT=0.25,0.5,0.75 python src/sweep_spike_sizing.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V3_BANDAR_SIZING", "0")  # matches the reproducible baseline this log has used since the tick-size-bug entry

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

DEFAULT_GRID = "0.25,0.5,0.75"
GRID = [float(v.strip()) for v in os.environ.get("SWEEP_SPIKE_MULT", DEFAULT_GRID).split(",") if v.strip()]


def run_schedule_with_spike_detail(df, idx_df, schedule):
    """Same per-window metrics as wf.run_schedule(), plus n_spike_admits/avg_spike_cost_basis
    (from a per-window direct simulate_window(diag=...) call, not routed through
    wf.run_schedule() -- see module docstring)."""
    rows = []
    for i, (tr_end, te_start, te_end) in enumerate(schedule, 1):
        print(f"\n{'-'*100}\nWindow {i}/{len(schedule)}\n{'-'*100}", flush=True)
        diag = {}
        metrics, df_trades, df_equity, _regime = bt.simulate_window(
            df, idx_df, tr_end, te_start, te_end, label=f"W{i}", diag=diag)
        if metrics is None:
            rows.append({"window": i, "test_start": te_start, "test_end": te_end, "trades": 0,
                         "n_spike_admits": 0, "avg_spike_cost_basis": float("nan")})
            continue
        top5 = df_trades.groupby("stock_code")["pnl"].sum().sort_values(ascending=False).head(5)
        pos_total = df_trades[df_trades["pnl"] > 0]["pnl"].sum()
        conc_pct = 100 * top5.clip(lower=0).sum() / pos_total if pos_total > 0 else float("nan")
        avg_n_positions = df_equity["n_positions"].mean() if "n_positions" in df_equity.columns else float("nan")
        admitted = [a for d in diag["days"] for a in d["admitted"]]
        spike_admits = [a for a in admitted if a["is_spike"]]
        rows.append({
            "window": i, "test_start": te_start, "test_end": te_end,
            "trades": metrics["total_trades"], "win_rate": metrics["win_rate"],
            "profit_pct": metrics["total_return_pct"], "bench_pct": metrics["bench_ret"],
            "alpha_pct": metrics["total_return_pct"] - metrics["bench_ret"],
            "profit_factor": metrics["profit_factor"], "max_dd": metrics["max_drawdown"],
            "cvar_95": metrics["cvar_95"], "concentration_pct": conc_pct,
            "avg_n_positions": avg_n_positions,
            "n_admits": len(admitted), "n_spike_admits": len(spike_admits),
            "avg_spike_cost_basis": (sum(a["cost_basis"] for a in spike_admits) / len(spike_admits)
                                      if spike_admits else float("nan")),
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

    orig_enabled, orig_mult = bt.SPIKE_SIZING_ENABLED, bt.SPIKE_SIZING_MULT
    all_rows = []

    print(f"\n{'='*100}\n[SWEEP] SPIKE_SIZING_ENABLED=False (baseline)\n{'='*100}", flush=True)
    bt.SPIKE_SIZING_ENABLED = False
    off_df = run_schedule_with_spike_detail(df, idx_df, schedule)
    off_df["spike_sizing_mult"] = "OFF"
    all_rows.append(off_df)

    for mult in GRID:
        label = f"SPIKE_SIZING_ENABLED=True SPIKE_SIZING_MULT={mult}"
        print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}", flush=True)
        bt.SPIKE_SIZING_ENABLED = True
        bt.SPIKE_SIZING_MULT = mult
        res_df = run_schedule_with_spike_detail(df, idx_df, schedule)
        res_df["spike_sizing_mult"] = mult
        all_rows.append(res_df)

    bt.SPIKE_SIZING_ENABLED, bt.SPIKE_SIZING_MULT = orig_enabled, orig_mult

    full = pd.concat(all_rows, ignore_index=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "spike_sizing_sweep_full.csv")
    full.to_csv(out_path, index=False)
    print(f"\n[OK] Saved full per-window results to {out_path}")

    agg_rows = []
    for mult, g in full.groupby("spike_sizing_mult"):
        traded = g[g["trades"] > 0]
        if traded.empty:
            agg_rows.append({"spike_sizing_mult": mult, "windows_traded": 0})
            continue
        agg_rows.append({
            "spike_sizing_mult": mult,
            "windows_traded": len(traded),
            "beat_bench": int((traded["alpha_pct"] > 0).sum()),
            "winrate_over_50": int((traded["win_rate"] > 50).sum()),
            "trades_total": int(traded["trades"].sum()),
            "spike_admits_total": int(traded["n_spike_admits"].sum()),
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
    print("SPIKE_SIZING_MULT SWEEP -- aggregate per value ('OFF' == SPIKE_SIZING_ENABLED=False)")
    print("=" * 110)
    print(agg.to_string(index=False))
    agg_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "spike_sizing_sweep_agg.csv")
    agg.to_csv(agg_path, index=False)
    print(f"\n[OK] Saved aggregate to {agg_path}")


if __name__ == "__main__":
    main()
