"""Does WHERE a stock sits in its own 12-month range belong in the ranking?

Yartseva (2025), "The Alchemy of Multibagger Stocks" (CAFE Working Paper 33),
studies 464 US stocks that rose tenfold between 2009 and 2024. Its most robust
technical result is that `price_range` -- (price - 12m low) / (12m high - 12m
low) -- carries a negative, strongly significant coefficient in all seven
specifications (-0.70 to -0.92): the closer to the 12-month high at purchase,
the lower the next year's return. Three- and six-month momentum are negative
too; only one-month momentum is positive, and only in one model of seven.

Our signals sit at a median position of 88 in their 60-session range. The user
has now twice pointed at the consequence: SGER was ranked 9th of 15 at 600 and
2nd at 660, because the score is built from two momentum components that both
rise as the price rises, so a name becomes buyable only after it has run.

Read the paper's limits before reading this sweep's result. Its sample is 464
CONFIRMED ten-baggers, so every coefficient is conditional on the stock already
having become one; the paper says plainly that an ex-ante screener "will be the
subject of the author's future research". Its horizon is one year, ours is 20-60
sessions under an 8% trailing stop. And our own EXTENSION_GATE test rejected 9
of 9 thresholds, with the loosest gate costing the most alpha -- evidence that
the stretched names are where our fat tail lives.

What makes this worth one clean test anyway is that the extension gate REMOVED
candidates and this REORDERS them. Those are different experiments, and only the
first has been run.

Pre-registered in docs/EXPERIMENT_REGISTER.md before running. Nothing here may
be promoted: the nine windows are closed (docs/HOLDOUT_PROTOCOL.md Rule 1), and
slippage is ON per Rule 4.

Usage:  python sweep_price_range.py
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from loadtest_trail import partitions, summarise  # noqa: E402

GRID = [0.0, 1.0, 2.0, 4.0, 8.0]
LOOKBACK = 252   # ~12 months of sessions, the paper's own window
MIN_HIST = 60    # below this there is no 12-month range to speak of


def add_price_range(df: pd.DataFrame) -> pd.DataFrame:
    """(close - rolling low) / (rolling high - rolling low), per stock.

    The window INCLUDES the current row, which is the paper's definition and
    introduces no look-ahead: today's high and low are known today. A stock with
    fewer than MIN_HIST sessions gets NaN, which score_candidates reads as
    neutral rather than as "at the low".
    """
    df = df.sort_values(["stock_code", "trade_date"]).copy()
    g = df.groupby("stock_code")["close_price"]
    hi = g.transform(lambda s: s.rolling(LOOKBACK, min_periods=MIN_HIST).max())
    lo = g.transform(lambda s: s.rolling(LOOKBACK, min_periods=MIN_HIST).min())
    span = (hi - lo).replace(0, np.nan)
    df["price_range_252"] = ((df["close_price"] - lo) / span).clip(0, 1)
    return df


def main():
    print("[DATA] loading cached dataset ...")
    df0, idx0 = wf.load_dataset()
    df0 = add_price_range(df0)
    ok = df0["price_range_252"].notna()
    print(f"[DATA] {len(df0):,} rows; price_range_252 present on {ok.mean() * 100:.1f}%, "
          f"median {df0.loc[ok, 'price_range_252'].median():.2f}")

    # Costs on by default -- HOLDOUT_PROTOCOL Rule 4.
    os.environ["V4_SLIPPAGE"] = "1"
    bt.SLIPPAGE_ENABLED = True

    parts = partitions()
    rows = []
    for w in GRID:
        bt.PRICE_RANGE_PENALTY = w
        for pname, sched in parts.items():
            s = summarise(wf.run_schedule(df0.copy(), idx0.copy(), sched))
            s.update(partition=pname, penalty=w)
            rows.append(s)
            tag = f"penalty={w:g}" + ("  (production: off)" if w == 0 else "")
            print(f"  {pname:>10} {tag:<26} alpha {s['alpha_mean']:+7.2f}%  "
                  f"med {s['alpha_med']:+7.2f}%  worstDD {s['worst_dd']:7.2f}%  "
                  f"beat {s['beat']}/{s['windows']}  PF {s['pf']:.2f}")
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(SRC, "sweep_price_range.csv"), index=False)

    print("\n--- against penalty=0, on ALL THREE cuts ---")
    for w in GRID[1:]:
        line, better, dd_ok = [], 0, 0
        for pname in parts:
            a = t[(t.partition == pname) & (t.penalty == w)].iloc[0]
            b = t[(t.partition == pname) & (t.penalty == 0.0)].iloc[0]
            da, dd = a.alpha_mean - b.alpha_mean, a.worst_dd - b.worst_dd
            better += da > 0
            dd_ok += dd >= 0
            line.append(f"{pname} {da:+6.2f}pp/DD{dd:+6.2f}pp")
        verdict = "PASSES on all three" if better == 3 and dd_ok == 3 else "fails"
        print(f"  penalty={w:<4g} {'  '.join(line)}   {verdict}")

    print("\n[DONE] Robustness reading only. A cell that passes here is a candidate "
          "to watch forward, never a change to ship -- the nine windows are closed.")


if __name__ == "__main__":
    main()
