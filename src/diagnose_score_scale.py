"""Is the score formula's normalisation actually broken, and by how much?

An internal note from 2026-08-24 recorded, unfixed: the score blends two features
that are meant to contribute evenly, but each is normalised by its OWN threshold
value, and those thresholds are on wildly different scales and move differently
across windows -- so one feature silently dominates in some periods and not in
others. Nobody chose that; it falls out of the arithmetic.

    w_comp = (weekly_ma_spread - weekly_cut) / |weekly_cut|      weekly_cut ~ 2.3
    s_comp = (sector_rs_momentum - sector_cut) / |sector_cut|    sector_cut ~ 0.003
    score  = w_comp + s_comp

That score decides which 6 of 15 daily candidates get bought, so it sits upstream
of every walk-forward number this project has produced. Ten improvement ideas
have now been graded on top of it.

This measures the claim before anything is changed. Per walk-forward window, on
that window's own train-derived cuts and its own test-period qualifying pool:
  - the two cut values, and how far they swing across windows
  - each component's spread (interquartile range) within the pool
  - each component's SHARE of the total score's variation -- the real question,
    since ranking is what the score is used for
  - how much the ranking changes if the two components are put on a common scale

Read-only. Changes nothing, ships nothing.

Usage:
    python src/diagnose_score_scale.py
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import config as cfg  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402


def qualifying_pool(df, regime_ok_dates, lo=None, hi=None):
    m = (
        (df["adtv_20"] >= cfg.ADTV_MIN)
        & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
        & df["atr_14"].notna() & (df["atr_14"] > 0)
        & ((df["atr_14"] / df["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
        & df["trade_date"].isin(regime_ok_dates)
    )
    if lo is not None:
        m &= df["trade_date"] >= lo
    if hi is not None:
        m &= df["trade_date"] <= hi
    return df[m]


def main():
    df, idx_df = wf.load_dataset(None)
    regime_by_date, streak_by_date, trend_by_date = bt.compute_regime_with_hysteresis(idx_df)
    ok_dates = {d for d in regime_by_date
                if regime_by_date[d] == "BULLISH"
                and streak_by_date.get(d, 0) >= bt.REGIME_CONFIRM_DAYS
                and trend_by_date.get(d, 0.0) >= bt.TREND_STRENGTH_MIN}

    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    rows = []
    print(f"{'win':<5}{'weekly_cut':>12}{'sector_cut':>12}{'w IQR':>10}{'s IQR':>10}"
          f"{'w share':>10}{'s share':>10}{'rank tau':>10}{'top6 kept':>11}")
    print("-" * 90)

    for i, (train_end, test_start, test_end) in enumerate(schedule, 1):
        train = qualifying_pool(df, ok_dates, hi=train_end)
        if train.empty:
            continue
        weekly_cut = train["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
        sector_cut = train["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)

        test = qualifying_pool(df, ok_dates, lo=test_start, hi=test_end)
        test = test[(test["weekly_ma_spread"] >= weekly_cut)
                    & (test["sector_rs_momentum"] >= sector_cut)]
        if len(test) < 50:
            continue

        w = (test["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        s = (test["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
        w_iqr = w.quantile(.75) - w.quantile(.25)
        s_iqr = s.quantile(.75) - s.quantile(.25)
        # Share of the score's own variation each component supplies. Standard
        # deviation, not IQR, because that is what "dominates the ranking" means
        # once the two are added together.
        w_sd, s_sd = w.std(), s.std()
        tot = w_sd + s_sd
        w_share, s_share = (100 * w_sd / tot, 100 * s_sd / tot) if tot else (np.nan, np.nan)

        # What changes if both are put on a common scale? Standardise each by its
        # own train-period spread instead of by its threshold value.
        tw = (train["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        ts = (train["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
        w_scale = tw.std() or 1.0
        s_scale = ts.std() or 1.0
        score_old = w + s
        score_new = w / w_scale + s / s_scale

        # How much does the ordering actually move? Per day, since ranking is
        # only ever done within a day.
        taus, kept = [], []
        for d, g in test.assign(_o=score_old, _n=score_new).groupby("trade_date"):
            if len(g) < 6:
                continue
            taus.append(g["_o"].corr(g["_n"], method="kendall"))
            top_o = set(g.nlargest(6, "_o")["stock_code"])
            top_n = set(g.nlargest(6, "_n")["stock_code"])
            kept.append(len(top_o & top_n) / 6)
        tau = np.nanmean(taus) if taus else np.nan
        keep = 100 * np.mean(kept) if kept else np.nan

        print(f"W{i:<4}{weekly_cut:>12.3f}{sector_cut:>12.5f}{w_iqr:>10.2f}{s_iqr:>10.2f}"
              f"{w_share:>9.1f}%{s_share:>9.1f}%{tau:>10.3f}{keep:>10.1f}%")
        rows.append({"win": i, "weekly_cut": weekly_cut, "sector_cut": sector_cut,
                     "w_share": w_share, "s_share": s_share, "tau": tau, "keep": keep})

    if not rows:
        print("no usable windows")
        return
    r = pd.DataFrame(rows)
    print("-" * 90)
    print(f"\nweekly_cut across windows: {r['weekly_cut'].min():.3f} .. {r['weekly_cut'].max():.3f}"
          f"  ({r['weekly_cut'].max() / max(r['weekly_cut'].min(), 1e-9):.1f}x swing)")
    print(f"sector_cut across windows: {r['sector_cut'].min():.5f} .. {r['sector_cut'].max():.5f}"
          f"  ({r['sector_cut'].max() / max(r['sector_cut'].min(), 1e-9):.1f}x swing)")
    print(f"\nweekly component's share of score variation: "
          f"{r['w_share'].min():.1f}% .. {r['w_share'].max():.1f}% "
          f"(mean {r['w_share'].mean():.1f}%)")
    print(f"  -> if the blend were even, this would sit near 50% in every window.")
    print(f"\nPutting both on a common scale changes the within-day ordering: "
          f"mean Kendall tau {r['tau'].mean():.3f}, "
          f"and only {r['keep'].mean():.1f}% of each day's top-6 picks survive unchanged.")


if __name__ == "__main__":
    main()
