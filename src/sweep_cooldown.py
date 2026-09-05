"""Does the ten-session re-entry ban after a stop-out cost us the tail?

Measured 2026-09-05: of the 120 positions that had a run of more than +25%
available in the 60 sessions after entry, **49 were stopped out at a median
-8.75% on names that went on to offer a median +50%**. That is 41% of the tail
draws, and the tail is where this system's only significant edge lives.

`cfg.COOLDOWN_DAYS = 10` blocks re-entry into a name for ten trading days after
it stops us out. Nobody has ever swept it. Against those 49 positions, ten
sessions of enforced absence is a specific and possibly expensive choice.

This is NOT a proposal to remove the stop. The capture measurement says nothing
about which stop-out would later run, "available" ignores path, and the stop is
what bounds a drawdown that already reaches -30% on a re-cut partition. The
question here is narrower: after the stop has done its job, how long should we
stay out?

Run on the closed nine windows and their two re-cuts, so nothing here may be
promoted (docs/HOLDOUT_PROTOCOL.md Rule 1). It can rule the idea out.

Usage:  python sweep_cooldown.py
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
# Production config held fixed while the one axis varies.
os.environ.setdefault("V4_BANDAR_SIZING", "1")
os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from loadtest_trail import partitions, summarise  # noqa: E402

GRID = [0, 3, 5, 10, 15]
PRODUCTION = 10


def main():
    print("[DATA] loading cached dataset ...")
    df0, idx0 = wf.load_dataset()
    print(f"[DATA] {len(df0):,} rows")
    parts = partitions()

    rows = []
    for cd in GRID:
        bt.cfg.COOLDOWN_DAYS = cd
        for pname, sched in parts.items():
            s = summarise(wf.run_schedule(df0.copy(), idx0.copy(), sched))
            s.update(partition=pname, cooldown=cd)
            rows.append(s)
            tag = f"cooldown={cd}" + (" (production)" if cd == PRODUCTION else "")
            print(f"  {pname:>10} {tag:<24} alpha {s['alpha_mean']:+7.2f}%  "
                  f"med {s['alpha_med']:+7.2f}%  worstDD {s['worst_dd']:7.2f}%  "
                  f"beat {s['beat']}/{s['windows']}  PF {s['pf']:.2f}")
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(SRC, "sweep_cooldown.csv"), index=False)

    print("\n--- against production (10), on ALL THREE cuts ---")
    for cd in GRID:
        if cd == PRODUCTION:
            continue
        line, wins, dd_ok = [], 0, 0
        for pname in parts:
            a = t[(t.partition == pname) & (t.cooldown == cd)].iloc[0]
            b = t[(t.partition == pname) & (t.cooldown == PRODUCTION)].iloc[0]
            da = a.alpha_mean - b.alpha_mean
            dd = a.worst_dd - b.worst_dd
            wins += da > 0
            dd_ok += dd >= 0          # worst_dd is negative; larger is shallower
            line.append(f"{pname} {da:+6.2f}pp/DD{dd:+6.2f}pp")
        verdict = "PASSES on all three" if wins == 3 and dd_ok == 3 else "fails"
        print(f"  cooldown={cd:<3} {'  '.join(line)}   {verdict}")

    print("\n[DONE] Robustness reading only -- the nine windows are closed for "
          "promotion. A cell that passes here is a candidate to watch forward, "
          "not a change to ship.")


if __name__ == "__main__":
    main()
