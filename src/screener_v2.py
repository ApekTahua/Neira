"""
screener_v2.py — V2 live screener (validation only). Prints today's
V2-gated signals (ADTV liquidity + per-stock HMM confirmation + existing
technical conditions) to the console for manual comparison against V1's
Telegram output.

Does NOT send Telegram messages and does NOT write to screener_results or
any other production table — V1's screener.py remains the only live
production path until V2 is explicitly approved.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/screener_v2.py
"""

import os
import sys

import pandas as pd
from supabase import create_client

import config as cfg
import data_fetch
import hmm_model
from strategy import add_features, get_regime, get_regime_params, get_signals


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    latest_date_res = supabase.table("ihsg_eod").select("trade_date").order("trade_date", desc=True).limit(1).execute()
    if not latest_date_res.data:
        sys.exit("No data in ihsg_eod")
    latest_date = pd.Timestamp(latest_date_res.data[0]["trade_date"]).date()

    print(f"[SCREENER V2] Latest market date: {latest_date}")
    df, idx_df = data_fetch.fetch_data(supabase, latest_date, latest_date, lookback_days=cfg.LOOKBACK_DAYS)

    artifacts = hmm_model.load_all_artifacts(supabase, cfg.HMM_BUCKET, cfg.HMM_VERSION)
    print(f"[SCREENER V2] Loaded {len(artifacts)} HMM models (version {cfg.HMM_VERSION})")

    market_label = get_regime(idx_df, latest_date)
    regime_params = get_regime_params(market_label)
    print(f"[SCREENER V2] IHSG Regime: {market_label}")

    stock_codes = df["stock_code"].unique()
    frames = []
    for sc in stock_codes:
        group = add_features(df[df["stock_code"] == sc].copy())
        group["hmm_state"] = hmm_model.infer_hmm_state(group, artifacts.get(sc))
        frames.append(group)
    df = pd.concat(frames, ignore_index=True)

    day_data = df[df["trade_date"] == latest_date].copy()
    signals = get_signals(
        day_data, regime_params["confidence_min"], regime_params["min_conditions"],
        adtv_min=cfg.ADTV_MIN, hmm_gate=True,
    )

    if signals.empty:
        print("\n[SCREENER V2] No V2-gated candidates today.")
        return

    top10 = signals.head(10)
    print("\n" + "=" * 70)
    print(f"{'TOP V2 CANDIDATES (HMM-confirmed)':^70}")
    print("=" * 70)
    print(f"{'Stock':<8} {'Conf':>7} {'Buy Zone':>16} {'TP':>10} {'SL':>10} {'HMM':>10}")
    print("-" * 70)
    for _, row in top10.iterrows():
        print(f"{row['stock_code']:<8} {row['confidence']:>6.1f}% "
              f"{row['buy_zone']:>16} {row['tp_target']:>10} {row['sl_target']:>10} {row['hmm_state']:>10}")
    print("-" * 70)


if __name__ == "__main__":
    main()
