"""sweep_vol_band_mult.py -- VOL_BAND_MULT (regime hysteresis band width)
walk-forward re-sweep, full 9-window harness (backlog item: the original
sweep in docs/V3_FINDINGS_LOG.md only covered 2 windows, before Window 3
existed and before REGIME_CONFIRM_DAYS/TREND_STRENGTH_MIN/pyramiding/
liquidity-sizing were layered on top).

Same "plateau, not peak" discipline as sweep_v4_filters.py / the earlier
hysteresis-band walk-back: one lucky value in a noisy landscape is not a
validated optimum. Reports per-window profit/win/PF/DD/trades/concentration,
not just the aggregate -- concentration is what caught the fixed-%
design's silent failure mode.

Uses in-process module-attribute mutation (same trick feature_test_harness.py
uses for ON/OFF flags, generalized to a numeric grid + a second axis) instead
of one subprocess per cell (sweep_v4_filters.py's pattern) -- avoids
re-unpickling the ~670MB cached dataset per cell, which the subprocess
approach would pay for on every single grid point.

Axes:
  VOL_BAND_MULT       -- SWEEP_VOL_MULT env, comma list, default the primary grid
  REGIME_CONFIRM_DAYS -- SWEEP_CONFIRM_DAYS env, comma list, default just [3] (current
                         default, i.e. no second axis) unless explicitly overridden

Usage:
    python src/sweep_vol_band_mult.py
    SWEEP_VOL_MULT=1.0,2.0,3.0 SWEEP_CONFIRM_DAYS=2,3,5 python src/sweep_vol_band_mult.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

import walk_forward_v4 as wf

bt = wf.bt


def _axis(env_name: str, default: list, cast) -> list:
    raw = os.environ.get(env_name, "")
    return [cast(v.strip()) for v in raw.split(",") if v.strip()] or default


VOL_MULTS = _axis("SWEEP_VOL_MULT", [1.0, 1.5, 2.0, 2.5, 3.0], float)
CONFIRM_DAYS = _axis("SWEEP_CONFIRM_DAYS", [3], int)


def main():
    supabase = None
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if url and key:
        from supabase import create_client
        supabase = create_client(url, key)

    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset(supabase)

    all_rows = []
    for mult in VOL_MULTS:
        for confirm in CONFIRM_DAYS:
            label = f"VOL_BAND_MULT={mult} REGIME_CONFIRM_DAYS={confirm}"
            print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}", flush=True)
            bt.VOL_BAND_MULT = mult
            bt.REGIME_CONFIRM_DAYS = confirm
            res_df = wf.run_schedule(df, idx_df, schedule)
            res_df["vol_band_mult"] = mult
            res_df["regime_confirm_days"] = confirm
            all_rows.append(res_df)

    # restore defaults regardless of what was swept last
    bt.VOL_BAND_MULT = 2.0
    bt.REGIME_CONFIRM_DAYS = 3

    full = pd.concat(all_rows, ignore_index=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "vol_band_mult_sweep_full.csv")
    full.to_csv(out_path, index=False)
    print(f"\n[OK] Saved full per-window results to {out_path}")

    # aggregate table, same shape as every other sweep in this codebase
    agg_rows = []
    for (mult, confirm), g in full.groupby(["vol_band_mult", "regime_confirm_days"]):
        traded = g[g["trades"] > 0]
        if traded.empty:
            agg_rows.append({"vol_band_mult": mult, "regime_confirm_days": confirm, "windows_traded": 0})
            continue
        agg_rows.append({
            "vol_band_mult": mult, "regime_confirm_days": confirm,
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
    print("VOL_BAND_MULT SWEEP -- aggregate per (vol_band_mult x regime_confirm_days) cell")
    print("=" * 110)
    print(agg.to_string(index=False))
    agg_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "vol_band_mult_sweep_agg.csv")
    agg.to_csv(agg_path, index=False)
    print(f"\n[OK] Saved aggregate to {agg_path}")


if __name__ == "__main__":
    main()
