"""
phase0b_foreign_flow_validation.py — does foreign net-flow (foreign_buy -
foreign_sell) predict forward return, independent of the squeeze pattern
that Phase 0 already showed has no edge on liquid stocks?

Two separate questions, kept separate on purpose:
  1. STANDALONE: bucket foreign_net_ma into quintiles across ALL bars for
     liquid stocks (no squeeze precondition) — does higher foreign buying
     predict higher forward return on its own?
  2. WITHIN-TRIGGER: same quintile bucketing but restricted to bars that
     already pass the squeeze+vol-spike trigger from Phase 0 — does
     foreign flow discriminate winners from losers *inside* the signal
     V1 already gates/scores on foreign flow for? This is the population
     V1's FOREIGN_NET_MIN filter + foreign_score actually act on.

Bias check included: foreign_net_ma is a trailing (same-day-inclusive)
average, so it carries no lookahead — but it could still be a LAGGING
indicator (foreign investors buying into a stock that already moved) rather
than a LEADING one. To tell these apart we also correlate foreign_net_ma
against the trailing 5-day return; if that correlation is much stronger
than the forward-return correlation, foreign flow is coincident/lagging,
not predictive.

Read-only, no Supabase writes, no portfolio simulation.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0b_foreign_flow_validation.py
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

START = date.fromisoformat(os.environ.get("PHASE0_START", "2021-01-01"))
END = date.fromisoformat(os.environ.get("PHASE0_END", "2026-06-30"))


def attach_regime(df: pd.DataFrame, idx_df: pd.DataFrame) -> pd.DataFrame:
    idx_sorted = idx_df.dropna(subset=["ma50"]).sort_values("trade_date").copy()
    idx_sorted["regime"] = np.select(
        [idx_sorted["close"] > idx_sorted["ma50"], idx_sorted["close"] < idx_sorted["ma50"]],
        ["BULLISH", "BEARISH"],
        default="NEUTRAL",
    )
    idx_sorted["_dt"] = pd.to_datetime(idx_sorted["trade_date"])
    df = df.sort_values("trade_date").copy()
    df["_dt"] = pd.to_datetime(df["trade_date"])
    df = pd.merge_asof(df, idx_sorted[["_dt", "regime"]], on="_dt", direction="backward")
    df = df.drop(columns=["_dt"])
    df["regime"] = df["regime"].fillna("NEUTRAL")
    return df


def attach_trailing_return(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    g = df.groupby("stock_code")["close_price"]
    df[f"trail_ret_{n}"] = df["close_price"] / g.shift(n) - 1
    return df


def quintile_summary(df: pd.DataFrame, value_col: str, group_cols: list[str]) -> pd.DataFrame:
    def bucket(sub: pd.DataFrame) -> pd.DataFrame:
        sub = sub.dropna(subset=[value_col]).copy()
        try:
            sub["quintile"] = pd.qcut(sub[value_col], 5, labels=[f"Q{i+1}(low)" if i == 0 else (f"Q{i+1}(high)" if i == 4 else f"Q{i+1}") for i in range(5)], duplicates="drop")
        except ValueError:
            return pd.DataFrame()
        out = []
        for q, g in sub.groupby("quintile", observed=True):
            row = {"quintile": q, "n": len(g), f"{value_col}_median": round(g[value_col].median(), 4)}
            for h in HORIZONS:
                r = g[f"fwd_ret_{h}"].dropna()
                if r.empty:
                    continue
                row[f"win_rate_{h}d"] = round((r > 0).mean() * 100, 1)
                row[f"mean_ret_{h}d"] = round(r.mean() * 100, 2)
                row[f"median_ret_{h}d"] = round(r.median() * 100, 2)
            out.append(row)
        return pd.DataFrame(out)

    if not group_cols:
        return bucket(df)

    rows = []
    for key, sub in df.groupby(group_cols):
        key = key if isinstance(key, tuple) else (key,)
        t = bucket(sub)
        if t.empty:
            continue
        for i, c in enumerate(group_cols):
            t.insert(i, c, key[i])
        rows.append(t)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def spearman_report(df: pd.DataFrame, value_col: str, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    groups = df.groupby(group_cols) if group_cols else [((), df)]
    for key, sub in groups:
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key))
        row["n"] = len(sub)
        row[f"corr_{value_col}_vs_trail_ret_5"] = None
        trail = sub[[value_col, "trail_ret_5"]].dropna()
        if len(trail) >= 30:
            row[f"corr_{value_col}_vs_trail_ret_5"] = round(trail[value_col].corr(trail["trail_ret_5"], method="spearman"), 4)
        for h in HORIZONS:
            fwd = sub[[value_col, f"fwd_ret_{h}"]].dropna()
            row[f"corr_fwd_{h}d"] = round(fwd[value_col].corr(fwd[f"fwd_ret_{h}"], method="spearman"), 4) if len(fwd) >= 30 else None
        rows.append(row)
    return pd.DataFrame(rows)


def print_table(title: str, table: pd.DataFrame):
    print("\n" + "=" * 110)
    print(title)
    print("=" * 110)
    print("(no data)" if table.empty else table.to_string(index=False))


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 110)
    print("PHASE 0b — Foreign net-flow: standalone predictive power + lag/lead check")
    print(f"Window: {START} .. {END}")
    print("=" * 110)

    print("[FETCH] Downloading data ...")
    df, idx_df = data_fetch.fetch_data(supabase, START, END)

    print("[FEATURE] Computing indicators ...")
    frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
    df = pd.concat(frames, ignore_index=True)

    print("[FORWARD] Computing forward + trailing returns ...")
    df = attach_forward_returns(df)
    df = attach_trailing_return(df, 5)
    df = attach_regime(df, idx_df)

    required = ["avg_vol_20", "foreign_net_ma"]
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
    print(f"[POPULATION] {len(clean)} clean bars total, {len(liquid)} liquid-tier bars.")

    # --- Q1: standalone predictive power, liquid stocks, ALL bars (no squeeze precondition) ---
    print_table("Q1a — LIQUID STOCKS, ALL BARS: foreign_net_ma quintile -> forward return", quintile_summary(liquid, "foreign_net_ma", []))
    print_table("Q1b — LIQUID STOCKS, ALL BARS, BY REGIME: foreign_net_ma quintile -> forward return", quintile_summary(liquid, "foreign_net_ma", ["regime"]))
    print_table("Q1c — Spearman correlation: foreign_net_ma vs forward return (liquid, by regime) + vs trailing 5d return (lag/lead check)", spearman_report(liquid, "foreign_net_ma", ["regime"]))

    # --- Q2: within the already-triggered squeeze population, does foreign flow discriminate? ---
    triggers = find_triggers(df)
    triggers = triggers.merge(
        clean[["stock_code", "trade_date", "liquidity_tier"]],
        on=["stock_code", "trade_date"], how="inner",
    )
    triggers_liquid = triggers[triggers["liquidity_tier"] == "liquid(>=1B)"]
    print(f"\n[POPULATION] {len(triggers)} squeeze-trigger bars, {len(triggers_liquid)} of those liquid-tier.")
    print_table("Q2 — WITHIN SQUEEZE TRIGGERS, LIQUID STOCKS: foreign_net_ma quintile -> forward return", quintile_summary(triggers_liquid, "foreign_net_ma", []))


if __name__ == "__main__":
    main()
