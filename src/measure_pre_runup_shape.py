"""Look BACKWARD from the big runs instead of forward from the setups.

The forward test (measure_coiling_tail.py) said coiling is worse than useless:
tight MAs 6.64% tail rate against 21.97% for wide, quiet 2.87% against 20.62%
for volatile, and the owner's full "coiled AND accumulated" rule scored 5.96%
against an 11.93% baseline.

That test cannot answer the question it was pointed at, and the reason is
mechanical. "Will this rise more than 50% in 60 sessions" is far easier for a
stock that already moves 5% a day than one that moves 1.8%, so `atr_ratio`
predicting the tail is close to arithmetic rather than insight. `ma_squeeze`
widens BECAUSE price moved, so it is a lagging read of a move already underway.
And a base that coils for eight months contributes ~150 "failure" days and one
success, so a forward-from-every-day design is biased against slow setups by
construction.

The version of the hypothesis that is NOT tautological runs backward: take the
runs that actually happened, and ask what those names looked like BEFORE they
started. If big runs are typically born out of quiet, coiled bases, the owner is
right and the current entry is arriving late by design. If they are born out of
names that were already moving, the current entry is early enough and coiling is
a story we tell ourselves.

Read-only, closed windows, Rule 1.
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

LOOKBACK = 20     # sessions before the run starts
HORIZON = 60
TAIL = 50.0


def main():
    print("[DATA] cached dataset ...")
    df, _ = wf.load_dataset()
    df = df[["stock_code", "trade_date", "close_price", "adtv_20", "atr_14",
             "ma10", "ma20", "ma50", "mover_score", "accdist_score"]].copy()
    df["trade_date"] = df["trade_date"].astype(str).str.slice(0, 10)
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)

    mas = df[["ma10", "ma20", "ma50"]]
    df["ma_squeeze"] = (mas.max(axis=1) - mas.min(axis=1)) / df.close_price
    df["atr_ratio"] = df.atr_14 / df.close_price
    df = df[(df.adtv_20 >= bt.cfg.ADTV_MIN) & df.ma_squeeze.notna() & df.atr_ratio.notna()]

    cal = sorted(df.trade_date.unique())
    idx = {d: i for i, d in enumerate(cal)}
    close = df.set_index(["stock_code", "trade_date"]).close_price.to_dict()
    feat = df.set_index(["stock_code", "trade_date"])[["ma_squeeze", "atr_ratio",
                                                       "mover_score", "accdist_score"]]

    # A "run start" is the first day of a >TAIL% advance completed within HORIZON
    # sessions, and the name must not have already been running: require the
    # trailing 20-session gain to be under +10%, so we are catching ignition, not
    # the middle of a move already in progress.
    starts, controls = [], []
    for r in df.itertuples(index=False):
        i = idx.get(r.trade_date)
        if i is None or i < LOOKBACK or i + HORIZON >= len(cal):
            continue
        p0 = close.get((r.stock_code, r.trade_date))
        pback = close.get((r.stock_code, cal[i - LOOKBACK]))
        if not p0 or not pback or p0 <= 0 or pback <= 0:
            continue
        if (p0 / pback - 1) * 100 > 10:      # already running -- not an ignition point
            continue
        w = [p for p in (close.get((r.stock_code, d))
                         for d in cal[i + 1:i + 1 + HORIZON]) if p]
        if not w:
            continue
        (starts if (max(w) / p0 - 1) * 100 > TAIL else controls).append(
            (r.stock_code, cal[i - LOOKBACK]))

    print(f"[EVENTS] {len(starts):,} ignition points (a >+{TAIL:.0f}% run began, "
          f"after a flat-to-mild 20 sessions)")
    print(f"[CTRL  ] {len(controls):,} matched non-events\n")

    def shape(pairs, label):
        rows = feat.reindex(pairs).dropna(subset=["ma_squeeze", "atr_ratio"])
        print(f"{label:>26}  n={len(rows):>7}"
              f"  ma_squeeze {rows.ma_squeeze.median():.4f}"
              f"  atr_ratio {rows.atr_ratio.median():.4f}"
              f"  bandar-active {100 * ((rows.mover_score.fillna(0) > 0) | (rows.accdist_score.fillna(0) > 0)).mean():.1f}%")
        return rows

    print(f"What they looked like {LOOKBACK} sessions BEFORE:")
    a = shape(starts, "before a big run")
    b = shape(controls, "everything else")

    rng = np.random.default_rng(11)
    for col in ("ma_squeeze", "atr_ratio"):
        d = [np.median(rng.choice(a[col].values, len(a))) - np.median(rng.choice(b[col].values, len(b)))
             for _ in range(2000)]
        lo, hi = np.percentile(d, [2.5, 97.5])
        sig = "SIGNIFICANT" if lo > 0 or hi < 0 else "not significant"
        print(f"\n  {col:<12} median difference {np.mean(d):+.4f}  "
              f"95% CI [{lo:+.4f}, {hi:+.4f}]  {sig}")
        print(f"    {'quieter/tighter before a run' if np.mean(d) < 0 else 'noisier/wider before a run'}")


if __name__ == "__main__":
    main()
