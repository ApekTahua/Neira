"""diagnose_bandarmology_pairs_power.py -- Layer 1 validation for the
PAIR-level structural flags (mover_pairs, rotation_pairs, cluster_pairs),
the biggest remaining methodology gap after validating the daily
features (net_flow_norm/consistency/concentration, see
diagnose_bandarmology_power.py). Those three tables have shipped to DB2
as pure structural/co-occurrence flags -- this asks the same question
Layer 1 already asked of the daily features: does any of this actually
carry forward-return information, or is it just a plausible-looking
pattern with nothing behind it?

Methodology, one EVENT-DAY definition per table, then a paired
signal-day vs non-signal-day forward-return comparison (same stock, so
each stock is its own baseline) across 3 subperiods, same anti-fluke
discipline as everything else in this project:

- MOVERS: for a (stock, broker) candidate-mover pair, an event day is
  one where that broker is net-acting in the direction its OWN
  historical correlation predicted as positive (net_lot sign matches
  sign of corr_first_half + corr_second_half). Tests: "did this
  broker's flagged action days actually see better forward returns than
  the stock's typical day?"
- ROTATION pairs: event day = both brokers in a flagged pair active on
  OPPOSITE sides that day (satisfies the pattern the pair was flagged
  for).
- CLUSTER pairs: event day = both brokers active on the SAME side that
  day.

For each table: pool all event-day (stock, trade_date) rows across every
candidate pair, compare mean forward return (5/10/20d) on event days vs
all other days for the SAME set of stocks (so a stock's own baseline
return level doesn't confound the comparison), split into 3 subperiods.

STATUS 2026-08-12: first run, full 2023-2026-08-11 data. Thresholds
(MIN_ACTIVE_DAYS=20, MIN_ABS_CORR=0.15 for movers; MIN_PAIR_DAYS=15,
MIN_LIFT=1.5 for rotation/cluster) are the same unvalidated placeholders
already documented in the source detector scripts -- this only tests
whether the RESULTING candidate sets carry signal, not whether those
specific thresholds are optimal.

Usage: python src/diagnose_bandarmology_pairs_power.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from diagnose_bandarmology_power import load_prices, add_forward_returns, HORIZONS, N_SUBPERIODS  # noqa: E402
from bandarmology_broker_profile import per_broker_daily, candidate_movers  # noqa: E402
from bandarmology_rotation_detector import find_rotation_pairs  # noqa: E402
from bandarmology_cluster_detector import find_cluster_pairs  # noqa: E402


def event_days_movers(raw: pd.DataFrame, movers: pd.DataFrame) -> pd.DataFrame:
    """One row per (stock_code, trade_date) where a candidate-mover
    broker acted in its historically-predictive direction."""
    broker_net = bf.per_broker_net(raw)[["trade_date", "stock_code", "broker_code", "net_lot"]]
    movers = movers[movers["candidate_mover"]].copy()
    movers["predicted_sign"] = np.sign(movers["corr_first_half"] + movers["corr_second_half"])
    merged = broker_net.merge(movers[["stock_code", "broker_code", "predicted_sign"]],
                               on=["stock_code", "broker_code"], how="inner")
    event = merged[np.sign(merged["net_lot"]) == merged["predicted_sign"]]
    return event[["stock_code", "trade_date"]].drop_duplicates()


def event_days_pairs(raw: pd.DataFrame, pairs: pd.DataFrame, broker_a_col: str, broker_b_col: str,
                      same_side: bool) -> pd.DataFrame:
    """One row per (stock_code, trade_date) where both brokers of a
    flagged pair are active on the same/opposite side that day."""
    broker_net = bf.per_broker_net(raw)
    broker_net = broker_net[broker_net["net_lot"] != 0][["trade_date", "stock_code", "broker_code", "net_lot"]]

    events = []
    for stock_code, group in pairs.groupby("stock_code"):
        stock_days = broker_net[broker_net["stock_code"] == stock_code]
        if stock_days.empty:
            continue
        wide = stock_days.pivot_table(index="trade_date", columns="broker_code", values="net_lot")
        for _, row in group.iterrows():
            a, b = row[broker_a_col], row[broker_b_col]
            if a not in wide.columns or b not in wide.columns:
                continue
            both_active = wide[a].notna() & wide[b].notna()
            if same_side:
                match = both_active & (np.sign(wide[a]) == np.sign(wide[b]))
            else:
                match = both_active & (np.sign(wide[a]) != np.sign(wide[b]))
            hit_dates = wide.index[match]
            if len(hit_dates) > 0:
                events.append(pd.DataFrame({"stock_code": stock_code, "trade_date": hit_dates}))
    if not events:
        return pd.DataFrame(columns=["stock_code", "trade_date"])
    return pd.concat(events, ignore_index=True).drop_duplicates()


def compare_event_vs_baseline(name: str, event_days: pd.DataFrame, prices: pd.DataFrame) -> None:
    print(f"\n=== {name}: {len(event_days)} event (stock, day) rows ===")
    if event_days.empty:
        print(" no event days, skipped")
        return
    stocks_with_events = event_days["stock_code"].unique()
    universe = prices[prices["stock_code"].isin(stocks_with_events)].copy()
    universe = universe.merge(
        event_days.assign(is_event=True), on=["stock_code", "trade_date"], how="left")
    # fillna leaves this object-dtype (NaN forced pandas to box the bools on
    # the merge), so ~ on it does Python bitwise-NOT on the boxed bools
    # (~True == -2, ~False == -1) instead of logical negation -- explicit
    # astype(bool) fixes the dtype back to native bool first.
    universe["is_event"] = universe["is_event"].fillna(False).astype(bool)

    dates = sorted(universe["trade_date"].unique())
    cut_points = np.linspace(0, len(dates), N_SUBPERIODS + 1, dtype=int)
    periods = [dates[cut_points[i]:cut_points[i + 1]] for i in range(N_SUBPERIODS)]

    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        print(f" horizon {h}d:")
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


def main():
    raw = bf.load_raw()
    print(f"raw rows: {len(raw)}, dates: {raw['trade_date'].min()} to {raw['trade_date'].max()}")

    stock_codes = raw["stock_code"].unique().tolist()
    start = raw["trade_date"].min().isoformat()
    end = raw["trade_date"].max().isoformat()
    print(f"loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_forward_returns(prices)

    # --- movers ---
    broker_daily = per_broker_daily(raw)
    movers = candidate_movers(broker_daily, prices)
    mover_events = event_days_movers(raw, movers)
    compare_event_vs_baseline("MOVERS (broker acting in predicted direction)", mover_events, prices)

    # --- rotation pairs (opposite side) ---
    rotation = find_rotation_pairs(raw)
    rotation_events = event_days_pairs(raw, rotation, "broker_a", "broker_b", same_side=False)
    compare_event_vs_baseline("ROTATION pairs (opposite-side co-occurrence)", rotation_events, prices)

    # --- cluster pairs (same side) ---
    cluster = find_cluster_pairs(raw)
    cluster_events = event_days_pairs(raw, cluster, "broker_a", "broker_b", same_side=True)
    compare_event_vs_baseline("CLUSTER pairs (same-side co-occurrence)", cluster_events, prices)


if __name__ == "__main__":
    main()
