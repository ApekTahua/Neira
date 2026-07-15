"""
hmm_model.py — Per-stock HMM regime detection (V2).

Fits a 3-state Gaussian HMM per stock on (return, range, log_volume_change)
features. States are unordered by hmmlearn; states are ranked by fitted
mean return and labeled BEARISH/SIDEWAYS/BULLISH. Frozen artifacts (scaler
+ model + label map) are persisted to Supabase Storage and never refit
outside train_hmm.py — screener_v2.py and backtest_v2.py only load and
infer.
"""

import pickle

import numpy as np
import pandas as pd

HMM_FEATURES = ["hmm_return", "hmm_range", "hmm_log_vol_change"]
STATE_LABELS = ["BEARISH", "SIDEWAYS", "BULLISH"]  # rank order by mean return


def compute_hmm_features(group: pd.DataFrame) -> pd.DataFrame:
    """Adds hmm_return/hmm_range/hmm_log_vol_change columns. `group` must
    already be sorted by trade_date and have close_price, high, low,
    volume columns."""
    group = group.copy()
    group["hmm_return"] = group["close_price"].pct_change()

    high = group["high"].where(group["high"] > 0, group["close_price"])
    high = high.where(high >= group["close_price"], group["close_price"])
    low = group["low"].where((group["low"] > 0) & (group["low"] <= high), group["close_price"])
    group["hmm_range"] = (high - low) / group["close_price"]

    vol_prev = group["volume"].shift(1).clip(lower=1)
    vol = group["volume"].clip(lower=1)
    group["hmm_log_vol_change"] = np.log(vol / vol_prev)

    return group


def compute_train_test_split(trading_days: list, train_pct: float = 0.7):
    """Returns the last date belonging to the train split (inclusive).
    Days strictly after this date are the test split. trading_days must be
    a sorted list of unique date objects."""
    if len(trading_days) < 2:
        raise ValueError("Need at least 2 trading days to split")
    split_idx = int(len(trading_days) * train_pct)
    split_idx = max(1, min(split_idx, len(trading_days) - 1))
    return trading_days[split_idx - 1]
