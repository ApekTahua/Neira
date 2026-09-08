"""sweep_broker_flow_gate.py -- SCRATCH/RESEARCH ONLY, walk-forward + sensitivity
sweep for V4_BROKER_FLOW_GATE (research candidate, docs/V3_FINDINGS_LOG.md
2026-08-25 entry). Same discipline/structure as sweep_v4_filters.py -- one
subprocess per grid cell (a fresh python process per cell, matching how the
existing sweep scripts in this repo already do it, avoids any risk of stale
module-level state leaking between cells), reusing walk_forward_v4's own
pickle cache so no Supabase re-fetch happens.

Axes:
  V4_BROKER_FLOW_MIN         -- gate threshold on the N-day rolling mean net-flow ratio
  V4_BROKER_FLOW_WINDOW_DAYS -- the rolling window itself (sensitivity axis)

V4_ATR_PRICE_RATIO_MAX is pinned to 0.08 throughout (current live config) so
every cell is apples-to-apples against this project's own reconfirmed baseline
(mean alpha +26.17%, mean PF 1.95, 7/9 beat-bench, 4/9 win>50%, 366 trades).

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/sweep_broker_flow_gate.py
"""

import itertools
import os
import subprocess
import sys


def _axis(env_name: str, default: list) -> list:
    raw = os.environ.get(env_name, "")
    return [v.strip() for v in raw.split(",") if v.strip()] or default


THRESHOLDS = _axis("SWEEP_FLOW_MIN", ["off", "-0.01", "-0.005", "0.0", "0.005", "0.01", "0.02"])
WINDOWS = _axis("SWEEP_FLOW_WINDOW", ["5"])


def main():
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")

    here = os.path.dirname(os.path.abspath(__file__))
    rows = []

    for thr, win in itertools.product(THRESHOLDS, WINDOWS):
        is_off = thr == "off"
        label = "OFF (baseline)" if is_off else f"MIN={thr} WINDOW={win}d"
        print(f"\n{'=' * 100}\n[SWEEP] {label}\n{'=' * 100}", flush=True)
        env = {**os.environ, "V4_ATR_PRICE_RATIO_MAX": "0.08"}
        if is_off:
            env["V4_BROKER_FLOW_GATE"] = "0"
        else:
            env["V4_BROKER_FLOW_GATE"] = "1"
            env["V4_BROKER_FLOW_MIN"] = thr
            env["V4_BROKER_FLOW_WINDOW_DAYS"] = win
        proc = subprocess.run(
            [sys.executable, os.path.join(here, "walk_forward_v4.py")],
            env=env, capture_output=True, text=True,
        )
        sys.stdout.write(proc.stdout[-3000:])
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr[-3000:])
            print(f"[SWEEP] {label} FAILED (exit {proc.returncode}) -- continuing", flush=True)
            continue

        import pandas as pd
        summary_path = os.path.join(os.getcwd(), "walk_forward_v4_summary.csv")
        if not os.path.exists(summary_path):
            print(f"[SWEEP] {label}: no summary csv produced -- skipping", flush=True)
            continue
        wdf = pd.read_csv(summary_path)
        wdf["cell_label"] = label
        wdf["thr"] = thr
        wdf["gate_window_days"] = win
        wdf.to_csv(os.path.join("C:/Users/Apek/AppData/Local/Temp/claude/d--Neira-Neira/"
                                 "6b6e97ab-dc93-41c9-a2c8-2d893a8f029e/scratchpad",
                                 f"broker_flow_full_{thr}_{win}.csv"), index=False)
        traded = wdf[wdf["trades"] > 0]
        if traded.empty:
            rows.append({"label": label, "thr": thr, "gate_window_days": win, "windows_traded": 0})
            continue
        rows.append({
            "label": label, "thr": thr, "gate_window_days": win,
            "windows_traded": len(traded),
            "beat_bench": int((traded["alpha_pct"] > 0).sum()),
            "winrate_over_50": int((traded["win_rate"] > 50).sum()),
            "trades": int(traded["trades"].sum()),
            "win_rate_mean": round(traded["win_rate"].mean(), 1),
            "profit_mean": round(traded["profit_pct"].mean(), 2),
            "profit_median": round(traded["profit_pct"].median(), 2),
            "alpha_mean": round(traded["alpha_pct"].mean(), 2),
            "alpha_median": round(traded["alpha_pct"].median(), 2),
            "pf_mean": round(traded["profit_factor"].mean(), 2),
            "max_dd_mean": round(traded["max_dd"].mean(), 2),
            "max_dd_worst": round(traded["max_dd"].min(), 2),
            # per-window profit_pct, so a single-window-driven result is visible at a glance
            **{f"w{int(r.window)}_profit": round(r.profit_pct, 2) for r in wdf.itertuples()},
            **{f"w{int(r.window)}_alpha": round(r.alpha_pct, 2) for r in wdf.itertuples()},
        })

    import pandas as pd
    res = pd.DataFrame(rows)
    print("\n" + "=" * 110)
    print("BROKER-FLOW GATE SWEEP -- one row per (threshold x window) cell")
    print("=" * 110)
    print(res.to_string(index=False))
    res.to_csv("sweep_broker_flow_gate_summary.csv", index=False)
    print("\n[OK] Saved sweep_broker_flow_gate_summary.csv")


if __name__ == "__main__":
    main()
