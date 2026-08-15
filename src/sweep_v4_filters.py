"""sweep_v4_filters.py -- picks the V3.1 entry-filter settings by sweeping
them through the full walk-forward, instead of eyeballing one number.

Why a sweep and not a single pick: the hysteresis-band episode in
docs/V3_FINDINGS_LOG.md is the cautionary tale. A 2% band looked excellent
at exactly 2%, and the surrounding sweep then showed window 1 swinging
61%-501% profit across nearby values -- the "validated optimum" was one
lucky point on a noisy surface. A parameter is only trustworthy if its
NEIGHBOURS behave too. Same standard applies here.

Three knobs, run as a grid:
  V3_ATR_PRICE_RATIO_MAX -- signal-day volatility ceiling (live run: 0.10;
      DOOH, which took a -13.6% stop, sat at 9.1%)
  V3_ARA_FILTER          -- drop candidates locked at the auto-reject
      ceiling on the signal day (BAJA, which then suspended and could
      never fill at all)
  V3_ARB_EXIT_REALISM    -- refuse to book an exit on an auto-reject-FLOOR
      bar, where there is no bid to sell into. Expect this one to make the
      numbers WORSE and truer; it removes a fill the backtest was granting
      itself for free on exactly the days that hurt in real life.

Default axes sweep ATR alone (both auto-reject knobs off) so the ceiling is
read against the live baseline. Phase 2 turns the filters on at whichever
ATR plateau phase 1 finds -- see the axis env vars below.

Reuses walk_forward_v4's pickle cache, so the expensive full-history fetch
happens once for the whole grid rather than once per cell.

Read the output as: prefer a setting whose neighbours are also fine over
one isolated spike. Report the plateau, not the peak.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/sweep_v4_filters.py
"""

import itertools
import os
import subprocess
import sys

# Axes are env-overridable so phase 2 (auto-reject filters, once the ATR
# plateau is known) doesn't have to re-run the whole grid:
#   SWEEP_ATR=0.08,0.07  SWEEP_ARA=0,1  SWEEP_ARB=0,1  python src/sweep_v4_filters.py
def _axis(env_name: str, default: list) -> list:
    raw = os.environ.get(env_name, "")
    return [v.strip() for v in raw.split(",") if v.strip()] or default


ATR_CEILINGS = _axis("SWEEP_ATR", ["0.10", "0.09", "0.08", "0.07", "0.06", "0.05"])
ARA_SETTINGS = _axis("SWEEP_ARA", ["0"])
ARB_SETTINGS = _axis("SWEEP_ARB", ["0"])


def main():
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")

    here = os.path.dirname(os.path.abspath(__file__))
    rows = []

    for atr, ara, arb in itertools.product(ATR_CEILINGS, ARA_SETTINGS, ARB_SETTINGS):
        label = f"ATR<={atr} ARA={'on' if ara == '1' else 'off'} ARB={'on' if arb == '1' else 'off'}"
        print(f"\n{'=' * 100}\n[SWEEP] {label}\n{'=' * 100}", flush=True)
        env = {
            **os.environ, "V3_ATR_PRICE_RATIO_MAX": atr,
            "V3_ARA_FILTER": ara, "V3_ARB_EXIT_REALISM": arb,
        }
        proc = subprocess.run(
            [sys.executable, os.path.join(here, "walk_forward_v4.py")],
            env=env, capture_output=True, text=True,
        )
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            print(f"[SWEEP] {label} FAILED (exit {proc.returncode}) -- continuing", flush=True)
            continue

        # walk_forward_v4.py rewrites this CSV each run; read it before the
        # next cell overwrites it.
        import pandas as pd
        summary_path = os.path.join(os.getcwd(), "walk_forward_v4_summary.csv")
        if not os.path.exists(summary_path):
            print(f"[SWEEP] {label}: no summary csv produced -- skipping", flush=True)
            continue
        df = pd.read_csv(summary_path)
        traded = df[df["trades"] > 0]
        if traded.empty:
            rows.append({"atr_max": atr, "ara": ara, "arb": arb, "windows_traded": 0})
            continue
        rows.append({
            "atr_max": atr, "ara": ara, "arb": arb,
            "windows_traded": len(traded),
            "beat_bench": int((traded["alpha_pct"] > 0).sum()),
            "winrate_over_50": int((traded["win_rate"] > 50).sum()),
            "trades": int(traded["trades"].sum()),
            "win_rate_mean": round(traded["win_rate"].mean(), 1),
            "profit_mean": round(traded["profit_pct"].mean(), 2),
            "profit_median": round(traded["profit_pct"].median(), 2),
            "profit_worst": round(traded["profit_pct"].min(), 2),
            "alpha_mean": round(traded["alpha_pct"].mean(), 2),
            "pf_median": round(traded["profit_factor"].median(), 2),
            "max_dd_worst": round(traded["max_dd"].min(), 2),
        })

    import pandas as pd
    res = pd.DataFrame(rows)
    print("\n" + "=" * 110)
    print("V3.1 FILTER SWEEP -- one row per (ATR ceiling x ARA x ARB) cell")
    print("=" * 110)
    print(res.to_string(index=False))
    print("\nBaseline is the live frozen config: atr_max=0.10, ara=0, arb=0.")
    print("Pick a PLATEAU (neighbouring cells also healthy), not the single best cell.")
    res.to_csv("sweep_v4_filters_summary.csv", index=False)
    print("\n[OK] Saved sweep_v4_filters_summary.csv")


if __name__ == "__main__":
    main()
