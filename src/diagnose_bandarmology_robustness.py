"""diagnose_bandarmology_robustness.py -- two follow-up checks after the
liquidity-gate result surprised expectations (docs/BANDARMOLOGY_DESIGN.md,
Layer 1 section): restricting net_flow_norm/concentration to liquid names
(ADTV_MIN gate) made the edge WORSE (7/9->1/9 for net_flow_norm), the
opposite of what the domain research's manipulation-risk warning predicted.
Two live explanations, not yet distinguished:

1. The edge is a broad, real effect that happens to be strongest in
   illiquid names (bandarmology folklore itself centers on small/mid-caps,
   where one broker's flow is a bigger share of total volume) -- not
   evidence of anything wrong.
2. The edge is driven by a small number of extreme-return prints
   (manipulation-style pump/dump spikes), which would show up as: (a)
   fragile to winsorizing forward returns, and (b) concentrated in the
   single most illiquid slice rather than smoothly present across the
   liquidity spectrum.

Check A -- winsorize forward returns at 1%/99% globally, rerun the same
9-check grid (net_flow_norm, concentration; 5/10/20d; 3 subperiods) on
the SAME 2024+ full-universe data the positive 7/9 results came from. If
wins/9 barely moves, the edge isn't a few outlier prints.

Check B -- per-day cross-sectional liquidity quintile (Q1=least liquid,
Q5=most liquid), 20d horizon only (the strongest horizon from Layer 1),
top-vs-bottom feature-quantile spread computed WITHIN each liquidity
quintile separately. A smooth gradient (edge shrinks steadily from Q1 to
Q5) supports explanation 1; an edge that's ONLY present in Q1 and flat/
zero elsewhere supports explanation 2.

Usage: python src/diagnose_bandarmology_robustness.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from diagnose_bandarmology_power import (  # noqa: E402
    load_prices, add_forward_returns, quantile_spread, HORIZONS, N_SUBPERIODS,
)

FEATURES = ("net_flow_norm", "concentration")  # consistency already confirmed dead, skip
MIN_DATE = "2024-03-06"  # matches the periods-2-3-only run that found the 7/9 edge


def load_merged():
    raw = bf.load_raw()
    broker_net = bf.per_broker_net(raw)
    daily = bf.daily_stock_features(broker_net)
    feats = bf.rolling_features(daily)
    feats = feats[feats["trade_date"] >= pd.Timestamp(MIN_DATE).date()]

    stock_codes = feats["stock_code"].unique().tolist()
    start = feats["trade_date"].min().isoformat()
    end = feats["trade_date"].max().isoformat()
    print(f"loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_forward_returns(prices)

    merged = feats.merge(prices, on=["trade_date", "stock_code"], how="inner")
    print(f"merged rows: {len(merged)}\n")
    return merged


def check_a_winsorize(merged: pd.DataFrame):
    print("=" * 70)
    print("CHECK A -- winsorized forward returns (1%/99%), same 2024+ data")
    print("=" * 70)
    wins_df = merged.copy()
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        lo, hi = wins_df[col].quantile([0.01, 0.99])
        wins_df[col] = wins_df[col].clip(lo, hi)

    dates = sorted(wins_df["trade_date"].unique())
    cut_points = np.linspace(0, len(dates), N_SUBPERIODS + 1, dtype=int)
    periods = [dates[cut_points[i]:cut_points[i + 1]] for i in range(N_SUBPERIODS)]

    for feature in FEATURES:
        print(f"\n=== {feature} (winsorized) ===")
        total_wins = 0
        for h in HORIZONS:
            col = f"fwd_ret_{h}d"
            wins = 0
            for period_dates in periods:
                sub = wins_df[wins_df["trade_date"].isin(period_dates)]
                spread = quantile_spread(sub, feature, col)
                if len(spread) < 2:
                    continue
                win = spread.iloc[-1] > spread.iloc[0]
                wins += win
            print(f" horizon {h}d: top>bottom in {wins}/{N_SUBPERIODS} periods")
            total_wins += wins
        print(f" -> total {total_wins}/9 (winsorized) -- compare to the unwinsorized 2024+ result")


def check_b_liquidity_quintiles(merged: pd.DataFrame):
    print("\n" + "=" * 70)
    print("CHECK B -- 20d edge by per-day liquidity quintile (Q1=illiquid..Q5=liquid)")
    print("=" * 70)
    df = merged.dropna(subset=["adtv_20", "fwd_ret_20d"]).copy()

    def _liq_quintile(day_df):
        if day_df["adtv_20"].nunique() < 5:
            return pd.Series(np.nan, index=day_df.index)
        return pd.qcut(day_df["adtv_20"], 5, labels=False, duplicates="drop") + 1

    df["_liq_q"] = df.groupby("trade_date", group_keys=False).apply(_liq_quintile)
    df = df.dropna(subset=["_liq_q"])

    for feature in FEATURES:
        print(f"\n=== {feature}, 20d horizon, by liquidity quintile ===")
        for lq in range(1, 6):
            sub = df[df["_liq_q"] == lq]
            spread = quantile_spread(sub, feature, "fwd_ret_20d")
            if len(spread) < 2:
                print(f" liquidity Q{lq}: not enough distinct values, skipped")
                continue
            top, bottom = spread.iloc[-1], spread.iloc[0]
            print(f" liquidity Q{lq} (n={len(sub)}): top_q={top:+.4f} bottom_q={bottom:+.4f} "
                  f"spread={top - bottom:+.4f} top>bottom={top > bottom}")


def main():
    merged = load_merged()
    check_a_winsorize(merged)
    check_b_liquidity_quintiles(merged)


if __name__ == "__main__":
    main()
