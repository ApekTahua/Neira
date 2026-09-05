"""Load-test the beam: the trailing stop carries 92.1% of gross profit across
80 exits and has never been stress-tested.

This is a ROBUSTNESS check, not a parameter search. The nine windows are closed
for promotion (see docs/HOLDOUT_PROTOCOL.md and the 2026-09-05 methodology
audit), so nothing here may be adopted on the strength of these numbers. The
question is only whether the value already in production is standing on solid
ground or on a spike -- and that question is answered by the SHAPE of the
surface, not by which cell is highest.

Two axes:

  1. Trail width, swept finely across THREE partitions (the original nine
     windows, a three-month shift, and an eighteen-window quarterly re-cut).
     One partition is how the 0.10pp BANDAR_SIZING artifact got adopted; a
     value that only looks good on one cut is a property of the cut.

  2. Slippage. `V4_SLIPPAGE` defaults to "0", so every headline figure this
     project has ever reported assumes fills at the exact close or open with
     no spread paid and no market impact. A TRAILING exit fills at
     `close_price` by construction. If the result evaporates once a real cost
     is charged, the strategy is an artifact of that assumption.

Usage:  python loadtest_trail.py            # both axes
        python loadtest_trail.py --trail    # width surface only
        python loadtest_trail.py --slip     # slippage stress only
"""
import os
import sys
from datetime import date

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
os.chdir(SRC)

from dotenv import load_dotenv

load_dotenv(os.path.join(SRC, "..", ".env"))
os.environ.setdefault("V4_TEST_END", "2026-06-30")
# Production config, held fixed while one axis at a time is varied.
os.environ.setdefault("V4_BANDAR_SIZING", "1")
os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402

TRAIL_GRID = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12]
PRODUCTION_TRAIL = 0.08
# base bps / impact bps. (5, 16) is the module default; the rest escalate toward
# what a thin IDX name actually costs to exit in a hurry.
SLIP_GRID = [(0, 0), (5, 16), (10, 30), (20, 50), (35, 80)]


def partitions():
    """The same three cuts the methodology audit used."""
    return {
        "orig": wf.build_schedule(date(2022, 1, 1), bt.TEST_END, test_months=6),
        "shift3mo": wf.build_schedule(date(2022, 4, 1), bt.TEST_END, test_months=6),
        "quarterly": wf.build_schedule(date(2022, 1, 1), bt.TEST_END, test_months=3),
    }


def summarise(res):
    t = res[res["trades"] > 0]
    if t.empty:
        return dict(windows=0, alpha_mean=np.nan, alpha_med=np.nan,
                    worst_dd=np.nan, beat=0, pf=np.nan, wr=np.nan)
    return dict(
        windows=len(t),
        alpha_mean=t["alpha_pct"].mean(),
        alpha_med=t["alpha_pct"].median(),
        worst_dd=t["max_dd"].min(),
        beat=int((t["alpha_pct"] > 0).sum()),
        pf=t["profit_factor"].mean(),
        wr=t["win_rate"].mean(),
    )


def run(df, idx_df, schedule):
    return summarise(wf.run_schedule(df, idx_df, schedule))


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    print("[DATA] loading cached dataset ...")
    df0, idx0 = wf.load_dataset()
    print(f"[DATA] {len(df0):,} rows")
    parts = partitions()
    for k, v in parts.items():
        print(f"[PART] {k}: {len(v)} windows, {v[0][1]} .. {v[-1][2]}")

    if only != "--slip":
        print("\n" + "=" * 104)
        print("AXIS 1 -- TRAIL WIDTH SURFACE  (production = 0.08; shape matters, not the max)")
        print("=" * 104)
        rows = []
        for pname, sched in parts.items():
            for w in TRAIL_GRID:
                os.environ["V4_TRAILING_PCT"] = str(w)
                bt.cfg.TRAILING_PCT = w
                s = run(df0.copy(), idx0.copy(), sched)
                s.update(partition=pname, trail=w)
                rows.append(s)
                print(f"  {pname:>10} trail={w:.2f}  alpha {s['alpha_mean']:+7.2f}%  "
                      f"med {s['alpha_med']:+7.2f}%  worstDD {s['worst_dd']:7.2f}%  "
                      f"beat {s['beat']}/{s['windows']}  PF {s['pf']:.2f}")
        t = pd.DataFrame(rows)
        t.to_csv(os.path.join(SRC, "loadtest_trail_surface.csv"), index=False)

        print("\n--- is 0.08 a plateau or a spike? ---")
        for pname in parts:
            sub = t[t.partition == pname].sort_values("trail")
            best = sub.loc[sub.alpha_mean.idxmax()]
            prod = sub[sub.trail == PRODUCTION_TRAIL].iloc[0]
            nb = sub[(sub.trail - PRODUCTION_TRAIL).abs().between(0.009, 0.011)]
            drop = prod.alpha_mean - nb.alpha_mean.min() if len(nb) else float("nan")
            print(f"  {pname:>10}: best trail={best.trail:.2f} ({best.alpha_mean:+.2f}%), "
                  f"production 0.08 ({prod.alpha_mean:+.2f}%), "
                  f"worst immediate neighbour costs {drop:+.2f}pp")

    if only != "--trail":
        print("\n" + "=" * 104)
        print("AXIS 2 -- SLIPPAGE STRESS  (V4_SLIPPAGE defaults OFF: every reported")
        print("          figure so far assumes a perfect fill at the close/open)")
        print("=" * 104)
        os.environ["V4_TRAILING_PCT"] = str(PRODUCTION_TRAIL)
        bt.cfg.TRAILING_PCT = PRODUCTION_TRAIL
        rows = []
        for base, impact in SLIP_GRID:
            on = not (base == 0 and impact == 0)
            os.environ["V4_SLIPPAGE"] = "1" if on else "0"
            os.environ["V4_SLIPPAGE_BASE_BPS"] = str(base)
            os.environ["V4_SLIPPAGE_IMPACT_BPS"] = str(impact)
            bt.SLIPPAGE_ENABLED = on
            bt.SLIPPAGE_BASE_BPS = float(base)
            bt.SLIPPAGE_IMPACT_BPS = float(impact)
            for pname, sched in parts.items():
                s = run(df0.copy(), idx0.copy(), sched)
                s.update(partition=pname, base_bps=base, impact_bps=impact)
                rows.append(s)
                tag = "OFF (as reported)" if not on else f"{base}bps + {impact}bps impact"
                print(f"  {pname:>10} {tag:<24} alpha {s['alpha_mean']:+7.2f}%  "
                      f"worstDD {s['worst_dd']:7.2f}%  beat {s['beat']}/{s['windows']}  "
                      f"PF {s['pf']:.2f}")
        sl = pd.DataFrame(rows)
        sl.to_csv(os.path.join(SRC, "loadtest_slippage.csv"), index=False)

        print("\n--- what does a realistic cost do to the headline? ---")
        for pname in parts:
            sub = sl[sl.partition == pname]
            off = sub[(sub.base_bps == 0)].iloc[0]
            for b, i in SLIP_GRID[1:]:
                r = sub[(sub.base_bps == b) & (sub.impact_bps == i)].iloc[0]
                print(f"  {pname:>10} {b:>2}/{i:<2}bps: alpha {off.alpha_mean:+7.2f}% -> "
                      f"{r.alpha_mean:+7.2f}%  ({r.alpha_mean - off.alpha_mean:+.2f}pp)")

    print("\n[DONE] Nothing here may be promoted -- the nine windows are closed. "
          "These are robustness readings only.")


if __name__ == "__main__":
    main()
