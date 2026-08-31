"""sweep_tranche_entry.py -- walk-forward sweep for TRANCHE_ENTRY_ENABLED (docs/
V3_FINDINGS_LOG.md, "tranche/split-fill entry" entry). Real-trader critique this answers,
a STRUCTURALLY DIFFERENT design from PULLBACK_FILL_ENABLED (rejected -- see that entry):
buy a BASE tranche immediately at the area-top price (guaranteed, same day/price as the
baseline, just smaller), then only ADD a second tranche -- averaging cost basis down -- if
price dips further within a short window. Never skips a trade (unlike pullback-fill).

Grid: TRANCHE_BASE_PCT in {0.5, 0.6, 0.7} x TRANCHE_ADD_LOW_PCT in {0.01, 0.02, 0.03}
(1%/2%/3% below the base fill price), TRANCHE_ADD_EXPIRY_SESSIONS fixed at 2.

Baseline = the CURRENT LIVE V4_PAPER config (V4_BANDAR_SIZING default-on,
V4_ATR_PRICE_RATIO_MAX=0.08 -- see paper_signal_scan_v4_trigger.yml), same convention
sweep_pullback_fill.py already uses. Also runs the OFF baseline and the single best ON
cell with V4_BANDAR_SIZING=0, to check whether any effect found is specific to (or
independent of) that live default sizing flag.

Usage:
    python src/sweep_tranche_entry.py
    SWEEP_BASE_PCT=0.5,0.6 SWEEP_ADD_PCT=0.02 python src/sweep_tranche_entry.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")  # V4_PAPER's actual live frozen config

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

BASE_GRID = [float(v.strip()) for v in os.environ.get("SWEEP_BASE_PCT", "0.5,0.6,0.7").split(",") if v.strip()]
ADD_GRID = [float(v.strip()) for v in os.environ.get("SWEEP_ADD_PCT", "0.01,0.02,0.03").split(",") if v.strip()]


def _run_cell(df, idx_df, schedule, base_pct, add_pct, bandar_on=True):
    bt.TRANCHE_ENTRY_ENABLED = True
    bt.TRANCHE_BASE_PCT = base_pct
    bt.TRANCHE_ADD_LOW_PCT = add_pct
    bt.TRANCHE_ADD_EXPIRY_SESSIONS = 2
    bt.BANDAR_SIZING_ENABLED = bandar_on
    bt.TRANCHE_FILL_LOG.clear()
    res_df = wf.run_schedule(df, idx_df, schedule)
    adds = list(bt.TRANCHE_FILL_LOG)
    return res_df, adds


def _agg_row(label, g):
    traded = g[g["trades"] > 0]
    if traded.empty:
        return {"config": label, "windows_traded": 0}
    return {
        "config": label,
        "windows_traded": len(traded),
        "beat_bench": int((traded["alpha_pct"] > 0).sum()),
        "winrate_over_50": int((traded["win_rate"] > 50).sum()),
        "trades_total": int(traded["trades"].sum()),
        "win_rate_mean": round(traded["win_rate"].mean(), 1),
        "profit_mean": round(traded["profit_pct"].mean(), 2),
        "alpha_mean": round(traded["alpha_pct"].mean(), 2),
        "alpha_median": round(traded["alpha_pct"].median(), 2),
        "pf_mean": round(traded["profit_factor"].mean(), 2),
        "dd_mean": round(traded["max_dd"].mean(), 2),
        "dd_worst": round(traded["max_dd"].min(), 2),
        "avg_n_positions_mean": round(traded["avg_n_positions"].mean(), 2),
    }


def main():
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset()

    orig = (bt.TRANCHE_ENTRY_ENABLED, bt.TRANCHE_BASE_PCT, bt.TRANCHE_ADD_LOW_PCT,
            bt.TRANCHE_ADD_EXPIRY_SESSIONS, bt.BANDAR_SIZING_ENABLED)

    all_rows, agg_rows, fill_quality_rows = [], [], []

    # ---- (1) confirm inert baseline (flag off, BANDAR on -- live default) ----
    print(f"\n{'='*100}\n[SWEEP] TRANCHE_ENTRY_ENABLED=False (baseline, live V4_PAPER config, BANDAR on)\n{'='*100}", flush=True)
    bt.TRANCHE_ENTRY_ENABLED = False
    bt.BANDAR_SIZING_ENABLED = True
    off_df = wf.run_schedule(df, idx_df, schedule)
    off_df["config"] = "OFF_bandar_on"
    all_rows.append(off_df)
    agg_rows.append(_agg_row("OFF_bandar_on", off_df))

    # ---- (2) full grid, BANDAR on (live default) ----
    for base_pct in BASE_GRID:
        for add_pct in ADD_GRID:
            label = f"base={base_pct} add={add_pct} bandar=on"
            print(f"\n{'='*100}\n[SWEEP] TRANCHE_ENTRY_ENABLED=True {label}\n{'='*100}", flush=True)
            res_df, adds = _run_cell(df, idx_df, schedule, base_pct, add_pct, bandar_on=True)
            res_df["config"] = label
            all_rows.append(res_df)
            agg_rows.append(_agg_row(label, res_df))

            if adds:
                improvements = [(a["base_fill_price"] - a["final_avg_price"]) / a["base_fill_price"] for a in adds]
                fill_quality_rows.append({
                    "base_pct": base_pct, "add_pct": add_pct, "bandar": "on",
                    "n_second_tranche_fills": len(adds),
                    "avg_fill_price_improvement_pct": 100 * sum(improvements) / len(improvements),
                })
            else:
                fill_quality_rows.append({"base_pct": base_pct, "add_pct": add_pct, "bandar": "on",
                                           "n_second_tranche_fills": 0, "avg_fill_price_improvement_pct": float("nan")})

    full = pd.concat(all_rows, ignore_index=True)
    agg = pd.DataFrame(agg_rows)
    print("\n" + "=" * 110)
    print("TRANCHE_ENTRY sweep -- aggregate per config, BANDAR_SIZING=on (live default)")
    print("=" * 110)
    print(agg.to_string(index=False))

    # ---- (3) pick the best ON cell by mean alpha (bandar on), re-run it + baseline with BANDAR off ----
    on_rows = agg[agg["config"] != "OFF_bandar_on"].dropna(subset=["alpha_mean"])
    if not on_rows.empty:
        best_label = on_rows.loc[on_rows["alpha_mean"].idxmax(), "config"]
        best_base, best_add = [float(x.split("=")[1]) for x in best_label.replace(" bandar=on", "").split(" ")]
        print(f"\n[SWEEP] Best ON cell by mean alpha (BANDAR on): {best_label} -- re-running with BANDAR_SIZING off ...")

        print(f"\n{'='*100}\n[SWEEP] TRANCHE_ENTRY_ENABLED=False (baseline, BANDAR off)\n{'='*100}", flush=True)
        bt.TRANCHE_ENTRY_ENABLED = False
        bt.BANDAR_SIZING_ENABLED = False
        off_bandar_off_df = wf.run_schedule(df, idx_df, schedule)
        off_bandar_off_df["config"] = "OFF_bandar_off"
        all_rows.append(off_bandar_off_df)
        agg_rows.append(_agg_row("OFF_bandar_off", off_bandar_off_df))

        label_off = f"base={best_base} add={best_add} bandar=off"
        print(f"\n{'='*100}\n[SWEEP] TRANCHE_ENTRY_ENABLED=True {label_off}\n{'='*100}", flush=True)
        res_df, adds = _run_cell(df, idx_df, schedule, best_base, best_add, bandar_on=False)
        res_df["config"] = label_off
        all_rows.append(res_df)
        agg_rows.append(_agg_row(label_off, res_df))
        if adds:
            improvements = [(a["base_fill_price"] - a["final_avg_price"]) / a["base_fill_price"] for a in adds]
            fill_quality_rows.append({
                "base_pct": best_base, "add_pct": best_add, "bandar": "off",
                "n_second_tranche_fills": len(adds),
                "avg_fill_price_improvement_pct": 100 * sum(improvements) / len(improvements),
            })

    bt.TRANCHE_ENTRY_ENABLED, bt.TRANCHE_BASE_PCT, bt.TRANCHE_ADD_LOW_PCT, \
        bt.TRANCHE_ADD_EXPIRY_SESSIONS, bt.BANDAR_SIZING_ENABLED = orig

    full = pd.concat(all_rows, ignore_index=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "tranche_entry_sweep_full.csv")
    full.to_csv(out_path, index=False)
    print(f"\n[OK] Saved full per-window results to {out_path}")

    agg = pd.DataFrame(agg_rows)
    agg_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "tranche_entry_sweep_agg.csv")
    agg.to_csv(agg_path, index=False)
    print("\n" + "=" * 110)
    print("TRANCHE_ENTRY sweep -- FULL aggregate (incl. BANDAR-off checks)")
    print("=" * 110)
    print(agg.to_string(index=False))
    print(f"\n[OK] Saved aggregate to {agg_path}")

    fq = pd.DataFrame(fill_quality_rows)
    fq_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "tranche_entry_fill_quality.csv")
    fq.to_csv(fq_path, index=False)
    print("\n" + "=" * 110)
    print("FILL-PRICE IMPROVEMENT diagnostic (pooled across all 9 windows, per grid cell) -- "
          "positions that got a genuine second tranche only")
    print("=" * 110)
    print(fq.to_string(index=False))
    print(f"\n[OK] Saved fill-quality diagnostic to {fq_path}")


if __name__ == "__main__":
    main()
