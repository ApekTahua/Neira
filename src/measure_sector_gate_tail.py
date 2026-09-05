"""Does the sector gate throw away the right tail?

LUCY ran 224 -> 585 (+161%) between 3 Aug and 4 Sep 2026 and Neira never named
it once. Checked day by day: from 31 Aug it passed liquidity and the volatility
cap, and on 4 Sep its own weekly trend put it in the 98th percentile of the
whole universe. Every single day it failed on one thing -- `sector_rs_momentum`
was negative while the gate demanded positive. The stock screamed; its sector
did not; the rule needs both.

That is one story, and one story is worth nothing. This asks the general
question: among names that already pass liquidity, the volatility cap and the
weekly-trend cut, does sector momentum select FOR or AGAINST a big run?

Deliberately NOT a threshold test. Picking a cut invites the same
best-of-N problem as everything else. Instead the qualifying pool is split into
deciles by sector momentum and the tail rate is measured in each. If the gate
earns its place, the top deciles carry more of the tail. If the rate is flat --
or worse, tilted the other way -- the gate is spending candidates for nothing.

Read-only. Nothing here may be promoted (docs/HOLDOUT_PROTOCOL.md Rule 1); a
diagnostic can only say an idea is worth pursuing or not.
"""
import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
os.chdir(SRC)

from dotenv import load_dotenv

load_dotenv(os.path.join(SRC, "..", ".env"))
os.environ.setdefault("V4_TEST_END", "2026-06-30")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402

HORIZON = 20
TAIL = 50.0      # "a big run" -- the same threshold the tail-fatness work used at 60d
WEEKLY_CUT_Q = 0.80   # stand-in for the train-derived weekly cut; swept below too


def main():
    print("[DATA] cached dataset ...")
    df, _ = wf.load_dataset()
    df = df[["stock_code", "trade_date", "close_price", "adtv_20", "atr_14",
             "weekly_ma_spread", "sector_rs_momentum"]].copy()
    df["trade_date"] = df["trade_date"].astype(str).str.slice(0, 10)
    cal = sorted(df.trade_date.unique())
    idx = {d: i for i, d in enumerate(cal)}
    close = df.set_index(["stock_code", "trade_date"]).close_price.to_dict()

    # The production gates that come BEFORE the sector cut.
    liq = (df.adtv_20 >= bt.cfg.ADTV_MIN) & df.atr_14.notna() & (df.atr_14 > 0)
    vol = (df.atr_14 / df.close_price) <= 0.08
    pool = df[liq & vol & df.weekly_ma_spread.notna() & df.sector_rs_momentum.notna()].copy()

    # Weekly-trend cut, per day, as a within-day quantile -- a stand-in for the
    # train-derived cut, which varies by window. The point is only to reproduce
    # "already a strong-trend candidate" before asking what sector momentum adds.
    pool["wk_q"] = pool.groupby("trade_date").weekly_ma_spread.rank(pct=True)
    pool = pool[pool.wk_q >= WEEKLY_CUT_Q]
    print(f"[POOL] {len(pool):,} stock-days pass liquidity + volatility + weekly trend")

    def fwd_max(code, d0, n):
        i = idx.get(d0)
        if i is None:
            return None
        p0 = close.get((code, d0))
        if not p0 or p0 <= 0:
            return None
        w = [close.get((code, d)) for d in cal[i + 1:i + 1 + n]]
        w = [p for p in w if p]
        return (max(w) / p0 - 1) * 100 if w else None

    runs = [fwd_max(r.stock_code, r.trade_date, HORIZON)
            for r in pool.itertuples(index=False)]
    pool["run"] = runs
    pool = pool[pool.run.notna()]
    print(f"[POOL] {len(pool):,} with a full {HORIZON}-session forward window\n")

    pool["dec"] = pd.qcut(pool.sector_rs_momentum, 10, labels=False, duplicates="drop")
    print(f"Tail rate by sector-momentum decile  (P of a >+{TAIL:.0f}% run within "
          f"{HORIZON} sessions)")
    print(f"{'decile':>7}{'sector mom':>14}{'n':>8}{'tail rate':>12}{'median run':>13}")
    for d, g in pool.groupby("dec"):
        print(f"{int(d) + 1:>7}{g.sector_rs_momentum.median():>+14.4f}{len(g):>8}"
              f"{100 * (g.run > TAIL).mean():>11.2f}%{g.run.median():>+12.2f}%")

    lo = pool[pool.sector_rs_momentum < 0]
    hi = pool[pool.sector_rs_momentum >= 0]
    print(f"\n{'':>22}{'n':>8}{'tail rate':>12}{'median run':>13}")
    for lab, g in [("sector NEGATIVE", lo), ("sector positive", hi)]:
        print(f"{lab:>22}{len(g):>8}{100 * (g.run > TAIL).mean():>11.2f}%{g.run.median():>+12.2f}%")

    # Bootstrap the gap, resampling by DATE -- candidates on one day are not
    # independent of each other.
    rng = np.random.default_rng(11)
    by_date = {d: (g[g.sector_rs_momentum >= 0].run.values,
                   g[g.sector_rs_momentum < 0].run.values)
               for d, g in pool.groupby("trade_date")}
    dates = list(by_date)
    diffs = []
    for _ in range(2000):
        a, b = [], []
        for d in rng.choice(dates, size=len(dates), replace=True):
            p, n = by_date[d]
            a.append(p)
            b.append(n)
        a, b = np.concatenate(a), np.concatenate(b)
        if len(a) and len(b):
            diffs.append(100 * ((a > TAIL).mean() - (b > TAIL).mean()))
    loq, hiq = np.percentile(diffs, [2.5, 97.5])
    sig = "SIGNIFICANT" if loq > 0 or hiq < 0 else "not significant"
    print(f"\ntail-rate gap (positive sector minus negative), date-level bootstrap:")
    print(f"  {np.mean(diffs):+.2f} pp   95% CI [{loq:+.2f}, {hiq:+.2f}]   {sig}")
    print("\nA gate that earns its place shows a clearly POSITIVE gap. A gap that")
    print("straddles zero means the sector filter is discarding candidates without")
    print("buying anything -- and LUCY is what that costs.")


if __name__ == "__main__":
    main()
