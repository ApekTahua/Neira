from datetime import date

import numpy as np
import pandas as pd
import pytest

import hmm_model


def _synthetic_ohlcv(n=10):
    dates = pd.date_range("2024-01-01", periods=n, freq="D").date
    close = [100.0, 102.0, 101.0, 105.0, 110.0, 108.0, 112.0, 115.0, 114.0, 120.0]
    return pd.DataFrame({
        "trade_date": dates,
        "close_price": close,
        "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close],
        "volume": [1000, 1200, 900, 1500, 2000, 1800, 2200, 2500, 2100, 3000],
    })


def test_compute_hmm_features_columns_exist():
    df = hmm_model.compute_hmm_features(_synthetic_ohlcv())
    assert set(hmm_model.HMM_FEATURES).issubset(df.columns)


def test_compute_hmm_features_return_values():
    df = hmm_model.compute_hmm_features(_synthetic_ohlcv())
    # close_price[1]/close_price[0] - 1 = 102/100 - 1 = 0.02
    assert df["hmm_return"].iloc[1] == pytest.approx(0.02)
    assert pd.isna(df["hmm_return"].iloc[0])


def test_compute_hmm_features_range_values():
    df = hmm_model.compute_hmm_features(_synthetic_ohlcv())
    # high=101.0, low=99.0, close=100.0 -> range = (101-99)/100 = 0.02
    assert df["hmm_range"].iloc[0] == pytest.approx(0.02, abs=1e-6)


def test_compute_hmm_features_log_vol_change():
    df = hmm_model.compute_hmm_features(_synthetic_ohlcv())
    # volume[1]/volume[0] = 1200/1000 = 1.2 -> log(1.2)
    assert df["hmm_log_vol_change"].iloc[1] == pytest.approx(np.log(1.2))
    assert pd.isna(df["hmm_log_vol_change"].iloc[0])


def test_compute_train_test_split_basic():
    days = [date(2024, 1, d) for d in range(1, 11)]  # 10 days
    split = hmm_model.compute_train_test_split(days, train_pct=0.7)
    assert split == date(2024, 1, 7)  # int(10*0.7) = 7 -> index 6 -> day 7


def test_compute_train_test_split_too_few_days():
    with pytest.raises(ValueError):
        hmm_model.compute_train_test_split([date(2024, 1, 1)], train_pct=0.7)


def test_compute_train_test_split_never_empty_test_window():
    days = [date(2024, 1, 1), date(2024, 1, 2)]
    split = hmm_model.compute_train_test_split(days, train_pct=0.99)
    assert split == date(2024, 1, 1)  # clamp so at least 1 test day remains


def _synthetic_regime_series():
    """200 days clearly BEARISH (drift -3.0%/day), 200 SIDEWAYS (~0%),
    200 BULLISH (drift +3.0%/day), low noise so the 3 regimes are
    separable in mean return."""
    rng = np.random.default_rng(42)
    n_per_regime = 200

    def block(drift, n=n_per_regime):
        rets = rng.normal(drift, 0.002, n)
        return rets

    rets = np.concatenate([block(-0.03), block(0.0002), block(0.03)])
    close = 100 * np.cumprod(1 + rets)
    close = np.concatenate([[100.0], close])[:-1]  # align length
    dates = pd.date_range("2020-01-01", periods=len(close), freq="B").date
    volume = rng.integers(1950, 2050, size=len(close))
    df = pd.DataFrame({
        "trade_date": dates,
        "close_price": close,
        "high": close * 1.005,
        "low": close * 0.995,
        "volume": volume,
    })
    labels = ["BEARISH"] * n_per_regime + ["SIDEWAYS"] * n_per_regime + ["BULLISH"] * n_per_regime
    df["true_label"] = labels
    return hmm_model.compute_hmm_features(df)


def test_fit_stock_hmm_insufficient_history_returns_none():
    df = hmm_model.compute_hmm_features(_synthetic_ohlcv())  # only 10 rows
    assert hmm_model.fit_stock_hmm(df, min_history_days=300) is None


def test_fit_stock_hmm_and_infer_recovers_regimes():
    df = _synthetic_regime_series()
    artifact = hmm_model.fit_stock_hmm(df, min_history_days=300, random_state=0)
    assert artifact is not None
    assert set(artifact["state_label_map"].values()) == {"BEARISH", "SIDEWAYS", "BULLISH"}

    predicted = hmm_model.infer_hmm_state(df, artifact)
    df["predicted"] = predicted.values

    # Majority of each true-regime block should be classified correctly.
    for label in ["BEARISH", "SIDEWAYS", "BULLISH"]:
        block = df[df["true_label"] == label]
        accuracy = (block["predicted"] == label).mean()
        assert accuracy > 0.7, f"{label} block only {accuracy:.0%} correctly classified"


def test_infer_hmm_state_no_model_returns_no_model_label():
    df = hmm_model.compute_hmm_features(_synthetic_ohlcv())
    result = hmm_model.infer_hmm_state(df, None)
    assert (result == "NO_MODEL").all()


def test_infer_hmm_state_missing_features_stay_no_model():
    df = _synthetic_regime_series()
    artifact = hmm_model.fit_stock_hmm(df, min_history_days=300)
    result = hmm_model.infer_hmm_state(df, artifact)
    # First row has NaN hmm_return (pct_change of first row) -> can't be scored
    assert result.iloc[0] == "NO_MODEL"


def test_infer_hmm_state_is_causal_not_affected_by_future_data():
    """Regression test: infer_hmm_state must be causal. A day's label must
    not change when MORE FUTURE data is appended after it — Viterbi decoding
    (hmmlearn's .predict()) fails this because it's a global decode over the
    whole sequence; forward-only filtering (the fix) passes it by
    construction, since state_seq[t] depends solely on obs[0..t]."""
    df = _synthetic_regime_series()
    artifact = hmm_model.fit_stock_hmm(df, min_history_days=300, random_state=0)
    assert artifact is not None

    prefix_len = 400
    df_prefix = df.iloc[:prefix_len].reset_index(drop=True)

    labels_full = hmm_model.infer_hmm_state(df, artifact)
    labels_prefix = hmm_model.infer_hmm_state(df_prefix, artifact)

    assert list(labels_full.iloc[:prefix_len]) == list(labels_prefix)


def test_fit_stock_hmm_skips_restart_that_crashes_on_score():
    """Regression test: a restart candidate whose .score() raises (e.g. a
    converged-but-degenerate fit with NaN startprob_) must be skipped, not
    propagate the exception and crash the whole fit_stock_hmm call."""
    from unittest.mock import patch
    from hmmlearn.hmm import GaussianHMM

    df = _synthetic_regime_series()
    real_score = GaussianHMM.score
    call_count = {"n": 0}

    def flaky_score(self, X, lengths=None):
        call_count["n"] += 1
        if call_count["n"] <= 3:
            raise ValueError("startprob_ must sum to 1 (got nan)")
        return real_score(self, X, lengths)

    with patch.object(GaussianHMM, "score", flaky_score):
        artifact = hmm_model.fit_stock_hmm(df, min_history_days=300, random_state=0)

    assert artifact is not None
    assert call_count["n"] > 3  # confirms later, non-raising restarts were actually reached


# Supabase Storage persistence tests
class _FakeStorageBucket:
    """In-memory stand-in for supabase.storage.from_(bucket) — enough of
    the .upload/.download/.list surface to test path construction and
    pickle round-tripping without network access."""

    def __init__(self):
        self._objects = {}  # path -> bytes

    def upload(self, path, data, options=None):
        self._objects[path] = data

    def download(self, path):
        if path not in self._objects:
            raise Exception(f"not found: {path}")
        return self._objects[path]

    def list(self, prefix, options=None):
        prefix = prefix.rstrip("/") + "/"
        names = set()
        for path in self._objects:
            if path.startswith(prefix):
                names.add(path[len(prefix):])
        sorted_names = sorted(names)
        options = options or {}
        offset = options.get("offset", 0)
        limit = options.get("limit", 100)
        sorted_names = sorted_names[offset:offset + limit]
        return [{"name": n} for n in sorted_names]


class _FakeStorage:
    def __init__(self):
        self._bucket = _FakeStorageBucket()

    def from_(self, bucket_name):
        return self._bucket


class _FakeSupabase:
    def __init__(self):
        self.storage = _FakeStorage()


def test_artifact_path_format():
    assert hmm_model.artifact_path("v2-2026q3", "BBCA") == "v2/v2-2026q3/BBCA.pkl"


def test_save_and_load_artifact_roundtrip():
    supabase = _FakeSupabase()
    artifact = {"scaler": "fake-scaler", "model": "fake-model", "state_label_map": {0: "BEARISH"}}
    hmm_model.save_artifact(supabase, "hmm-models", "v2-2026q3", "BBCA", artifact)
    loaded = hmm_model.load_artifact(supabase, "hmm-models", "v2-2026q3", "BBCA")
    assert loaded == artifact


def test_load_artifact_missing_returns_none():
    supabase = _FakeSupabase()
    assert hmm_model.load_artifact(supabase, "hmm-models", "v2-2026q3", "NOPE") is None


def test_load_all_artifacts():
    supabase = _FakeSupabase()
    hmm_model.save_artifact(supabase, "hmm-models", "v2-2026q3", "BBCA", {"x": 1})
    hmm_model.save_artifact(supabase, "hmm-models", "v2-2026q3", "TLKM", {"x": 2})
    all_artifacts = hmm_model.load_all_artifacts(supabase, "hmm-models", "v2-2026q3")
    assert all_artifacts == {"BBCA": {"x": 1}, "TLKM": {"x": 2}}


def test_load_all_artifacts_paginates_beyond_page_size():
    """Regression test: must not silently truncate to Storage's default
    100-item list() page size (this exact bug dropped 178/278 real models
    in a live acceptance run before being caught and fixed)."""
    supabase = _FakeSupabase()
    for i in range(250):
        hmm_model.save_artifact(supabase, "hmm-models", "v2-2026q3", f"STK{i:04d}", {"x": i})

    all_artifacts = hmm_model.load_all_artifacts(supabase, "hmm-models", "v2-2026q3")

    assert len(all_artifacts) == 250
    assert all_artifacts["STK0000"] == {"x": 0}
    assert all_artifacts["STK0249"] == {"x": 249}
