"""Map the stop's trade-off. Publish the whole curve, pick nothing.

The leak is located: 49 of the 120 positions that had a >+25% run available were
stopped out first at a median -8.75%, on names that went on to offer a median
+50%. Three ideas for recovering that have already died -- the cooldown barely
binds, a bandar-aware stop has nothing to work with, and the coiling premise
failed in both directions.

What has never been looked at is the stop's own width. `V4_SL_MULT` is 1.5 ATR,
a number that was chosen rather than swept, exactly like the trailing 0.08 was
until yesterday.

This is deliberately NOT a search for the best cell. Widening a stop must recover
tail and must cost drawdown; the only open question is the exchange rate. So the
output is the whole frontier, every width reported, including no stop at all --
which exists to show where the trade-off ends, not to be adopted.

Pre-registered before running. Closed windows, Rule 1: nothing here may be
promoted. Slippage ON, Rule 4.

Usage:  python sweep_stop_frontier.py
"""
import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
os.chdir(SRC)

from dotenv import load_dotenv

load_dotenv(os.path.join(SRC, "..", ".env"))
os.environ.setdefault("V4_TEST_END", "2026-06-30")
os.environ.setdefault("V4_BANDAR_SIZING", "1")
os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from loadtest_trail import partitions, summarise  # noqa: E402

# 99.0 is "no stop in practice" -- an ATR multiple no position can reach before
# the trailing stop or the time cap takes it.
GRID = [float(x) for x in os.environ.get(
    "V4_SL_GRID", "1.0,1.5,2.0,2.5,3.0,4.0,99.0").split(",")]
PRODUCTION = 1.5


def main():
    print("[DATA] cached dataset ...")
    df0, idx0 = wf.load_dataset()
    os.environ["V4_SLIPPAGE"] = "1"
    bt.SLIPPAGE_ENABLED = True
    parts = partitions()

    rows = []
    for m in GRID:
        bt.SL_MULT = m
        for pname, sched in parts.items():
            s = summarise(wf.run_schedule(df0.copy(), idx0.copy(), sched))
            s.update(partition=pname, sl_mult=m)
            rows.append(s)
            tag = ("no stop" if m >= 99 else f"{m:g} ATR") + (
                "  (production)" if m == PRODUCTION else "")
            print(f"  {pname:>10} {tag:<22} alpha {s['alpha_mean']:+7.2f}%  "
                  f"med {s['alpha_med']:+7.2f}%  worstDD {s['worst_dd']:7.2f}%  "
                  f"beat {s['beat']}/{s['windows']}  PF {s['pf']:.2f}  "
                  f"trades {s['trades']:>4}  avgPos {s['avg_positions']:.2f}")
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(SRC, "sweep_stop_frontier.csv"), index=False)

    # Every cell below is a delta against PRODUCTION, so a grid that does not
    # contain production has nothing to subtract. Say so and fall back to
    # absolute levels: running a partial grid to extend one end of the curve
    # (V4_SL_GRID="3.0,6.0,10.0", say) is normal, and crashing here threw away
    # nine windows of finished work the first time it happened.
    baseline = PRODUCTION in GRID
    print("\n--- THE FRONTIER: what each widening buys and what it costs ---")
    if not baseline:
        print(f"    (production {PRODUCTION:g} ATR is not in this grid -- "
              f"showing absolute alpha and drawdown, not deltas)")
    print(f"{'width':>10}" + "".join(f"{p:>26}" for p in parts))
    for m in GRID:
        cells = []
        for pname in parts:
            sub = t[(t.partition == pname) & (t.sl_mult == m)]
            if sub.empty:
                cells.append("--")
                continue
            a = sub.iloc[0]
            if baseline:
                b = t[(t.partition == pname) & (t.sl_mult == PRODUCTION)].iloc[0]
                cells.append(f"{a.alpha_mean - b.alpha_mean:+8.2f}pp /DD{a.worst_dd - b.worst_dd:+7.2f}")
            else:
                cells.append(f"{a.alpha_mean:+8.2f}%  /DD{a.worst_dd:+7.2f}")
        lab = "no stop" if m >= 99 else f"{m:g} ATR"
        print(f"{lab:>10}" + "".join(f"{c:>26}" for c in cells))

    print("\nRead this as a curve, not a leaderboard. A cell that improves BOTH")
    print("alpha and drawdown on all three cuts is more likely a measurement error")
    print("than a free lunch -- check it before believing it.")


if __name__ == "__main__":
    main()
