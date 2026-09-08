"""scratch_market_flow_build.py -- SCRATCH/RESEARCH ONLY, not wired into any live
path. Builds a daily market-wide broker net-flow feature from the local Parquet
archive (data/bandarmology_history/**/*.parquet) and sanity-checks it, per the
council's "market-wide aggregate broker-flow regime signal" research candidate.

Two variants computed, both scale-free (net / turnover, bounded ~[-1,1]):
  - liquid_net_ratio: restricted to the SAME liquid universe score_candidates()
    already screens to (adtv_20 >= cfg.ADTV_MIN, using df's own adtv_20 column,
    same-day, no lookahead -- adtv_20 is already a trailing rolling mean).
  - full_net_ratio: every stock_code in the archive, no liquidity filter --
    kept only as a robustness comparison, not the primary candidate (illiquid
    penny-stock flow is plausibly just noise, per the task brief's own hint).

Run directly: python src/scratch_market_flow_build.py
"""
import pickle
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

import config as cfg
from bandarmology_features import filter_corrupt_rows, PRICE_BAND_LO, PRICE_BAND_HI  # noqa: F401

DATA_DIR = "data/bandarmology_history"
CACHE_PATH = ".cache/walk_forward_data_2021-01-01_2026-06-30.pkl"


def load_broker_raw() -> pd.DataFrame:
    """Column-projected pyarrow scan over the whole archive -- ~3s for 18.8M
    raw rows, no per-file python loop. Keeps lot/avg_price (needed by
    filter_corrupt_rows) alongside val_rupiah."""
    dataset = ds.dataset(DATA_DIR, format="parquet")
    raw = dataset.to_table(columns=["stock_code", "side", "lot", "avg_price", "val_rupiah", "trade_date"]).to_pandas()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.date
    return raw


def net_by_stock_day(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per (trade_date, stock_code): net_val (buy - sell, Rupiah),
    turnover_val (buy + sell, Rupiah)."""
    g = raw.groupby(["trade_date", "stock_code", "side"])["val_rupiah"].sum().unstack("side", fill_value=0.0)
    g["net_val"] = g.get("buy", 0.0) - g.get("sell", 0.0)
    g["turnover_val"] = g.get("buy", 0.0) + g.get("sell", 0.0)
    return g.reset_index()[["trade_date", "stock_code", "net_val", "turnover_val"]]


def local_eod_reference(df: pd.DataFrame) -> pd.DataFrame:
    """Same shape bandarmology_features.load_eod_bands() returns (stock_code,
    trade_date, high, low, volume), built from the ALREADY-FETCHED backtest
    dataset in memory instead of a fresh per-stock Supabase round trip --
    same sanitizing (a 0/missing high or low is itself missing data, not a
    real Rp0 print, matching the V3_FINDINGS_LOG open_price=0 audit) that
    load_eod_bands applies, just sourced locally."""
    eod = df[["stock_code", "trade_date", "high", "low", "volume"]].drop_duplicates(["stock_code", "trade_date"]).copy()
    eod["high"] = eod["high"].where(eod["high"] > 0, df["close_price"])
    eod["low"] = eod["low"].where((eod["low"] > 0) & (eod["low"] <= eod["high"]), df["close_price"])
    return eod


def build_market_flow_ratios(apply_corrupt_filter: bool = True) -> pd.DataFrame:
    """Returns a date-indexed DataFrame: liquid_net_ratio, full_net_ratio,
    liquid_n_stocks, full_n_stocks, liquid_turnover, full_turnover.

    apply_corrupt_filter=True (default): drops broker rows whose avg_price/lot
    can't be reconciled against the real ihsg_eod print, using the ALREADY-
    FETCHED backtest dataset as the local reference (no network round trip) --
    same filter bandarmology_push_daily.py's load_raw_clean() applies for the
    live site, done here without needing a fresh per-stock Supabase fetch."""
    raw = load_broker_raw()

    with open(CACHE_PATH, "rb") as f:
        df, _idx_df = pickle.load(f)

    if apply_corrupt_filter:
        eod_ref = local_eod_reference(df)
        raw = filter_corrupt_rows(raw, eod_ref)

    broker = net_by_stock_day(raw)
    adtv = df[["trade_date", "stock_code", "adtv_20"]].drop_duplicates(["trade_date", "stock_code"])

    merged = broker.merge(adtv, on=["trade_date", "stock_code"], how="left")
    liquid = merged[merged["adtv_20"] >= cfg.ADTV_MIN]

    def agg(sub, prefix):
        g = sub.groupby("trade_date").agg(
            net=("net_val", "sum"), turnover=("turnover_val", "sum"), n=("stock_code", "nunique"))
        g[f"{prefix}_net_ratio"] = g["net"] / g["turnover"].replace(0, np.nan)
        return g.rename(columns={"net": f"{prefix}_net", "turnover": f"{prefix}_turnover",
                                  "n": f"{prefix}_n_stocks"})

    liq_g = agg(liquid, "liquid")
    full_g = agg(merged, "full")
    out = liq_g.join(full_g, how="outer").sort_index()
    return out


def sanity_check(out: pd.DataFrame):
    print(f"date range: {out.index.min()} .. {out.index.max()}, {len(out)} trading days")
    for col in ["liquid_net_ratio", "full_net_ratio"]:
        s = out[col].dropna()
        print(f"\n--- {col} (n={len(s)}, nulls={out[col].isna().sum()}) ---")
        print(s.describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]).to_string())

    print("\n--- liquid universe size per day ---")
    print(out["liquid_n_stocks"].describe().to_string())

    print("\n--- outlier-day check: does 1-2 days dominate the whole series? ---")
    liq_abs = out["liquid_net"].abs().dropna().sort_values(ascending=False)
    total_abs = out["liquid_net"].abs().sum()
    top5_share = liq_abs.head(5).sum() / total_abs
    print(f"top-5 |net| days share of total |net|: {top5_share:.1%} (n={len(liq_abs)} days total)")
    print(liq_abs.head(5))

    print("\n--- days with liquid_net_ratio null (adtv_20 not yet available / no liquid stock) ---")
    print(out[out["liquid_net_ratio"].isna()].index.min(), "..", out[out["liquid_net_ratio"].isna()].index.max()
          if out["liquid_net_ratio"].isna().any() else "none")


if __name__ == "__main__":
    out = build_market_flow_ratios()
    out.to_pickle(".cache/market_flow_ratios.pkl")
    print("[OK] saved .cache/market_flow_ratios.pkl")
    sanity_check(out)
