"""bandarmology_broker_profile.py -- prototype "which broker actually
moves this stock" detector (see docs/BANDARMOLOGY_DESIGN.md, "Per-broker-
per-stock behavior profile"). User's framing: "saham A itu penggeraknya
Broker A dan B" -- stock-specific, not a universal broker property, and
must be LEARNED from history, not assumed from folklore.

For each (broker_code, stock_code) pair with enough active history:
tests whether that broker's daily net_lot at day t has a real lagged
relationship with the stock's OWN forward return (t+1..t+H), using a
simple correlation. Split the sample in half chronologically and
require the sign/strength to hold in BOTH halves before calling a
broker a "candidate mover" for that stock -- same anti-fluke standard
as everything else this session (one-half agreement is exactly the kind
of single-window read that turned out wrong before).

STATUS 2026-08-10: prototype against ~9 months of partial local data
(2023 H1-H2 so far, backfill still running). Too little history yet for
a real per-pair significance test (need enough active days per broker
per stock) -- this is infrastructure + a first look, not a validated
mover list. Rerun once the full 2023-2026 backfill lands.

Usage: python src/bandarmology_broker_profile.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from diagnose_bandarmology_power import SUPABASE_URL, SUPABASE_ANON_KEY, load_prices, add_forward_returns  # noqa: E402

MIN_ACTIVE_DAYS = 20  # a broker needs to show up at least this often for a stock before testing it
FORWARD_HORIZON = 5
MIN_ABS_CORR = 0.15  # candidate threshold -- not a validated cutoff, a first filter


def per_broker_daily(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per (trade_date, stock_code, broker_code) with net_lot --
    reuses bandarmology_features.per_broker_net, just keeps the broker
    dimension instead of summing it away."""
    return bf.per_broker_net(raw)[["trade_date", "stock_code", "broker_code", "net_lot"]]


def candidate_movers(broker_daily: pd.DataFrame, fwd_ret: pd.DataFrame) -> pd.DataFrame:
    merged = broker_daily.merge(fwd_ret, on=["trade_date", "stock_code"], how="inner")
    merged = merged.dropna(subset=[f"fwd_ret_{FORWARD_HORIZON}d"])

    results = []
    for (stock_code, broker_code), sub in merged.groupby(["stock_code", "broker_code"]):
        sub = sub.sort_values("trade_date")
        if len(sub) < MIN_ACTIVE_DAYS:
            continue
        mid = len(sub) // 2
        first_half, second_half = sub.iloc[:mid], sub.iloc[mid:]
        if first_half["net_lot"].nunique() < 3 or second_half["net_lot"].nunique() < 3:
            continue
        corr_1 = first_half["net_lot"].corr(first_half[f"fwd_ret_{FORWARD_HORIZON}d"])
        corr_2 = second_half["net_lot"].corr(second_half[f"fwd_ret_{FORWARD_HORIZON}d"])
        if pd.isna(corr_1) or pd.isna(corr_2):
            continue
        same_sign = (corr_1 > 0) == (corr_2 > 0)
        both_strong = abs(corr_1) >= MIN_ABS_CORR and abs(corr_2) >= MIN_ABS_CORR
        results.append({
            "stock_code": stock_code, "broker_code": broker_code,
            "active_days": len(sub), "corr_first_half": corr_1, "corr_second_half": corr_2,
            "same_sign": same_sign, "candidate_mover": same_sign and both_strong,
        })
    return pd.DataFrame(results)


def main():
    raw = bf.load_raw()
    broker_daily = per_broker_daily(raw)

    stock_codes = broker_daily["stock_code"].unique().tolist()
    start = raw["trade_date"].min().isoformat()
    end = raw["trade_date"].max().isoformat()
    print(f"loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_forward_returns(prices)

    out = candidate_movers(broker_daily, prices)
    print(f"\npairs tested (>= {MIN_ACTIVE_DAYS} active days): {len(out)}")
    print(f"candidate movers (same-sign both halves, |corr| >= {MIN_ABS_CORR} both halves): "
          f"{out['candidate_mover'].sum()}")

    top = out[out["candidate_mover"]].sort_values("active_days", ascending=False).head(20)
    print("\ntop candidates by active_days:")
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()
