"""Does broker flow predict the RIGHT TAIL? The founding question, re-asked.

This system was built to read bandar flow. It does not use it to pick stocks --
the entry score is weekly trend plus sector momentum, and bandarmology only sizes
positions. That gap exists because bandar-as-entry was tested once and rejected
on a **42.5% win rate**.

Win rate is the one axis on which this project's selection is provably average.
Eleven selection experiments were graded on it before the 2026-09-05 measurement
showed the edge lives in the fatness of the right tail, not in direction. So the
bandar rejection was decided on the wrong metric, exactly like the others, and
the question has never actually been asked.

Same shape as the sector-gate diagnostic: take the stock-days that already pass
liquidity, the volatility cap and the weekly-trend cut, split them by each bandar
feature into deciles, and measure the probability of a >+50% run in 20 sessions.
Not a threshold test -- deciles, so no cut is being searched for.

Read-only, and nothing here may be promoted (HOLDOUT_PROTOCOL Rule 1). A
diagnostic can say "worth pursuing" or "stop wondering". Nothing more.
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
TAIL = 50.0
WEEKLY_CUT_Q = 0.80
FEATURES = ["concentration", "mover_score", "accdist_score", "rotation_score"]


def main():
    print("[DATA] cached dataset ...")
    df, _ = wf.load_dataset()
    keep = (["stock_code", "trade_date", "close_price", "adtv_20", "atr_14",
             "weekly_ma_spread", "sector_rs_momentum"] + FEATURES)
    df = df[keep].copy()
    df["trade_date"] = df["trade_date"].astype(str).str.slice(0, 10)
    cal = sorted(df.trade_date.unique())
    idx = {d: i for i, d in enumerate(cal)}
    close = df.set_index(["stock_code", "trade_date"]).close_price.to_dict()

    liq = (df.adtv_20 >= bt.cfg.ADTV_MIN) & df.atr_14.notna() & (df.atr_14 > 0)
    vol = (df.atr_14 / df.close_price) <= 0.08
    pool = df[liq & vol & df.weekly_ma_spread.notna() & df.sector_rs_momentum.notna()].copy()
    pool["wk_q"] = pool.groupby("trade_date").weekly_ma_spread.rank(pct=True)
    pool = pool[pool.wk_q >= WEEKLY_CUT_Q]

    def fwd_max(code, d0, n):
        i = idx.get(d0)
        if i is None:
            return None
        p0 = close.get((code, d0))
        if not p0 or p0 <= 0:
            return None
        w = [p for p in (close.get((code, d)) for d in cal[i + 1:i + 1 + n]) if p]
        return (max(w) / p0 - 1) * 100 if w else None

    pool["run"] = [fwd_max(r.stock_code, r.trade_date, HORIZON)
                   for r in pool.itertuples(index=False)]
    pool = pool[pool.run.notna()]
    base = 100 * (pool.run > TAIL).mean()
    print(f"[POOL] {len(pool):,} stock-days past the existing gates; "
          f"baseline tail rate {base:.2f}%\n")

    rng = np.random.default_rng(11)
    for f in FEATURES:
        sub = pool[pool[f].notna()].copy()
        # A feature that is zero for most rows has no deciles to speak of; split
        # zero from non-zero instead of pretending qcut means something.
        nz = (sub[f] != 0).mean()
        print("=" * 78)
        print(f"{f}   n={len(sub):,} ({100 * len(sub) / len(pool):.0f}% of pool), "
              f"non-zero {100 * nz:.0f}%")
        try:
            sub["dec"] = pd.qcut(sub[f], 10, labels=False, duplicates="drop")
            grouped = list(sub.groupby("dec"))
        except ValueError:
            grouped = []
        if len(grouped) >= 4:
            print(f"{'bucket':>8}{'value':>14}{'n':>9}{'tail rate':>12}{'median run':>13}")
            for d, g in grouped:
                print(f"{int(d) + 1:>8}{g[f].median():>+14.4f}{len(g):>9}"
                      f"{100 * (g.run > TAIL).mean():>11.2f}%{g.run.median():>+12.2f}%")
        else:
            print("  too concentrated for deciles -- zero vs non-zero only")

        hi = sub[sub[f] > sub[f].median()]
        lo = sub[sub[f] <= sub[f].median()]
        if not len(hi) or not len(lo):
            print("  no usable split\n")
            continue
        print(f"\n  above median  n={len(hi):>7}  tail {100 * (hi.run > TAIL).mean():.2f}%")
        print(f"  below median  n={len(lo):>7}  tail {100 * (lo.run > TAIL).mean():.2f}%")

        by_date = {d: (g[g[f] > sub[f].median()].run.values,
                       g[g[f] <= sub[f].median()].run.values)
                   for d, g in sub.groupby("trade_date")}
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
        print(f"  gap (high minus low), date-level bootstrap: {np.mean(diffs):+.2f} pp  "
              f"95% CI [{loq:+.2f}, {hiq:+.2f}]  {sig}\n")

    print("Compare against the sector gate measured the same way today: +1.52pp,")
    print("CI [+1.09, +1.93], broadly monotonic across deciles. That is what a")
    print("feature worth putting in the entry looks like. Anything flat here means")
    print("bandar flow does not belong in the entry, and we stop wondering.")


if __name__ == "__main__":
    main()
