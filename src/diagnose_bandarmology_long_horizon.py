"""diagnose_bandarmology_long_horizon.py -- tests a genuinely new
hypothesis surfaced by the 2026-08-12 domain cross-check (see
docs/BANDARMOLOGY_DESIGN.md): a beneficial owner's quiet accumulation
can run for MONTHS with zero short-term price impact ("bikin sahamnya
sideways... gak bisa cuan") before the eventual move. Every Bandarmology
feature validated so far (net_flow_norm/consistency/concentration) was
tested against 5/10/20-session forward returns -- exactly the timescale
this pattern is DESIGNED to be invisible at. This asks the same
question at the timescale the pattern actually predicts on: does
persistent LONG-window (60-trading-day, ~3 calendar months)
accumulation predict LONG-horizon (60/90/120-session) forward returns?

Not a rerun of `consistency` (which failed Layer 1 at a 10-day window /
5-20 day horizons) -- a different window AND a different horizon range,
testing a different claim. `consistency` failing at short-term doesn't
imply this fails at long-term; they're separate hypotheses.

Reuses bandarmology_features.rolling_features's own `window` parameter
(already generic, no changes needed there) to compute `consistency` at
a 60-day window instead of the original 10-day default -- same formula,
just measuring persistence over a season instead of two weeks.

STATUS 2026-08-12: first run. Long horizons mean the last ~120 trading
days of the backfill can't have a complete forward-return window --
expected sample-size cost of testing further out, not a bug.

Usage: python src/diagnose_bandarmology_long_horizon.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from diagnose_bandarmology_power import load_prices, quantile_spread, N_SUBPERIODS  # noqa: E402

LONG_WINDOW = 60  # trading days, ~1 quarter -- vs the original 10-day consistency window
LONG_HORIZONS = (60, 90, 120)  # sessions, vs the original 5/10/20


def add_long_forward_returns(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    for h in LONG_HORIZONS:
        fwd_close = prices.groupby("stock_code")["close_price"].shift(-h)
        prices[f"fwd_ret_{h}d"] = fwd_close / prices["close_price"] - 1
    return prices


def main():
    raw = bf.load_raw()
    broker_net = bf.per_broker_net(raw)
    daily = bf.daily_stock_features(broker_net)
    feats = bf.rolling_features(daily, window=LONG_WINDOW)
    feats = feats.rename(columns={"consistency": "long_consistency", "net_flow_norm": "long_net_flow_norm"})

    stock_codes = feats["stock_code"].unique().tolist()
    start = feats["trade_date"].min().isoformat()
    end = feats["trade_date"].max().isoformat()
    print(f"loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_long_forward_returns(prices)

    merged = feats.merge(prices, on=["trade_date", "stock_code"], how="inner")
    print(f"merged rows: {len(merged)}\n")

    dates = sorted(merged["trade_date"].unique())
    cut_points = np.linspace(0, len(dates), N_SUBPERIODS + 1, dtype=int)
    periods = [dates[cut_points[i]:cut_points[i + 1]] for i in range(N_SUBPERIODS)]

    for feature in ("long_consistency", "long_net_flow_norm"):
        print(f"=== {feature} (window={LONG_WINDOW}d) ===")
        for h in LONG_HORIZONS:
            col = f"fwd_ret_{h}d"
            print(f" horizon {h}d:")
            wins = 0
            for i, period_dates in enumerate(periods):
                sub = merged[merged["trade_date"].isin(period_dates)].dropna(subset=[col])
                if sub.empty:
                    print(f"   period {i+1}: no rows with a complete {h}d forward window, skipped")
                    continue
                spread = quantile_spread(sub, feature, col)
                if len(spread) < 2:
                    print(f"   period {i+1}: not enough distinct values, skipped")
                    continue
                top, bottom = spread.iloc[-1], spread.iloc[0]
                win = top > bottom
                wins += win
                print(f"   period {i+1} ({period_dates[0]}..{period_dates[-1]}): "
                      f"top_q={top:+.4f} bottom_q={bottom:+.4f} top>bottom={win}")
            print(f"   -> top>bottom in {wins}/{N_SUBPERIODS} periods")
        print()


if __name__ == "__main__":
    main()
