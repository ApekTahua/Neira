"""Does the "coiling" pattern precede a multibagger run?

The owner's proposal: the existing quant signal is a swing/trend-riding tool,
and forcing it to also find multibaggers is asking one instrument to do two
jobs. A separate method would look for the opposite shape -- a stock going
sideways, being accumulated, with its moving averages squeezed together.

That is a testable claim, and it is the OPPOSITE of what the current entry
demands. Today's entry requires `weekly_ma_spread` in the top fifth (a trend
already extended) and caps ATR. A coiling screener would want low spread and
low volatility.

Measured here on the full liquid universe -- NOT on candidates that already
passed the current gates, because the whole point is that these names never
reach those gates:

  ma_squeeze   (max(ma10,ma20,ma50) - min(...)) / close   -- lower = tighter
  atr_ratio    atr_14 / close                             -- lower = quieter
  range_pos    position in the 252-session high/low range -- lower = nearer the low
  mover_score / accdist_score                             -- bandar activity

Horizon is 60 sessions, not 20: a base takes time to resolve. Tail is >+50%.

Read-only, closed windows, Rule 1. This says "worth building" or "not".
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

HORIZON = 60
TAIL = 50.0


def main():
    print("[DATA] cached dataset ...")
    df, _ = wf.load_dataset()
    df = df[["stock_code", "trade_date", "close_price", "adtv_20", "atr_14",
             "ma10", "ma20", "ma50", "weekly_ma_spread",
             "mover_score", "accdist_score"]].copy()
    df["trade_date"] = df["trade_date"].astype(str).str.slice(0, 10)
    df = df.sort_values(["stock_code", "trade_date"])

    g = df.groupby("stock_code")["close_price"]
    hi = g.transform(lambda s: s.rolling(252, min_periods=60).max())
    lo = g.transform(lambda s: s.rolling(252, min_periods=60).min())
    df["range_pos"] = ((df.close_price - lo) / (hi - lo).replace(0, np.nan)).clip(0, 1)

    mas = df[["ma10", "ma20", "ma50"]]
    df["ma_squeeze"] = (mas.max(axis=1) - mas.min(axis=1)) / df.close_price
    df["atr_ratio"] = df.atr_14 / df.close_price

    # Liquidity only. Deliberately no trend or volatility gate -- these names are
    # exactly the ones the current entry never sees.
    pool = df[(df.adtv_20 >= bt.cfg.ADTV_MIN) & df.ma_squeeze.notna()
              & df.atr_ratio.notna() & df.range_pos.notna()].copy()

    cal = sorted(df.trade_date.unique())
    idx = {d: i for i, d in enumerate(cal)}
    close = df.set_index(["stock_code", "trade_date"]).close_price.to_dict()

    def fwd_max(code, d0):
        i = idx.get(d0)
        p0 = close.get((code, d0))
        if i is None or not p0 or p0 <= 0:
            return None
        w = [p for p in (close.get((code, d)) for d in cal[i + 1:i + 1 + HORIZON]) if p]
        return (max(w) / p0 - 1) * 100 if w else None

    pool["run"] = [fwd_max(r.stock_code, r.trade_date) for r in pool.itertuples(index=False)]
    pool = pool[pool.run.notna()]
    base = 100 * (pool.run > TAIL).mean()
    print(f"[POOL] {len(pool):,} liquid stock-days, baseline P(>+{TAIL:.0f}% in "
          f"{HORIZON} sessions) = {base:.2f}%\n")

    for f, note in [("ma_squeeze", "lower = MAs tighter together"),
                    ("atr_ratio", "lower = quieter"),
                    ("range_pos", "lower = nearer the 52-week low"),
                    ("weekly_ma_spread", "HIGH is what the current entry demands")]:
        sub = pool[pool[f].notna()].copy()
        sub["dec"] = pd.qcut(sub[f], 10, labels=False, duplicates="drop")
        print("=" * 74)
        print(f"{f}  ({note})   n={len(sub):,}")
        print(f"{'decile':>7}{'value':>13}{'n':>8}{'tail rate':>12}{'median run':>13}")
        for d, gg in sub.groupby("dec"):
            print(f"{int(d) + 1:>7}{gg[f].median():>+13.4f}{len(gg):>8}"
                  f"{100 * (gg.run > TAIL).mean():>11.2f}%{gg.run.median():>+12.2f}%")
        print()

    # The owner's actual proposal is a CONJUNCTION: quiet AND coiled AND being
    # accumulated. Test it as one thing, against the same universe.
    q = pool.ma_squeeze.quantile(0.3)
    v = pool.atr_ratio.quantile(0.5)
    coil = pool[(pool.ma_squeeze <= q) & (pool.atr_ratio <= v)]
    coil_bandar = coil[(coil.mover_score.fillna(0) > 0) | (coil.accdist_score.fillna(0) > 0)]
    print("=" * 74)
    print("THE PROPOSAL AS ONE RULE")
    print(f"{'':>34}{'n':>9}{'tail rate':>12}{'vs base':>10}")
    for lab, s in [("every liquid name (baseline)", pool),
                   ("coiled (tight MAs + quiet)", coil),
                   ("coiled AND bandar active", coil_bandar)]:
        r = 100 * (s.run > TAIL).mean()
        print(f"{lab:>34}{len(s):>9}{r:>11.2f}%{r - base:>+9.2f}pp")

    rng = np.random.default_rng(11)
    by_date = {}
    tgt = set(map(tuple, coil_bandar[["stock_code", "trade_date"]].values))
    for d, gg in pool.groupby("trade_date"):
        m = np.array([(c, d) in tgt for c in gg.stock_code])
        by_date[d] = (gg.run.values[m], gg.run.values[~m])
    dates = list(by_date)
    diffs = []
    for _ in range(2000):
        a, b = [], []
        for d in rng.choice(dates, size=len(dates), replace=True):
            x, y = by_date[d]
            a.append(x)
            b.append(y)
        a, b = np.concatenate(a), np.concatenate(b)
        if len(a) and len(b):
            diffs.append(100 * ((a > TAIL).mean() - (b > TAIL).mean()))
    loq, hiq = np.percentile(diffs, [2.5, 97.5])
    print(f"\n'coiled AND bandar active' minus everything else, date-level bootstrap:")
    print(f"  {np.mean(diffs):+.2f} pp   95% CI [{loq:+.2f}, {hiq:+.2f}]   "
          f"{'SIGNIFICANT' if loq > 0 or hiq < 0 else 'not significant'}")


if __name__ == "__main__":
    main()
