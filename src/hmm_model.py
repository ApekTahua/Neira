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
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

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


def fit_stock_hmm(feature_df: pd.DataFrame, min_history_days: int, random_state: int = 42) -> dict | None:
    """Fits StandardScaler + 3-state GaussianHMM on feature_df's
    HMM_FEATURES columns. Returns None if there isn't enough clean data or
    the model fails to converge. feature_df should already be restricted
    to the train-split rows for this stock."""
    clean = feature_df.dropna(subset=HMM_FEATURES)
    if len(clean) < min_history_days:
        return None

    X = clean[HMM_FEATURES].to_numpy()
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Single-restart EM is known to land in bad local optima depending on
    # initialization. Multi-restart (keep the highest-log-likelihood
    # converged fit) is standard practice for Gaussian mixture/HMM fitting
    # — the same principle sklearn's own KMeans(n_init=10) uses internally.
    # Restarts are seeded deterministically from `random_state` so the
    # overall fit stays fully reproducible.
    rng = np.random.default_rng(random_state)
    n_restarts = 10
    model = None
    best_score = -np.inf
    for _ in range(n_restarts):
        seed = int(rng.integers(0, 2**31 - 1))
        candidate = GaussianHMM(
            n_components=3,
            covariance_type="diag",
            n_iter=100,
            random_state=seed,
        )
        try:
            candidate.fit(X_scaled)
            if not candidate.monitor_.converged:
                continue
            score = candidate.score(X_scaled)
        except Exception:
            continue
        if not np.isfinite(score):
            continue
        if score > best_score:
            best_score = score
            model = candidate

    if model is None:
        return None

    # Rank hidden states by fitted mean return (index 0 = hmm_return).
    # StandardScaler applies a positive-slope affine transform per feature,
    # so ranking in scaled space preserves the true ascending order.
    mean_returns = model.means_[:, 0]
    order = np.argsort(mean_returns)  # ascending: BEARISH, SIDEWAYS, BULLISH
    state_label_map = {int(state_idx): STATE_LABELS[rank] for rank, state_idx in enumerate(order)}

    return {"scaler": scaler, "model": model, "state_label_map": state_label_map}


def infer_hmm_state(feature_df: pd.DataFrame, artifact: dict | None) -> pd.Series:
    """Returns a Series aligned to feature_df.index with the dominant HMM
    state label per row ("BEARISH"/"SIDEWAYS"/"BULLISH"). Rows that can't
    be scored (no frozen artifact, or missing features for that row) get
    "NO_MODEL"."""
    if artifact is None:
        return pd.Series("NO_MODEL", index=feature_df.index)

    result = pd.Series("NO_MODEL", index=feature_df.index)
    clean_mask = feature_df[HMM_FEATURES].notna().all(axis=1)
    clean = feature_df.loc[clean_mask, HMM_FEATURES]
    if clean.empty:
        return result

    X_scaled = artifact["scaler"].transform(clean.to_numpy())
    state_seq = artifact["model"].predict(X_scaled)
    labels = [artifact["state_label_map"][s] for s in state_seq]
    result.loc[clean.index] = labels
    return result


def artifact_path(version: str, stock_code: str) -> str:
    return f"v2/{version}/{stock_code}.pkl"


def save_artifact(supabase, bucket: str, version: str, stock_code: str, artifact: dict) -> None:
    blob = pickle.dumps(artifact)
    supabase.storage.from_(bucket).upload(
        artifact_path(version, stock_code),
        blob,
        {"content-type": "application/octet-stream", "upsert": "true"},
    )


def load_artifact(supabase, bucket: str, version: str, stock_code: str) -> dict | None:
    try:
        blob = supabase.storage.from_(bucket).download(artifact_path(version, stock_code))
    except Exception:
        return None
    return pickle.loads(blob)


def load_all_artifacts(supabase, bucket: str, version: str) -> dict:
    """Loads every artifact under v2/{version}/ into {stock_code: artifact}."""
    prefix = f"v2/{version}"
    files = supabase.storage.from_(bucket).list(prefix)
    artifacts = {}
    for f in files:
        name = f["name"]
        if not name.endswith(".pkl"):
            continue
        stock_code = name[: -len(".pkl")]
        blob = supabase.storage.from_(bucket).download(f"{prefix}/{name}")
        artifacts[stock_code] = pickle.loads(blob)
    return artifacts
