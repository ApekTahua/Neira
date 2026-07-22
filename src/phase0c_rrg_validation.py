"""
phase0c_rrg_validation.py — does sector relative strength (RRG-style
rotation) predict forward return, independent of the squeeze pattern?

Proxy for the RS-Momentum axis of a classic JdK Relative Rotation Graph,
kept to the minimum that's testable without a full quadrant model:
  sector_rel_strength(t)  = sector_index_close(t) / COMPOSITE_close(t)
  sector_rs_momentum(t)   = sector_rel_strength(t) / sector_rel_strength(t-20) - 1

Positive rs_momentum = the stock's sector has been strengthening vs the
market over the last 20 trading days ("leading/improving" quadrant of a
real RRG). Same two questions as Phase 0b, same discipline:
  1. STANDALONE: liquid stocks, ALL bars — quintile sector_rs_momentum,
     check if forward return rises Q1->Q5.
  2. WITHIN-TRIGGER: same, restricted to squeeze-trigger bars.

Sector mapping comes from stock_profiles.sector (Indonesian OJK/IDX
sector names) mapped to the matching IDX sector index code in index_eod.
Stocks with no profile row are dropped from this analysis only.

Read-only, no Supabase writes, no portfolio simulation.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0c_rrg_validation.py
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd
from supabase import create_client

import config as cfg
import data_fetch
from strategy import add_features
from phase0_signal_validation import HORIZONS, attach_forward_returns, find_triggers
from phase0b_foreign_flow_validation import attach_regime, attach_trailing_return, quintile_summary, spearman_report, print_table

START = date.fromisoformat(os.environ.get("PHASE0_START", "2021-01-01"))
END = date.fromisoformat(os.environ.get("PHASE0_END", "2026-06-30"))

# stock_profiles.sector (Indonesian IDX-IC names) -> index_eod.index_code
SECTOR_TO_INDEX = {
    "Barang Baku": "IDXBASIC",
    "Barang Konsumen Non-Primer": "IDXCYCLIC",
    "Barang Konsumen Primer": "IDXNONCYC",
    "Energi": "IDXENERGY",
    "Infrastruktur": "IDXINFRA",
    "Kesehatan": "IDXHEALTH",
    "Keuangan": "IDXFINANCE",
    "Perindustrian": "IDXINDUST",
    "Properti & Real Estat": "IDXPROPERT",
    "Teknologi": "IDXTECHNO",
    "Transportasi & Logistik": "IDXTRANS",
}


def fetch_sector_indices(supabase, start_date: date, end_date: date) -> pd.DataFrame:
    codes = list(SECTOR_TO_INDEX.values()) + ["COMPOSITE"]
    rows = []
    for code in codes:
        offset = 0
        while True:
            batch = (
                supabase.table("index_eod")
                .select("trade_date,close")
                .eq("index_code", code)
                .gte("trade_date", start_date.isoformat())
                .lte("trade_date", end_date.isoformat())
                .order("trade_date")
                .range(offset, offset + 999)
                .execute()
            )
            if not batch.data:
                break
            for r in batch.data:
                rows.append({"index_code": code, "trade_date": r["trade_date"], "close": r["close"]})
            offset += 1000
    wide = pd.DataFrame(rows)
    wide["trade_date"] = pd.to_datetime(wide["trade_date"]).dt.date
    wide["close"] = pd.to_numeric(wide["close"], errors="coerce")
    return wide.pivot(index="trade_date", columns="index_code", values="close").sort_index()


def fetch_sector_map(supabase) -> dict:
    rows = []
    offset = 0
    while True:
        batch = supabase.table("stock_profiles").select("ticker,sector").range(offset, offset + 999).execute()
        if not batch.data:
            break
        rows.extend(batch.data)
        offset += 1000
    mapping = {}
    for r in rows:
        idx_code = SECTOR_TO_INDEX.get(r["sector"])
        if idx_code:
            mapping[r["ticker"]] = idx_code
    return mapping


def compute_rs_momentum(sector_wide: pd.DataFrame) -> pd.DataFrame:
    """Long-format: trade_date, index_code, rs_momentum (20d rate of change of sector/COMPOSITE ratio)."""
    rel = sector_wide.div(sector_wide["COMPOSITE"], axis=0)
    rs_mom = rel.div(rel.shift(20)) - 1
    rs_mom = rs_mom.drop(columns=["COMPOSITE"])
    long = rs_mom.reset_index().melt(id_vars="trade_date", var_name="index_code", value_name="sector_rs_momentum")
    return long


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 110)
    print("PHASE 0c — Sector RRG relative strength: standalone predictive power")
    print(f"Window: {START} .. {END}")
    print("=" * 110)

    print("[FETCH] Downloading stock + index data ...")
    df, idx_df = data_fetch.fetch_data(supabase, START, END)

    print("[FETCH] Downloading sector indices + stock->sector map ...")
    sector_wide = fetch_sector_indices(supabase, START, END)
    sector_map = fetch_sector_map(supabase)
    print(f"[MAP] {len(sector_map)} stocks mapped to a sector index.")

    print("[FEATURE] Computing indicators ...")
    frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
    df = pd.concat(frames, ignore_index=True)

    print("[RRG] Computing sector RS-momentum ...")
    rs_long = compute_rs_momentum(sector_wide)
    df["index_code"] = df["stock_code"].map(sector_map)
    df = df.merge(rs_long, on=["trade_date", "index_code"], how="left")

    print("[FORWARD] Computing forward + trailing returns, regime ...")
    df = attach_forward_returns(df)
    df = attach_trailing_return(df, 5)
    df = attach_regime(df, idx_df)

    required = ["avg_vol_20", "sector_rs_momentum"]
    clean = df.dropna(subset=required).copy()
    sleeping = (
        (clean["close_price"] <= cfg.SLEEPING_PRICE)
        & (clean["rolling_min_close"] == cfg.SLEEPING_PRICE)
        & (clean["rolling_max_close"] == cfg.SLEEPING_PRICE)
    )
    illiquid = clean["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL
    clean = clean[~(sleeping | illiquid)]
    clean["liquidity_tier"] = np.where(clean["adtv_20"] >= cfg.ADTV_MIN, "liquid(>=1B)", "microcap(<1B)")

    liquid = clean[clean["liquidity_tier"] == "liquid(>=1B)"]
    print(f"[POPULATION] {len(clean)} clean bars with sector mapping, {len(liquid)} liquid-tier.")

    print_table("Q1a — LIQUID STOCKS, ALL BARS: sector_rs_momentum quintile -> forward return", quintile_summary(liquid, "sector_rs_momentum", []))
    print_table("Q1b — LIQUID STOCKS, ALL BARS, BY REGIME: sector_rs_momentum quintile -> forward return", quintile_summary(liquid, "sector_rs_momentum", ["regime"]))
    print_table("Q1c — Spearman correlation: sector_rs_momentum vs forward return (liquid, by regime) + vs trailing 5d return (lag/lead check)", spearman_report(liquid, "sector_rs_momentum", ["regime"]))

    triggers = find_triggers(df)
    triggers = triggers.merge(
        clean[["stock_code", "trade_date", "liquidity_tier"]],
        on=["stock_code", "trade_date"], how="inner",
    )
    triggers_liquid = triggers[triggers["liquidity_tier"] == "liquid(>=1B)"]
    print(f"\n[POPULATION] {len(triggers)} squeeze-trigger bars, {len(triggers_liquid)} of those liquid-tier with sector mapping.")
    print_table("Q2 — WITHIN SQUEEZE TRIGGERS, LIQUID STOCKS: sector_rs_momentum quintile -> forward return", quintile_summary(triggers_liquid, "sector_rs_momentum", []))


if __name__ == "__main__":
    main()
