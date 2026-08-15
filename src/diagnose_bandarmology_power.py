"""diagnose_bandarmology_power.py -- Layer 1 signal validation for the
bandarmology features (see docs/BANDARMOLOGY_DESIGN.md, "Backtest
legitimacy plan"). Same question `diagnose_score_power.py` asks of the
V3 score: does this feature actually rank forward returns, or is it
noise? Read-only, writes nothing.

For each feature (net_flow_norm, consistency, concentration), each
trading day: rank the day's stocks into quintiles, then compare mean
forward return (close-to-close, 5/10/20 sessions) of the top vs bottom
quintile. A real signal shows top > bottom consistently across
sub-periods, not just in one lucky stretch -- same anti-fluke standard
as walk_forward_v4.py and diagnose_score_power.py's own window
breakdown (the hysteresis-band sweep is the cautionary tale for why
this matters: a single-window read passed as "validated" once, wasn't).

Close-to-close forward return, not next-session-open like
diagnose_score_power.py uses -- this is a pure signal-quality check,
there's no engine yet actually paying an entry price (see design doc,
Layer 1 vs Layer 2). Revisit if/when this becomes an actual entry rule.

STATUS 2026-08-10: first run, against PARTIAL backfilled data (2023
H1 only, backfill still running). Numbers here are a smoke test, NOT
a validated result -- rerun once the full 2023-2026 backfill lands
before trusting any conclusion, same as every other single-window
read this session has been wrong to trust.

Usage: python src/diagnose_bandarmology_power.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from config import ADTV_MIN  # noqa: E402

SUPABASE_URL = "https://soddgoonjnfclabrijtn.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNvZGRnb29uam5mY2xhYnJpanRuIiwi"
    "cm9sZSI6ImFub24iLCJpYXQiOjE3NzkwMjI3NzksImV4cCI6MjA5NDU5ODc3OX0.5Sxn0uY8TCOdFbcOPF8vxUIgezBrD-bejKuKplDF9uo"
)

HORIZONS = (5, 10, 20)
FEATURES = ("net_flow_norm", "consistency", "concentration")
N_QUANTILES = 5
N_SUBPERIODS = 3  # small-sample placeholder -- bump once full history lands


def load_prices(stock_codes: list[str], start: str, end: str) -> pd.DataFrame:
    """trade_date/stock_code/close from ihsg_eod. One query per stock code --
    a 3.5-year range is <= ~880 trading days, under the 1000-row PostgREST
    cap, so no OFFSET pagination is needed. Batching the IN-list and paging
    with OFFSET was tried first and still hit Postgres's statement timeout
    (57014): OFFSET makes Postgres scan+discard every prior row on each
    page, and that cost was still too high even at 100-stock batches. No
    ORDER BY either -- add_forward_returns sorts in pandas anyway, so
    there's no reason to pay for a DB-side sort on every request."""
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    rows = []
    for code in stock_codes:
        offset = 0
        while True:
            batch = (
                supabase.table("ihsg_eod")
                .select("trade_date,stock_code,close_price,volume")
                .eq("stock_code", code)
                .gte("trade_date", start)
                .lte("trade_date", end)
                .range(offset, offset + 999)
                .execute()
            )
            if not batch.data:
                break
            rows.extend(batch.data)
            if len(batch.data) < 1000:
                break
            offset += 1000
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df


def add_forward_returns(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    for h in HORIZONS:
        fwd_close = prices.groupby("stock_code")["close_price"].shift(-h)
        prices[f"fwd_ret_{h}d"] = fwd_close / prices["close_price"] - 1
    # Same ADTV_20 definition strategy.py already uses for V3's liquidity
    # gate (close * volume, 20-session rolling mean) -- reused here so a
    # liquidity filter on Bandarmology features means the same thing it
    # already means everywhere else in this repo, not a new definition.
    # Explicit per-group loop + concat, not groupby().apply() -- the
    # latter silently misbehaves on this pandas version, see
    # bandarmology_features.rolling_features's own comment on the same
    # footgun found earlier this session.
    parts = []
    for _, sub in prices.groupby("stock_code"):
        sub = sub.copy()
        sub["adtv_20"] = (sub["close_price"] * sub["volume"]).rolling(20, min_periods=20).mean()
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)


def quantile_spread(df: pd.DataFrame, feature: str, horizon_col: str) -> pd.Series:
    """Per-day cross-sectional quantile rank on `feature`, then mean
    forward return per quantile across all days. Returns a Series
    indexed 1 (lowest) .. N_QUANTILES (highest)."""
    def _rank_day(day_df):
        if day_df[feature].nunique() < N_QUANTILES:
            return pd.Series(np.nan, index=day_df.index)
        return pd.qcut(day_df[feature], N_QUANTILES, labels=False, duplicates="drop") + 1

    ranks = df.groupby("trade_date", group_keys=False).apply(_rank_day)
    tmp = df.assign(_q=ranks).dropna(subset=["_q", horizon_col])
    return tmp.groupby("_q")[horizon_col].mean()


def main():
    raw = bf.load_raw()
    broker_net = bf.per_broker_net(raw)
    daily = bf.daily_stock_features(broker_net)
    feats = bf.rolling_features(daily)

    # Optional: python diagnose_bandarmology_power.py 2024-01-01 -- restrict
    # to dates on/after this, e.g. to check whether a weak early-history
    # result is a regime effect or a thin-backfill data-quality effect.
    if len(sys.argv) > 1:
        min_date = pd.Timestamp(sys.argv[1]).date()
        feats = feats[feats["trade_date"] >= min_date]
        print(f"restricted to trade_date >= {min_date}")

    stock_codes = feats["stock_code"].unique().tolist()
    start = feats["trade_date"].min().isoformat()
    end = feats["trade_date"].max().isoformat()
    print(f"loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_forward_returns(prices)

    merged = feats.merge(prices, on=["trade_date", "stock_code"], how="inner")

    # Optional second arg "liquid" -- restrict to ADTV_20 >= config.ADTV_MIN,
    # same threshold V3's own liquidity gate uses (config.py). Domain
    # research (2026-08-12) flagged that OJK-documented manipulation
    # concentrates in small-cap/"gorengan" names -- same contamination risk
    # V3 already learned the hard way, worth testing here before trusting
    # a feature on the full universe.
    if len(sys.argv) > 2 and sys.argv[2] == "liquid":
        before = len(merged)
        merged = merged[merged["adtv_20"] >= ADTV_MIN]
        print(f"liquidity filter (adtv_20 >= {ADTV_MIN:,.0f}): {before} -> {len(merged)} rows")

    print(f"merged rows: {len(merged)}\n")

    dates = sorted(merged["trade_date"].unique())
    cut_points = np.linspace(0, len(dates), N_SUBPERIODS + 1, dtype=int)
    periods = [dates[cut_points[i]:cut_points[i + 1]] for i in range(N_SUBPERIODS)]

    for feature in FEATURES:
        print(f"=== {feature} ===")
        for h in HORIZONS:
            col = f"fwd_ret_{h}d"
            print(f" horizon {h}d:")
            wins = 0
            for i, period_dates in enumerate(periods):
                sub = merged[merged["trade_date"].isin(period_dates)]
                if sub.empty:
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
