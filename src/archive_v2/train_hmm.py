"""
train_hmm.py — V2 offline training script (manual trigger only).

Fits per-stock HMM regime models on the TRAIN split of historical data and
uploads frozen artifacts to Supabase Storage. Never run automatically by
any GitHub Actions workflow — rerun manually to produce a new HMM_VERSION
(bump config.HMM_VERSION first so the new artifacts don't overwrite the
previous, still-in-use version).

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/train_hmm.py
"""

import os
import sys
from datetime import date

import config as cfg
import data_fetch
import hmm_model
from strategy import add_features
from supabase import create_client

TRAIN_START = date.fromisoformat(os.environ.get("BACKTEST_START", "2021-01-01"))
TRAIN_END = date.fromisoformat(os.environ.get("BACKTEST_END", "2026-06-30"))


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print(f"[TRAIN_HMM] Fetching {TRAIN_START} .. {TRAIN_END} ...")
    df, idx_df = data_fetch.fetch_data(supabase, TRAIN_START, TRAIN_END)

    trading_days = sorted(
        d for d in df[(df["trade_date"] >= TRAIN_START) & (df["trade_date"] <= TRAIN_END)]["trade_date"].unique()
    )
    split_date = hmm_model.compute_train_test_split(trading_days, cfg.HMM_TRAIN_SPLIT_PCT)
    n_train_days = sum(1 for d in trading_days if d <= split_date)
    print(f"[TRAIN_HMM] Train split: {trading_days[0]} .. {split_date} ({n_train_days} days)")
    print(f"[TRAIN_HMM] Held-out test window (not used for fitting): "
          f"{split_date} .. {trading_days[-1]} ({len(trading_days) - n_train_days} days)")

    stock_codes = df["stock_code"].unique()
    fitted, skipped_liquidity, skipped_history = 0, 0, 0

    for sc in stock_codes:
        group = add_features(df[df["stock_code"] == sc].copy())
        train_rows = group[group["trade_date"] <= split_date]

        if train_rows.empty or train_rows["adtv_20"].tail(20).mean() < cfg.ADTV_MIN:
            skipped_liquidity += 1
            continue

        artifact = hmm_model.fit_stock_hmm(train_rows, cfg.HMM_MIN_HISTORY_DAYS)
        if artifact is None:
            skipped_history += 1
            continue

        hmm_model.save_artifact(supabase, cfg.HMM_BUCKET, cfg.HMM_VERSION, sc, artifact)
        fitted += 1

    print(f"\n[TRAIN_HMM] Done. Fitted {fitted} models, "
          f"skipped {skipped_liquidity} (illiquid), {skipped_history} (insufficient/non-convergent history), "
          f"out of {len(stock_codes)} total tickers. Version: {cfg.HMM_VERSION}")


if __name__ == "__main__":
    main()
