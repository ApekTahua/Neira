"""diagnose_bandarmology_long_horizon_movers.py -- the corrected version
of the long-horizon "quiet accumulator" test. The first attempt
(diagnose_bandarmology_long_horizon.py) tested AGGREGATE market-wide
60-day consistency across ALL brokers combined and failed (1/9,
inverted). That tested the wrong thing: the user's actual story
(docs/BANDARMOLOGY_DESIGN.md, 2026-08-12 domain conversation) was about
a SPECIFIC broker (a beneficial owner's house broker) persistently
accumulating, not the whole market's aggregate behavior.

This extends `bandarmology_broker_profile.py`'s own validated
methodology (per-(stock,broker) split-half correlation, already proven
at a 5-day horizon -- 9/9 in the pair-level Layer 1 check) to LONG
horizons (60/90/120 sessions) instead. Same event-day-vs-baseline
comparison as diagnose_bandarmology_pairs_power.py's mover check, just
correlating against long forward returns when selecting candidates in
the first place.

Usage: python src/diagnose_bandarmology_long_horizon_movers.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from diagnose_bandarmology_power import load_prices, N_SUBPERIODS  # noqa: E402
from bandarmology_broker_profile import per_broker_daily, MIN_ACTIVE_DAYS, MIN_ABS_CORR  # noqa: E402

LONG_HORIZONS = (60, 90, 120)


def add_long_forward_returns(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    for h in LONG_HORIZONS:
        fwd_close = prices.groupby("stock_code")["close_price"].shift(-h)
        prices[f"fwd_ret_{h}d"] = fwd_close / prices["close_price"] - 1
    return prices


def candidate_movers_long(broker_daily: pd.DataFrame, fwd_ret: pd.DataFrame, horizon: int) -> pd.DataFrame:
    col = f"fwd_ret_{horizon}d"
    merged = broker_daily.merge(fwd_ret, on=["trade_date", "stock_code"], how="inner")
    merged = merged.dropna(subset=[col])
    results = []
    for (stock_code, broker_code), sub in merged.groupby(["stock_code", "broker_code"]):
        sub = sub.sort_values("trade_date")
        if len(sub) < MIN_ACTIVE_DAYS:
            continue
        mid = len(sub) // 2
        first_half, second_half = sub.iloc[:mid], sub.iloc[mid:]
        if first_half["net_lot"].nunique() < 3 or second_half["net_lot"].nunique() < 3:
            continue
        corr_1 = first_half["net_lot"].corr(first_half[col])
        corr_2 = second_half["net_lot"].corr(second_half[col])
        if pd.isna(corr_1) or pd.isna(corr_2):
            continue
        same_sign = (corr_1 > 0) == (corr_2 > 0)
        both_strong = abs(corr_1) >= MIN_ABS_CORR and abs(corr_2) >= MIN_ABS_CORR
        if same_sign and both_strong:
            results.append({
                "stock_code": stock_code, "broker_code": broker_code,
                "predicted_sign": np.sign(corr_1 + corr_2),
            })
    return pd.DataFrame(results)


def main():
    raw = bf.load_raw()
    broker_daily = per_broker_daily(raw)
    stock_codes = raw["stock_code"].unique().tolist()
    start = raw["trade_date"].min().isoformat()
    end = raw["trade_date"].max().isoformat()
    print(f"loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_long_forward_returns(prices)

    broker_net_full = bf.per_broker_net(raw)[["trade_date", "stock_code", "broker_code", "net_lot"]]

    for horizon in LONG_HORIZONS:
        movers = candidate_movers_long(broker_daily, prices, horizon)
        print(f"\n=== horizon {horizon}d: {len(movers)} candidate long-horizon movers ===")
        if movers.empty:
            continue

        merged = broker_net_full.merge(movers, on=["stock_code", "broker_code"], how="inner")
        event = merged[np.sign(merged["net_lot"]) == merged["predicted_sign"]]
        event_days = event[["stock_code", "trade_date"]].drop_duplicates()

        stocks_with_events = event_days["stock_code"].unique()
        universe = prices[prices["stock_code"].isin(stocks_with_events)].copy()
        universe = universe.merge(event_days.assign(is_event=True), on=["stock_code", "trade_date"], how="left")
        universe["is_event"] = universe["is_event"].fillna(False).astype(bool)

        col = f"fwd_ret_{horizon}d"
        dates = sorted(universe["trade_date"].unique())
        cut_points = np.linspace(0, len(dates), N_SUBPERIODS + 1, dtype=int)
        periods = [dates[cut_points[i]:cut_points[i + 1]] for i in range(N_SUBPERIODS)]

        wins = 0
        for i, period_dates in enumerate(periods):
            sub = universe[universe["trade_date"].isin(period_dates)].dropna(subset=[col])
            event_ret = sub.loc[sub["is_event"], col]
            base_ret = sub.loc[~sub["is_event"], col]
            if len(event_ret) < 10 or len(base_ret) < 10:
                print(f"   period {i+1}: too few rows (event={len(event_ret)}, base={len(base_ret)}), skipped")
                continue
            win = event_ret.mean() > base_ret.mean()
            wins += win
            print(f"   period {i+1} ({period_dates[0]}..{period_dates[-1]}): "
                  f"event_mean={event_ret.mean():+.4f} (n={len(event_ret)}) "
                  f"base_mean={base_ret.mean():+.4f} (n={len(base_ret)}) event>base={win}")
        print(f"   -> event>base in {wins}/{N_SUBPERIODS} periods")


if __name__ == "__main__":
    main()
