# V2 HMM Screener/Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build V2 of the screener/backtester as new, isolated files that add an ADTV liquidity gate, per-stock HMM regime confirmation (block BEARISH only), a chronological train/test split, and realistic risk management (min-hold, cooldown, asymmetric fees) — without touching V1's live production path at all.

**Architecture:** `strategy.py` gets two small *additive, default-off* extensions (`add_features()` always computes new feature columns; `get_signals()` gains optional `adtv_min`/`hmm_gate` kwargs that V1 callers never pass). Everything else — HMM fit/inference, the train/test split, the backtest simulation loop, the live screener — lives in brand-new files (`hmm_model.py`, `risk.py`, `data_fetch.py`, `train_hmm.py`, `backtest_v2.py`, `screener_v2.py`) that V1's `screener.py`/`backtest.py` never import and that no GitHub Actions workflow triggers automatically.

**Tech Stack:** Python 3.11, pandas, numpy, `hmmlearn` (GaussianHMM), `scikit-learn` (StandardScaler), Supabase (Postgres + Storage), pytest (new to this repo).

## Global Constraints

- Never alter or edit the `ihsg_eod` / `index_eod` tables — fed by the user's own n8n pipeline, hands off, always.
- `src/backtest.py` and `src/screener.py` (V1, live production) must not be modified by this plan. Not even whitespace.
- `strategy.py`'s `add_features()`/`get_signals()` may only be *extended* with new optional, default-off parameters/columns — any change must leave V1's call sites (which pass no new arguments) byte-identical in behavior. This is verified by an explicit regression test in Task 10, not assumed.
- No new GitHub Actions workflow triggers anything in this plan automatically. `train_hmm.py`, `backtest_v2.py`, `screener_v2.py` are all manual-run only.
- HMM gate rule (locked after design review): reject only if a stock's dominant HMM state is BEARISH. BULLISH or SIDEWAYS both pass through to the existing technical-condition check. Never gate on BULLISH-only — that would reject the accumulation/consolidation setups the strategy is built to catch.
- SL always fires from day 1 of a position, every day, regardless of `MIN_HOLD_DAYS` — capital protection is never suppressed.
- Full design rationale: `docs/superpowers/specs/2026-07-15-v2-hmm-screener-design.md`.

---

## Task 1: Supabase Storage bucket + RLS policies

**Files:** None (Supabase-side only, via MCP tool).

**Interfaces:**
- Produces: Storage bucket `hmm-models` that `hmm_model.save_artifact`/`load_artifact`/`load_all_artifacts` (Task 7) read/write via the same anon key already used by `screener.py`/`backtest.py`.

- [ ] **Step 1: Create the bucket + RLS policies**

Run via the Supabase MCP `apply_migration` tool (`project_id: soddgoonjnfclabrijtn`, name `create_hmm_models_bucket`):

```sql
insert into storage.buckets (id, name, public)
values ('hmm-models', 'hmm-models', false)
on conflict (id) do nothing;

create policy "anon read hmm models"
on storage.objects for select
to anon
using (bucket_id = 'hmm-models');

create policy "anon upload hmm models"
on storage.objects for insert
to anon
with check (bucket_id = 'hmm-models');
```

Mirrors the existing anon SELECT+INSERT-only pattern already used for `screener_results`/`backtest_runs`/etc. — never grant anon UPDATE/DELETE on this bucket either.

- [ ] **Step 2: Verify**

Run via `execute_sql`:

```sql
select id, public from storage.buckets where id = 'hmm-models';
select policyname, cmd from pg_policies where tablename = 'objects' and schemaname = 'storage' and policyname like '%hmm models%';
```

Expected: one bucket row (`public = false`), two policy rows (`cmd = 'SELECT'` and `cmd = 'INSERT'`).

---

## Task 2: Test scaffold + dependencies

**Files:**
- Modify: `requirements.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Produces: a working `pytest` invocation from repo root that can import anything under `src/`.

- [ ] **Step 1: Add dependencies**

Edit `requirements.txt` to:

```
supabase
pandas>=2.2.2
numpy<2.0.0
requests==2.31.0
matplotlib>=3.8.0
hmmlearn>=0.3.0
scikit-learn>=1.3.0
pytest>=8.0.0
```

- [ ] **Step 2: Install**

```bash
pip install -r requirements.txt
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
```

- [ ] **Step 4: Write `tests/test_smoke.py`**

```python
import config as cfg


def test_config_importable():
    assert cfg.LOOKBACK_DAYS == 280
```

- [ ] **Step 5: Run it**

```bash
pytest tests/test_smoke.py -v
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt tests/conftest.py tests/test_smoke.py
git commit -m "test: add pytest scaffold for V2 work"
```

---

## Task 3: `config.py` — V2 constants

**Files:**
- Modify: `src/config.py` (append at end of file)

**Interfaces:**
- Produces: `cfg.ADTV_MIN`, `cfg.MIN_HOLD_DAYS`, `cfg.COOLDOWN_DAYS`, `cfg.BUY_FEE`, `cfg.SELL_FEE`, `cfg.HMM_MIN_HISTORY_DAYS`, `cfg.HMM_TRAIN_SPLIT_PCT`, `cfg.HMM_VERSION`, `cfg.HMM_BUCKET` — consumed by every task from here on.

- [ ] **Step 1: Append to `src/config.py`**

```python

# ----------------------------------------------------------------------
# V2: Liquidity, HMM regime, risk management
# (see docs/superpowers/specs/2026-07-15-v2-hmm-screener-design.md)
# Only referenced by *_v2.py scripts — V1's screener.py/backtest.py never
# import these.
# ----------------------------------------------------------------------
ADTV_MIN = 1_000_000_000          # Rp 1 miliar rata-rata nilai transaksi 20 hari
MIN_HOLD_DAYS = 3                 # TP1/Trailing ditahan N hari bursa; SL selalu aktif
COOLDOWN_DAYS = 10                # blokir entry ulang N hari bursa setelah kena SL
BUY_FEE = 0.0018                  # 0.18% fee beli (broker fee)
SELL_FEE = 0.0028                 # 0.28% fee jual (broker fee + levy bursa 0.1%)
HMM_MIN_HISTORY_DAYS = 300        # minimal hari bersih di train split buat fit HMM
HMM_TRAIN_SPLIT_PCT = 0.7         # 70% train / 30% test, chronological
HMM_VERSION = "v2-2026q3"         # bump manual tiap retrain (train_hmm.py)
HMM_BUCKET = "hmm-models"
```

- [ ] **Step 2: Sanity check**

```bash
python -c "import sys; sys.path.insert(0, 'src'); import config as cfg; print(cfg.ADTV_MIN, cfg.HMM_VERSION)"
```

Expected: `1000000000 v2-2026q3`.

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat(v2): add liquidity/HMM/risk-management config constants"
```

---

## Task 4: `src/risk.py` — cooldown, min-hold, fee helpers

**Files:**
- Create: `src/risk.py`
- Test: `tests/test_risk.py`

**Interfaces:**
- Produces: `is_in_cooldown(stock_code: str, day_idx: int, last_sl_idx: dict, cooldown_days: int) -> bool`, `min_hold_elapsed(hold_days: int, min_hold_days: int) -> bool`, `apply_fee(gross_amount: float, side: str, buy_fee: float, sell_fee: float) -> float` — consumed by `backtest_v2.py` (Task 12).

- [ ] **Step 1: Write failing tests — `tests/test_risk.py`**

```python
import pytest

import risk


def test_is_in_cooldown_no_prior_sl():
    assert risk.is_in_cooldown("BBCA", day_idx=10, last_sl_idx={}, cooldown_days=10) is False


def test_is_in_cooldown_within_window():
    last_sl_idx = {"BBCA": 5}
    assert risk.is_in_cooldown("BBCA", day_idx=10, last_sl_idx=last_sl_idx, cooldown_days=10) is True


def test_is_in_cooldown_after_window():
    last_sl_idx = {"BBCA": 5}
    assert risk.is_in_cooldown("BBCA", day_idx=16, last_sl_idx=last_sl_idx, cooldown_days=10) is False


def test_is_in_cooldown_different_stock_unaffected():
    last_sl_idx = {"BBCA": 5}
    assert risk.is_in_cooldown("TLKM", day_idx=6, last_sl_idx=last_sl_idx, cooldown_days=10) is False


def test_min_hold_elapsed_false_before():
    assert risk.min_hold_elapsed(hold_days=1, min_hold_days=3) is False


def test_min_hold_elapsed_true_at_boundary():
    assert risk.min_hold_elapsed(hold_days=3, min_hold_days=3) is True


def test_apply_fee_buy():
    assert risk.apply_fee(1_000_000, "buy", buy_fee=0.0018, sell_fee=0.0028) == pytest.approx(1800.0)


def test_apply_fee_sell():
    assert risk.apply_fee(1_000_000, "sell", buy_fee=0.0018, sell_fee=0.0028) == pytest.approx(2800.0)


def test_apply_fee_invalid_side():
    with pytest.raises(ValueError):
        risk.apply_fee(1_000_000, "hold", buy_fee=0.0018, sell_fee=0.0028)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_risk.py -v
```

Expected: `ModuleNotFoundError: No module named 'risk'`.

- [ ] **Step 3: Write `src/risk.py`**

```python
"""risk.py — V2 backtest risk-management helpers: cooldown, min-hold, fees.

Pure functions only, no I/O. Consumed by backtest_v2.py's simulation loop.
"""


def is_in_cooldown(stock_code: str, day_idx: int, last_sl_idx: dict, cooldown_days: int) -> bool:
    """True if stock_code was stopped out (SL) within the last
    cooldown_days *trading days* (not calendar days) of day_idx.

    last_sl_idx maps stock_code -> trading-day index (into the
    simulation's trading_days list) of that stock's most recent SL exit.
    Trading-day counting matches how hold_days already counts in the
    existing backtest loop.
    """
    last_idx = last_sl_idx.get(stock_code)
    if last_idx is None:
        return False
    return (day_idx - last_idx) < cooldown_days


def min_hold_elapsed(hold_days: int, min_hold_days: int) -> bool:
    """True once a position has been held >= min_hold_days trading days."""
    return hold_days >= min_hold_days


def apply_fee(gross_amount: float, side: str, buy_fee: float, sell_fee: float) -> float:
    """Returns the fee (same currency unit as gross_amount) for a buy or
    sell. side must be 'buy' or 'sell'."""
    if side == "buy":
        return gross_amount * buy_fee
    if side == "sell":
        return gross_amount * sell_fee
    raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_risk.py -v
```

Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/risk.py tests/test_risk.py
git commit -m "feat(v2): add risk.py cooldown/min-hold/fee helpers"
```

---

## Task 5: `src/hmm_model.py` part 1 — feature computation + split boundary

**Files:**
- Create: `src/hmm_model.py`
- Test: `tests/test_hmm_model.py`

**Interfaces:**
- Produces: `HMM_FEATURES: list[str]`, `compute_hmm_features(group: pd.DataFrame) -> pd.DataFrame`, `compute_train_test_split(trading_days: list, train_pct: float = 0.7) -> date` — consumed by `strategy.add_features()` (Task 9) and `train_hmm.py`/`backtest_v2.py` (Tasks 11-12).

- [ ] **Step 1: Write failing tests — `tests/test_hmm_model.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hmm_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'hmm_model'`.

- [ ] **Step 3: Write `src/hmm_model.py` (part 1 — this task's scope only)**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_hmm_model.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/hmm_model.py tests/test_hmm_model.py
git commit -m "feat(v2): hmm_model.py feature computation + train/test split boundary"
```

---

## Task 6: `src/hmm_model.py` part 2 — fit, label, infer

**Files:**
- Modify: `src/hmm_model.py`
- Test: `tests/test_hmm_model.py` (append)

**Interfaces:**
- Consumes: `HMM_FEATURES` from Task 5.
- Produces: `fit_stock_hmm(feature_df: pd.DataFrame, min_history_days: int, random_state: int = 42) -> dict | None`, `infer_hmm_state(feature_df: pd.DataFrame, artifact: dict | None) -> pd.Series` — consumed by `train_hmm.py` (Task 11), `backtest_v2.py`/`screener_v2.py` (Tasks 12-13), and `strategy.py`'s gate logic indirectly (via the `hmm_state` column callers merge in).

- [ ] **Step 1: Write failing tests — append to `tests/test_hmm_model.py`**

```python
def _synthetic_regime_series():
    """200 days clearly BEARISH (drift -1.5%/day), 200 SIDEWAYS (~0%),
    200 BULLISH (drift +1.5%/day), low noise so the 3 regimes are
    separable in mean return."""
    rng = np.random.default_rng(42)
    n_per_regime = 200

    def block(drift, n=n_per_regime):
        rets = rng.normal(drift, 0.002, n)
        return rets

    rets = np.concatenate([block(-0.015), block(0.0002), block(0.015)])
    close = 100 * np.cumprod(1 + rets)
    close = np.concatenate([[100.0], close])[:-1]  # align length
    dates = pd.date_range("2020-01-01", periods=len(close), freq="B").date
    volume = rng.integers(1000, 5000, size=len(close))
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
    artifact = hmm_model.fit_stock_hmm(df, min_history_days=300)
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hmm_model.py -v -k "fit_stock_hmm or infer_hmm_state"
```

Expected: `AttributeError: module 'hmm_model' has no attribute 'fit_stock_hmm'`.

- [ ] **Step 3: Append to `src/hmm_model.py`**

```python
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler


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

    model = GaussianHMM(
        n_components=3,
        covariance_type="diag",
        n_iter=100,
        random_state=random_state,
    )
    try:
        model.fit(X_scaled)
    except Exception:
        return None

    if not model.monitor_.converged:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_hmm_model.py -v
```

Expected: all pass (11 total so far). `test_fit_stock_hmm_and_infer_recovers_regimes` may take a few seconds (HMM fit on 600 rows) — that's expected, not a hang.

- [ ] **Step 5: Commit**

```bash
git add src/hmm_model.py tests/test_hmm_model.py
git commit -m "feat(v2): hmm_model.py fit/label/infer per-stock HMM"
```

---

## Task 7: `src/hmm_model.py` part 3 — Supabase Storage persistence

**Files:**
- Modify: `src/hmm_model.py`
- Test: `tests/test_hmm_model.py` (append)

**Interfaces:**
- Produces: `artifact_path(version: str, stock_code: str) -> str`, `save_artifact(supabase, bucket: str, version: str, stock_code: str, artifact: dict) -> None`, `load_artifact(supabase, bucket: str, version: str, stock_code: str) -> dict | None`, `load_all_artifacts(supabase, bucket: str, version: str) -> dict[str, dict]` — consumed by `train_hmm.py` (Task 11), `backtest_v2.py`/`screener_v2.py` (Tasks 12-13).

- [ ] **Step 1: Write failing tests — append to `tests/test_hmm_model.py`**

```python
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

    def list(self, prefix):
        prefix = prefix.rstrip("/") + "/"
        names = set()
        for path in self._objects:
            if path.startswith(prefix):
                names.add(path[len(prefix):])
        return [{"name": n} for n in sorted(names)]


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hmm_model.py -v -k "artifact"
```

Expected: `AttributeError: module 'hmm_model' has no attribute 'artifact_path'`.

- [ ] **Step 3: Append to `src/hmm_model.py`**

```python
def artifact_path(version: str, stock_code: str) -> str:
    return f"v2/{version}/{stock_code}.pkl"


def save_artifact(supabase, bucket: str, version: str, stock_code: str, artifact: dict) -> None:
    blob = pickle.dumps(artifact)
    supabase.storage.from_(bucket).upload(
        artifact_path(version, stock_code),
        blob,
        {"content-type": "application/octet-stream"},
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_hmm_model.py -v
```

Expected: all pass (15 total).

- [ ] **Step 5: Commit**

```bash
git add src/hmm_model.py tests/test_hmm_model.py
git commit -m "feat(v2): hmm_model.py Supabase Storage artifact persistence"
```

---

## Task 8: `src/data_fetch.py` — shared fetch for V2 scripts

**Files:**
- Create: `src/data_fetch.py`
- Test: `tests/test_data_fetch.py`

**Interfaces:**
- Produces: `fetch_data(supabase, start_date: date, end_date: date, lookback_days: int = 280) -> tuple[pd.DataFrame, pd.DataFrame]` — consumed by `train_hmm.py`, `backtest_v2.py`, `screener_v2.py` (Tasks 11-13).

Deliberately a fresh extraction, not imported by V1's `backtest.py` — see Global Constraints.

- [ ] **Step 1: Write failing tests — `tests/test_data_fetch.py`**

```python
from datetime import date

import data_fetch


class _FakeQuery:
    """Chainable stand-in for supabase.table(...).select(...).eq(...)... .execute()."""

    def __init__(self, rows_by_call, call_counter, key):
        self._rows_by_call = rows_by_call
        self._call_counter = call_counter
        self._key = key

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self

    def range(self, offset, limit):
        return self

    def execute(self):
        i = self._call_counter[self._key]
        self._call_counter[self._key] += 1
        rows = self._rows_by_call[self._key][i] if i < len(self._rows_by_call[self._key]) else []
        return type("Result", (), {"data": rows})()


class _FakeTable:
    def __init__(self, name, rows_by_call, call_counter):
        self._name = name
        self._rows_by_call = rows_by_call
        self._call_counter = call_counter

    def select(self, *a, **k):
        return _FakeQuery(self._rows_by_call, self._call_counter, self._name)


class _FakeSupabase:
    def __init__(self, rows_by_call):
        self._rows_by_call = rows_by_call
        self._call_counter = {k: 0 for k in rows_by_call}

    def table(self, name):
        return _FakeTable(name, self._rows_by_call, self._call_counter)


def test_fetch_data_paginates_until_empty_batch():
    idx_rows = [{"trade_date": "2024-01-01", "close": "7000"}]
    codes_rows = [{"stock_code": "BBCA"}]
    stock_rows = [{
        "stock_code": "BBCA", "trade_date": "2024-01-01", "open_price": "9000",
        "close_price": "9100", "high": "9150", "low": "8950", "previous": "9050",
        "volume": "1000000", "foreign_buy": "100", "foreign_sell": "50",
    }]
    rows_by_call = {
        "index_eod": [idx_rows, []],   # first page has data, second page empty -> stop
        "ihsg_eod": [codes_rows, stock_rows, []],
    }
    supabase = _FakeSupabase(rows_by_call)

    df, idx_df = data_fetch.fetch_data(supabase, date(2024, 1, 1), date(2024, 1, 1), lookback_days=0)

    assert len(idx_df) == 1
    assert idx_df.iloc[0]["close"] == 7000.0
    assert len(df) == 1
    assert df.iloc[0]["stock_code"] == "BBCA"
    assert df.iloc[0]["close_price"] == 9100.0


def test_fetch_data_raises_when_no_stock_data():
    rows_by_call = {
        "index_eod": [[{"trade_date": "2024-01-01", "close": "7000"}], []],
        "ihsg_eod": [[{"stock_code": "BBCA"}], [], []],  # codes found but no OHLCV rows
    }
    supabase = _FakeSupabase(rows_by_call)
    import pytest
    with pytest.raises(RuntimeError):
        data_fetch.fetch_data(supabase, date(2024, 1, 1), date(2024, 1, 1), lookback_days=0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_data_fetch.py -v
```

Expected: `ModuleNotFoundError: No module named 'data_fetch'`.

- [ ] **Step 3: Write `src/data_fetch.py`**

```python
"""
data_fetch.py — Shared Supabase data-fetch helper for V2 scripts
(train_hmm.py, backtest_v2.py, screener_v2.py).

Deliberately NOT imported by V1's backtest.py/screener.py — those keep
their own inline fetch logic untouched (see plan Global Constraints).
"""

import time
from datetime import date, timedelta

import pandas as pd


def _retry(fn, attempts=4, base_delay=2.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (i + 1))


def fetch_data(supabase, start_date: date, end_date: date, lookback_days: int = 280):
    """Fetches IHSG index + per-stock OHLCV data for
    [start_date - lookback_days, end_date]. Returns (df, idx_df)."""
    fetch_start = start_date - timedelta(days=lookback_days)

    all_idx = []
    offset = 0
    while True:
        batch = _retry(lambda: (
            supabase.table("index_eod")
            .select("trade_date,close")
            .eq("index_code", "COMPOSITE")
            .gte("trade_date", fetch_start.isoformat())
            .lte("trade_date", end_date.isoformat())
            .order("trade_date")
            .range(offset, offset + 999)
            .execute()
        ))
        if not batch.data:
            break
        all_idx.extend(batch.data)
        offset += 1000

    idx_df = pd.DataFrame(all_idx) if all_idx else pd.DataFrame()
    if not idx_df.empty:
        idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"]).dt.date
        idx_df["close"] = pd.to_numeric(idx_df["close"], errors="coerce")
        idx_df = idx_df.sort_values("trade_date").reset_index(drop=True)
        idx_df["ma50"] = idx_df["close"].rolling(50, min_periods=50).mean()

    idx_in_range = idx_df[
        (idx_df["trade_date"] >= start_date) & (idx_df["trade_date"] <= end_date)
    ] if not idx_df.empty else idx_df
    code_date = (
        idx_in_range["trade_date"].max().isoformat()
        if not idx_in_range.empty else end_date.isoformat()
    )

    codes_batch = _retry(lambda: (
        supabase.table("ihsg_eod")
        .select("stock_code")
        .eq("trade_date", code_date)
        .limit(2000)
        .execute()
    ))
    unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))
    if not unique_codes:
        codes_batch = _retry(lambda: (
            supabase.table("ihsg_eod")
            .select("stock_code")
            .eq("trade_date", start_date.isoformat())
            .limit(2000)
            .execute()
        ))
        unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))

    all_stocks = []
    batch_size = 50
    for i in range(0, len(unique_codes), batch_size):
        batch_codes = unique_codes[i:i + batch_size]
        offset = 0
        while True:
            batch = _retry(lambda: (
                supabase.table("ihsg_eod")
                .select("stock_code,trade_date,open_price,close_price,high,low,previous,volume,foreign_buy,foreign_sell")
                .in_("stock_code", batch_codes)
                .gte("trade_date", fetch_start.isoformat())
                .lte("trade_date", end_date.isoformat())
                .order("trade_date")
                .range(offset, offset + 999)
                .execute()
            ))
            if not batch.data:
                break
            all_stocks.extend(batch.data)
            offset += 1000

    if not all_stocks:
        raise RuntimeError("No stock data retrieved from ihsg_eod")

    df = pd.DataFrame(all_stocks)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    for col in ["open_price", "close_price", "high", "low", "volume", "previous", "foreign_buy", "foreign_sell"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df, idx_df
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_data_fetch.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/data_fetch.py tests/test_data_fetch.py
git commit -m "feat(v2): data_fetch.py — extracted, parametrized Supabase fetch for V2 scripts"
```

---

## Task 9: `strategy.py` — add ADTV + HMM feature columns

**Files:**
- Modify: `src/strategy.py`
- Test: `tests/test_strategy_v2.py`

**Interfaces:**
- Consumes: `hmm_model.compute_hmm_features` (Task 5).
- Produces: `add_features()` output now always includes `adtv_20`, `hmm_return`, `hmm_range`, `hmm_log_vol_change` columns — consumed by Task 10 and all V2 orchestrator scripts.

- [ ] **Step 1: Write failing test — `tests/test_strategy_v2.py`**

```python
import pandas as pd
import pytest

from strategy import add_features


def _synthetic_stock_df(n=60):
    dates = pd.date_range("2024-01-01", periods=n, freq="B").date
    close = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "stock_code": ["TEST"] * n,
        "trade_date": dates,
        "close_price": close,
        "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close],
        "previous": [close[0]] + close[:-1],
        "volume": [1_000_000] * n,
        "foreign_buy": [0] * n,
        "foreign_sell": [0] * n,
    })


def test_add_features_includes_adtv_20():
    df = add_features(_synthetic_stock_df())
    assert "adtv_20" in df.columns
    # adtv_20 at row 19 (20th row, 0-indexed) = mean(close[0:20] * 1_000_000)
    expected = (df["close_price"].iloc[:20] * 1_000_000).mean()
    assert df["adtv_20"].iloc[19] == pytest.approx(expected)


def test_add_features_includes_hmm_columns():
    df = add_features(_synthetic_stock_df())
    for col in ["hmm_return", "hmm_range", "hmm_log_vol_change"]:
        assert col in df.columns
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_strategy_v2.py -v
```

Expected: `AssertionError: assert 'adtv_20' in Index([...])`.

- [ ] **Step 3: Modify `src/strategy.py`**

Add the import near the top (after `import config as cfg`):

```python
import hmm_model
```

In `add_features()`, right before the final `return group` (currently line 169, after the `foreign_net_ma` block), add:

```python
    # ---- V2: ADTV liquidity feature + HMM regime features ----
    group["adtv_20"] = (group["close_price"] * group["volume"]).rolling(20, min_periods=20).mean()
    group = hmm_model.compute_hmm_features(group)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_strategy_v2.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Regression check — V1 still unaffected**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
import pandas as pd
from strategy import add_features
df = pd.DataFrame({
    'stock_code': ['TEST']*30, 'trade_date': pd.date_range('2024-01-01', periods=30, freq='B').date,
    'close_price': [100.0+i for i in range(30)], 'high': [101.0+i for i in range(30)],
    'low': [99.0+i for i in range(30)], 'previous': [100.0]+[99.0+i for i in range(29)],
    'volume': [1000]*30, 'foreign_buy': [0]*30, 'foreign_sell': [0]*30,
})
out = add_features(df)
assert 'ma10' in out.columns and 'adtv_20' in out.columns
print('OK: V1 columns + new V2 columns coexist')
"
```

Expected: `OK: V1 columns + new V2 columns coexist`.

- [ ] **Step 6: Commit**

```bash
git add src/strategy.py tests/test_strategy_v2.py
git commit -m "feat(v2): add_features() computes adtv_20 + HMM feature columns"
```

---

## Task 10: `strategy.py` — `get_signals()` optional ADTV/HMM gates + V1 regression test

**Files:**
- Modify: `src/strategy.py`
- Test: `tests/test_strategy_v2.py` (append)

**Interfaces:**
- Produces: `get_signals(df_day, confidence_min, min_conditions=4, adtv_min: float | None = None, hmm_gate: bool = False) -> pd.DataFrame` — consumed by `backtest_v2.py`/`screener_v2.py` (Tasks 12-13). V1's `screener.py`/`backtest.py` call sites are unchanged text and get identical behavior via the new params' defaults.

- [ ] **Step 1: Write failing tests — append to `tests/test_strategy_v2.py`**

```python
from strategy import get_signals


def _synthetic_signal_day(n=5, with_adtv=True, with_hmm=False, hmm_states=None):
    """A day_data frame with enough columns for get_signals() to run past
    the REQUIRED_COLS dropna and red-flag filters."""
    df = pd.DataFrame({
        "stock_code": [f"STK{i}" for i in range(n)],
        "trade_date": [pd.Timestamp("2024-06-01").date()] * n,
        "close_price": [1000.0] * n,
        "previous": [1000.0] * n,
        "high": [1010.0] * n,
        "low": [990.0] * n,
        "volume": [500_000] * n,
        "foreign_buy": [0] * n,
        "foreign_sell": [0] * n,
        "ma10": [1000.0] * n,
        "ma20": [1000.0] * n,
        "ma50": [1000.0] * n,
        "std20": [5.0] * n,
        "bb_bandwidth": [2.0] * n,          # tight -> cond2 True
        "avg_vol_20": [400_000] * n,
        "avg_vol_20_prev": [200_000] * n,   # vol_ratio = 500k/200k = 2.5 -> cond3 True
        "daily_return": [0.0] * n,
        "rolling_min_close": [900.0] * n,
        "rolling_max_close": [1100.0] * n,
        "bb_upper": [1050.0] * n,
        "rsi": [55.0] * n,
        "adx": [25.0] * n,
        "sma200": [900.0] * n,
        "foreign_net_ma": [0.1] * n,
        "atr_14": [10.0] * n,
        "atr_sl": [980.0] * n,
        "ut_position": [1] * n,
        "swing_low": [950.0] * n,
        "last_swing_low": [950.0] * n,
        "buy_zone_low": [940.0] * n,
        "buy_zone_high": [960.0] * n,
        "last_swing_high": [1050.0] * n,
        "tp_target": [1050.0] * n,
    })
    if with_adtv:
        df["adtv_20"] = 2_000_000_000.0  # well above ADTV_MIN
    if with_hmm:
        df["hmm_state"] = hmm_states if hmm_states is not None else ["BULLISH"] * n
    return df


def test_get_signals_v1_call_signature_unaffected_by_missing_v2_columns():
    """V1 callers never compute adtv_20/hmm_state and never pass the new
    kwargs — get_signals() must not require those columns to exist."""
    day = _synthetic_signal_day(with_adtv=False, with_hmm=False)
    assert "adtv_20" not in day.columns
    assert "hmm_state" not in day.columns
    result = get_signals(day, confidence_min=0, min_conditions=2)
    assert isinstance(result, pd.DataFrame)  # ran without KeyError


def test_get_signals_adtv_gate_excludes_illiquid():
    day = _synthetic_signal_day(with_adtv=True)
    day["adtv_20"] = 500_000_000.0  # below ADTV_MIN (1B)
    result = get_signals(day, confidence_min=0, min_conditions=2, adtv_min=1_000_000_000)
    assert result.empty


def test_get_signals_adtv_gate_keeps_liquid():
    day = _synthetic_signal_day(with_adtv=True)  # 2B, above ADTV_MIN
    result = get_signals(day, confidence_min=0, min_conditions=2, adtv_min=1_000_000_000)
    assert not result.empty


def test_get_signals_hmm_gate_excludes_bearish():
    day = _synthetic_signal_day(with_adtv=True, with_hmm=True, hmm_states=["BEARISH"] * 5)
    result = get_signals(day, confidence_min=0, min_conditions=2, hmm_gate=True)
    assert result.empty


def test_get_signals_hmm_gate_keeps_sideways_and_bullish():
    day = _synthetic_signal_day(with_adtv=True, with_hmm=True, hmm_states=["SIDEWAYS", "BULLISH", "BEARISH", "NO_MODEL", "SIDEWAYS"])
    result = get_signals(day, confidence_min=0, min_conditions=2, hmm_gate=True)
    assert set(result["stock_code"]).issubset({"STK0", "STK1", "STK4"})
    assert "STK2" not in set(result["stock_code"])  # BEARISH
    assert "STK3" not in set(result["stock_code"])  # NO_MODEL
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_strategy_v2.py -v -k "get_signals"
```

Expected: `TypeError: get_signals() got an unexpected keyword argument 'adtv_min'`.

- [ ] **Step 3: Modify `get_signals()` in `src/strategy.py`**

Change the signature:

```python
def get_signals(
    df_day: pd.DataFrame,
    confidence_min: float,
    min_conditions: int = 4,
    adtv_min: float | None = None,
    hmm_gate: bool = False,
) -> pd.DataFrame:
```

Right after the existing block:

```python
    illiquid = latest["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL
    candidates = latest[~(sleeping | illiquid)].copy()
    if candidates.empty:
        return pd.DataFrame()
```

add:

```python
    # --- V2 (opt-in, default off): ADTV liquidity + HMM regime gate ---
    if adtv_min is not None:
        candidates = candidates[candidates["adtv_20"] >= adtv_min]
        if candidates.empty:
            return pd.DataFrame()

    if hmm_gate:
        candidates = candidates[candidates["hmm_state"].isin(["BULLISH", "SIDEWAYS"])]
        if candidates.empty:
            return pd.DataFrame()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_strategy_v2.py -v
```

Expected: all pass (7 total in this file).

- [ ] **Step 5: Full regression suite**

```bash
pytest tests/ -v
```

Expected: all tests across all files pass (confirms nothing in Tasks 4-9 broke).

- [ ] **Step 6: Commit**

```bash
git add src/strategy.py tests/test_strategy_v2.py
git commit -m "feat(v2): get_signals() optional adtv_min/hmm_gate params, V1 behavior unchanged"
```

---

## Task 11: `src/train_hmm.py` — offline training script

**Files:**
- Create: `src/train_hmm.py`

**Interfaces:**
- Consumes: `data_fetch.fetch_data`, `hmm_model.compute_train_test_split`/`fit_stock_hmm`/`save_artifact`, `strategy.add_features`, `cfg.ADTV_MIN`/`HMM_MIN_HISTORY_DAYS`/`HMM_TRAIN_SPLIT_PCT`/`HMM_BUCKET`/`HMM_VERSION`.
- Produces: populated `hmm-models` Storage bucket, ready for Tasks 12-13.

Manual-trigger only — no test suite for this task (it's I/O orchestration glue over already-tested pieces); verified by the acceptance run in Task 14.

- [ ] **Step 1: Write `src/train_hmm.py`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add src/train_hmm.py
git commit -m "feat(v2): train_hmm.py offline per-stock HMM training script"
```

---

## Task 12: `src/backtest_v2.py` — out-of-sample simulation

**Files:**
- Create: `src/backtest_v2.py`

**Interfaces:**
- Consumes: everything from Tasks 3-10 (`config`, `data_fetch`, `hmm_model`, `risk`, `strategy`).
- Produces: a `backtest_runs` row with `version="v2-dev"`, `is_published=false`, plus matching `backtest_trades`/`backtest_equity` rows, scoped to the test window only.

- [ ] **Step 1: Write `src/backtest_v2.py`**

```python
"""
backtest_v2.py — V2 backtest: per-stock HMM confirmation, ADTV liquidity
gate, min-hold/cooldown risk management, asymmetric transaction costs,
chronological train/test split.

Adapted from backtest.py's proven simulation loop. Deliberately a SEPARATE
file, not a modification of backtest.py — V1 stays untouched and
reproducible while V2 is validated. See
docs/superpowers/specs/2026-07-15-v2-hmm-screener-design.md.

Only ever run manually — not wired into any scheduled GitHub Actions
workflow until V2 is explicitly approved for production.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/backtest_v2.py
"""

import os
import sys
from datetime import date

import pandas as pd
from supabase import create_client

import config as cfg
import data_fetch
import hmm_model
import risk
from strategy import add_features, get_regime, get_regime_params, get_signals

BACKTEST_START = date.fromisoformat(os.environ.get("BACKTEST_START", "2021-01-01"))
BACKTEST_END = date.fromisoformat(os.environ.get("BACKTEST_END", "2026-06-30"))
INITIAL_CAPITAL = 100_000_000
LOT_SIZE = 100
SL_PCT = 0.02

BACKTEST_VERSION = os.environ.get("BACKTEST_VERSION", "v2-dev")
BACKTEST_PUBLISH = os.environ.get("BACKTEST_PUBLISH", "false").lower() == "true"


def run_backtest_v2():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 70)
    print("BACKTEST V2 - HMM-confirmed Accumulation Detector")
    print(f"Periode: {BACKTEST_START} - {BACKTEST_END}")
    print("=" * 70)

    print("[FETCH] Downloading data ...")
    df, idx_df = data_fetch.fetch_data(supabase, BACKTEST_START, BACKTEST_END)

    print("[HMM] Loading frozen artifacts ...")
    artifacts = hmm_model.load_all_artifacts(supabase, cfg.HMM_BUCKET, cfg.HMM_VERSION)
    print(f"[HMM] Loaded {len(artifacts)} stock models (version {cfg.HMM_VERSION})")

    print("[FEATURE] Computing indicators + HMM states ...")
    stock_codes = df["stock_code"].unique()
    frames = []
    for sc in stock_codes:
        group = add_features(df[df["stock_code"] == sc].copy())
        group["hmm_state"] = hmm_model.infer_hmm_state(group, artifacts.get(sc))
        frames.append(group)
    df = pd.concat(frames, ignore_index=True)

    close_lookup = df.set_index(["stock_code", "trade_date"])["close_price"]
    bar_lookup = {
        (r.stock_code, r.trade_date): (r.open_price, r.close_price, r.high, r.low)
        for r in df.itertuples()
    }

    def get_bar(stock_code, d):
        try:
            o, c, h, l = bar_lookup[(stock_code, d)]
        except KeyError:
            return None
        if pd.isna(c) or c <= 0:
            return None
        h = c if (pd.isna(h) or h <= 0) else max(h, c)
        l = c if (pd.isna(l) or l <= 0) else min(l, c)
        if pd.isna(o) or o <= 0 or o > h or o < l:
            o = None
        return o, c, h, l

    all_trading_days = sorted(
        d for d in df[df["trade_date"] >= BACKTEST_START]["trade_date"].unique()
        if d <= BACKTEST_END
    )
    split_date = hmm_model.compute_train_test_split(all_trading_days, cfg.HMM_TRAIN_SPLIT_PCT)
    trading_days = [d for d in all_trading_days if d > split_date]
    n_train_days = sum(1 for d in all_trading_days if d <= split_date)
    print(f"[SPLIT] Train: {all_trading_days[0]} .. {split_date} "
          f"({n_train_days} days, used only to freeze HMM models in train_hmm.py)")
    print(f"[SPLIT] Test (out-of-sample simulation): {trading_days[0]} .. {trading_days[-1]} "
          f"({len(trading_days)} days)\n")

    positions = []
    cash = float(INITIAL_CAPITAL)
    trades = []
    equity_curve = []
    pending_entries = []
    last_sl_idx = {}  # stock_code -> trading_days index of most recent SL exit

    for day_idx, trade_date in enumerate(trading_days):
        regime = get_regime(idx_df, trade_date)
        regime_params = get_regime_params(regime)
        prev_equity = equity_curve[-1]["total"] if equity_curve else float(INITIAL_CAPITAL)

        # ---- Execute pending entries at today's OPEN ----
        for sig in pending_entries:
            if any(p["stock_code"] == sig["stock_code"] for p in positions):
                continue
            if len(positions) >= sig["max_positions"]:
                break
            if risk.is_in_cooldown(sig["stock_code"], day_idx, last_sl_idx, cfg.COOLDOWN_DAYS):
                continue

            bar = get_bar(sig["stock_code"], trade_date)
            if bar is None:
                continue
            o, c, h, l = bar
            entry_price = o if o is not None else c
            sc_price = sig["signal_close"]
            tick = 1 if sc_price < 200 else 2 if sc_price < 500 else 5 if sc_price < 2000 else 10 if sc_price < 5000 else 25
            gap_limit = max(cfg.GAP_MAX, 2 * tick / sc_price)
            if abs(entry_price / sc_price - 1) > gap_limit:
                continue

            atr_val = sig["atr"]
            if pd.isna(atr_val) or atr_val <= 0:
                tp1_price = entry_price * 1.02
                sl_price = entry_price * (1 - SL_PCT)
            else:
                tp1_price = entry_price + atr_val * cfg.TP1_MULT
                sl_price = entry_price - atr_val * sig["sl_mult"]
                tp1_price = max(tp1_price, entry_price * 1.01)
                sl_price = min(sl_price, entry_price * 0.99)

            alloc = min(prev_equity * sig["alloc_pct"], cash)
            cost_per_share = entry_price * (1 + cfg.BUY_FEE)
            lots = int(alloc / cost_per_share) // LOT_SIZE
            risk_per_share = entry_price - sl_price
            if risk_per_share > 0:
                lots_risk = int(prev_equity * cfg.RISK_PCT / risk_per_share) // LOT_SIZE
                lots = min(lots, lots_risk)
            liq_lots = int(sig["avg_vol_20"] * cfg.LIQ_CAP_PCT) // LOT_SIZE
            lots = min(lots, liq_lots)
            if lots < cfg.ALLOC_MIN_LOTS:
                continue

            quantity = lots * LOT_SIZE
            cost_basis = quantity * cost_per_share
            if cost_basis > cash:
                lots = int(cash / cost_per_share) // LOT_SIZE
                if lots < 1:
                    continue
                quantity = lots * LOT_SIZE
                cost_basis = quantity * cost_per_share

            cash -= cost_basis
            positions.append({
                "stock_code": sig["stock_code"],
                "entry_date": trade_date,
                "avg_price": entry_price,
                "tp1_price": tp1_price,
                "sl_price": sl_price,
                "total_lots": lots,
                "remaining_lots": lots,
                "quantity": quantity,
                "cost_basis": cost_basis,
                "hold_days": 0,
                "tp1_hit": False,
                "highest_price": entry_price,
                "trigger": sig["trigger"],
            })
        pending_entries = []

        # ---- Exit check ----
        remaining_positions = []
        for pos in positions:
            if pos["entry_date"] == trade_date:
                remaining_positions.append(pos)
                continue

            bar = get_bar(pos["stock_code"], trade_date)
            if bar is None:
                pos["hold_days"] += 1
                remaining_positions.append(pos)
                continue
            o, close_price, high_price, low_price = bar

            exit_reason = None
            exit_price = None
            sell_lots = 0
            hold_ok = risk.min_hold_elapsed(pos["hold_days"], cfg.MIN_HOLD_DAYS)

            if close_price > pos["highest_price"]:
                pos["highest_price"] = close_price

            # SL always active from day 1 — capital protection is never suppressed,
            # regardless of MIN_HOLD_DAYS. Only TP1/TRAILING are gated on hold_ok.
            if not pos["tp1_hit"]:
                if low_price <= pos["sl_price"]:
                    exit_reason = "SL"
                    exit_price = o if (o is not None and o < pos["sl_price"]) else pos["sl_price"]
                    sell_lots = pos["remaining_lots"]
                elif hold_ok and high_price >= pos["tp1_price"]:
                    exit_reason = "TP1"
                    exit_price = o if (o is not None and o > pos["tp1_price"]) else pos["tp1_price"]
                    sell_lots = max(1, int(pos["remaining_lots"] * cfg.TP1_PCT))
                elif pos["hold_days"] >= cfg.MAX_HOLD_DAYS - 1:
                    pnl_check = (close_price / pos["avg_price"] - 1) * 100
                    if pnl_check > 0 and regime == "BULLISH":
                        pass
                    else:
                        exit_reason = "TIME"
                        exit_price = close_price
                        sell_lots = pos["remaining_lots"]
            else:
                if low_price <= pos["sl_price"]:
                    exit_reason = "SL"
                    exit_price = o if (o is not None and o < pos["sl_price"]) else pos["sl_price"]
                    sell_lots = pos["remaining_lots"]
                elif hold_ok:
                    trailing_stop = pos["highest_price"] * (1 - cfg.TRAILING_PCT)
                    stop_eff = max(trailing_stop, pos["sl_price"])
                    if close_price <= stop_eff:
                        exit_reason = "TRAILING"
                        exit_price = close_price
                        sell_lots = pos["remaining_lots"]

            if exit_reason is not None and sell_lots > 0:
                sell_qty = sell_lots * LOT_SIZE
                sell_cost_basis = pos["cost_basis"] * (sell_lots / pos["total_lots"])
                gross_return = exit_price * sell_qty
                fee = risk.apply_fee(gross_return, "sell", cfg.BUY_FEE, cfg.SELL_FEE)
                net_return = gross_return - fee
                pnl = net_return - sell_cost_basis
                pnl_pct = (exit_price / pos["avg_price"] - 1) * 100

                cash += net_return
                pos["remaining_lots"] -= sell_lots

                if exit_reason == "SL":
                    last_sl_idx[pos["stock_code"]] = day_idx

                trades.append({
                    "stock_code": pos["stock_code"],
                    "entry_date": pos["entry_date"],
                    "exit_date": trade_date,
                    "entry_price": pos["avg_price"],
                    "exit_price": exit_price,
                    "quantity": sell_qty,
                    "lots": sell_lots,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                    "trigger": pos["trigger"],
                    "hold_days": pos["hold_days"],
                })

                if exit_reason == "TP1":
                    pos["tp1_hit"] = True
                    pos["sl_price"] = pos["avg_price"]
                    pos["cost_basis"] = pos["cost_basis"] - sell_cost_basis
                    pos["total_lots"] = pos["remaining_lots"]
                    remaining_positions.append(pos)

            if exit_reason is None or sell_lots == 0:
                pos["hold_days"] += 1
                remaining_positions.append(pos)

        positions = remaining_positions

        # ---- New signals (V2 gates: ADTV + HMM) ----
        day_data = df[df["trade_date"] == trade_date].copy()
        if regime == "BULLISH":
            min_cond = cfg.BULLISH_MIN_CONDITIONS
        elif regime == "BEARISH":
            min_cond = cfg.BEARISH_MIN_CONDITIONS
        else:
            min_cond = cfg.NEUTRAL_MIN_CONDITIONS

        signals = get_signals(
            day_data, regime_params["confidence_min"], min_cond,
            adtv_min=cfg.ADTV_MIN, hmm_gate=True,
        )

        if not signals.empty:
            if regime == "BULLISH":
                alloc_pct = cfg.ALLOC_BULLISH
            elif regime == "BEARISH":
                alloc_pct = cfg.ALLOC_BEARISH
            else:
                alloc_pct = cfg.ALLOC_NEUTRAL

            for _, sig in signals.nlargest(15, "confidence").iterrows():
                pending_entries.append({
                    "stock_code": sig["stock_code"],
                    "confidence": float(sig["confidence"]),
                    "signal_close": float(sig["close_price"]),
                    "atr": sig["atr_14"],
                    "avg_vol_20": float(sig["avg_vol_20"]),
                    "sl_mult": regime_params["sl_mult"],
                    "alloc_pct": alloc_pct,
                    "max_positions": regime_params["max_positions"],
                    "trigger": sig["trigger"],
                })

        pos_market_value = 0.0
        for pos in positions:
            try:
                cp = close_lookup.loc[(pos["stock_code"], trade_date)]
                if hasattr(cp, "iloc"):
                    cp = cp.iloc[0]
                pos_market_value += (cp if not pd.isna(cp) else pos["avg_price"]) * pos["remaining_lots"] * LOT_SIZE
            except KeyError:
                pos_market_value += pos["avg_price"] * pos["remaining_lots"] * LOT_SIZE

        portfolio_value = cash + pos_market_value
        equity_curve.append({"date": trade_date, "cash": cash, "market_value": pos_market_value, "total": portfolio_value})

    # ---- Close remaining positions at end of test window ----
    final_date = trading_days[-1]
    for pos in positions:
        if pos["remaining_lots"] <= 0:
            continue
        try:
            exit_price = close_lookup.loc[(pos["stock_code"], final_date)]
            if hasattr(exit_price, "iloc"):
                exit_price = exit_price.iloc[0]
            if pd.isna(exit_price):
                exit_price = pos["avg_price"]
        except KeyError:
            exit_price = pos["avg_price"]

        exit_qty = pos["remaining_lots"] * LOT_SIZE
        exit_cost_basis = pos["cost_basis"] * (pos["remaining_lots"] / pos["total_lots"])
        gross_return = exit_price * exit_qty
        fee = risk.apply_fee(gross_return, "sell", cfg.BUY_FEE, cfg.SELL_FEE)
        net_return = gross_return - fee
        pnl = net_return - exit_cost_basis
        pnl_pct = (exit_price / pos["avg_price"] - 1) * 100
        cash += net_return

        trades.append({
            "stock_code": pos["stock_code"], "entry_date": pos["entry_date"], "exit_date": final_date,
            "entry_price": pos["avg_price"], "exit_price": exit_price, "quantity": exit_qty,
            "lots": pos["remaining_lots"], "pnl": pnl, "pnl_pct": pnl_pct,
            "exit_reason": "END", "trigger": pos["trigger"], "hold_days": pos["hold_days"],
        })

    total_trades = len(trades)
    if total_trades == 0:
        print("\n[BACKTEST V2] No trades executed in test window.")
        return

    df_trades = pd.DataFrame(trades)
    df_equity = pd.DataFrame(equity_curve)

    winning = df_trades[df_trades["pnl"] > 0]
    losing = df_trades[df_trades["pnl"] <= 0]
    win_rate = len(winning) / total_trades * 100
    total_profit = winning["pnl"].sum() if not winning.empty else 0.0
    total_loss = losing["pnl"].sum() if not losing.empty else 0.0
    net_profit = total_profit + total_loss
    final_capital = cash
    profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float("inf")

    df_equity["peak"] = df_equity["total"].cummax()
    df_equity["drawdown"] = (df_equity["total"] - df_equity["peak"]) / df_equity["peak"] * 100
    max_drawdown = df_equity["drawdown"].min()
    total_return_pct = (final_capital / INITIAL_CAPITAL - 1) * 100

    bench = idx_df[(idx_df["trade_date"] >= trading_days[0]) & (idx_df["trade_date"] <= trading_days[-1])]
    bench_ret = (bench["close"].iloc[-1] / bench["close"].iloc[0] - 1) * 100 if len(bench) >= 2 else float("nan")

    print("\n" + "=" * 70)
    print("BACKTEST V2 RESULTS (out-of-sample test window only)")
    print("=" * 70)
    print(f"  Test window     : {trading_days[0]} .. {trading_days[-1]}")
    print(f"  Net Profit      : Rp {net_profit:,.0f} ({total_return_pct:+.2f}%)")
    print(f"  Benchmark IHSG  : {bench_ret:+.2f}% (alpha {total_return_pct - bench_ret:+.2f}%)")
    print(f"  Total Trades    : {total_trades}")
    print(f"  Win Rate        : {win_rate:.1f}%")
    print(f"  Profit Factor   : {profit_factor:.2f}")
    print(f"  Max Drawdown    : {max_drawdown:.2f}%")
    print("=" * 70)

    notes = (
        f"V2: HMM per-stock gate (block BEARISH only) + ADTV>=Rp{cfg.ADTV_MIN:,.0f} liquidity filter, "
        f"min-hold {cfg.MIN_HOLD_DAYS}d, cooldown {cfg.COOLDOWN_DAYS}d after SL, "
        f"asymmetric fees (buy {cfg.BUY_FEE*100:.2f}%/sell {cfg.SELL_FEE*100:.2f}%). "
        f"Train split used only to freeze HMM models ({all_trading_days[0]}..{split_date}); "
        f"these metrics are the held-out test window only, never seen during model fitting."
    )

    try:
        run_res = supabase.table("backtest_runs").insert({
            "version": BACKTEST_VERSION,
            "period_start": trading_days[0].isoformat(),
            "period_end": trading_days[-1].isoformat(),
            "initial_capital": INITIAL_CAPITAL,
            "final_capital": final_capital,
            "net_profit_pct": total_return_pct,
            "benchmark_pct": bench_ret,
            "alpha_pct": total_return_pct - bench_ret,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": None if profit_factor == float("inf") else profit_factor,
            "max_drawdown": max_drawdown,
            "notes": notes,
            "strategy_summary": notes,
            "is_published": BACKTEST_PUBLISH,
        }).execute()
        run_id = run_res.data[0]["id"]

        trade_rows = [{
            "run_id": run_id, "stock_code": tr["stock_code"],
            "entry_date": tr["entry_date"].isoformat(), "exit_date": tr["exit_date"].isoformat(),
            "entry_price": float(tr["entry_price"]), "exit_price": float(tr["exit_price"]),
            "lots": int(tr["lots"]), "pnl": float(tr["pnl"]), "pnl_pct": float(tr["pnl_pct"]),
            "exit_reason": tr["exit_reason"], "trigger": tr.get("trigger"),
            "hold_days": int(tr["hold_days"]) if pd.notna(tr.get("hold_days")) else None,
        } for _, tr in df_trades.iterrows()]
        equity_rows = [{
            "run_id": run_id, "date": row["date"].isoformat(), "portfolio_value": float(row["total"]),
            "drawdown_pct": float(row["drawdown"]), "regime": get_regime(idx_df, row["date"]),
        } for _, row in df_equity.iterrows()]

        for i in range(0, len(trade_rows), 500):
            supabase.table("backtest_trades").insert(trade_rows[i:i + 500]).execute()
        for i in range(0, len(equity_rows), 500):
            supabase.table("backtest_equity").insert(equity_rows[i:i + 500]).execute()

        print(f"\n[OK] Saved to Supabase: backtest_runs id={run_id} "
              f"(version={BACKTEST_VERSION}, published={BACKTEST_PUBLISH})")
    except Exception as e:
        print(f"WARNING: Failed to save to Supabase: {e}")


if __name__ == "__main__":
    run_backtest_v2()
```

- [ ] **Step 2: Commit**

```bash
git add src/backtest_v2.py
git commit -m "feat(v2): backtest_v2.py — out-of-sample simulation with HMM gate + risk mgmt"
```

---

## Task 13: `src/screener_v2.py` — console-only live validation

**Files:**
- Create: `src/screener_v2.py`

**Interfaces:**
- Consumes: `data_fetch`, `hmm_model`, `strategy.add_features`/`get_signals`, `config`.
- Produces: console output only. No Telegram, no `screener_results` writes — V1's `screener.py` remains the only production write path.

- [ ] **Step 1: Write `src/screener_v2.py`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add src/screener_v2.py
git commit -m "feat(v2): screener_v2.py — console-only live validation, no production writes"
```

---

## Task 14: End-to-end acceptance run

**Files:** None — manual verification.

- [ ] **Step 1: Run the full test suite one more time**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Train HMM models**

```bash
SUPABASE_URL=<url> SUPABASE_KEY=<anon key> python src/train_hmm.py
```

Expected: prints train/test split dates, then a summary line like `Fitted N models, skipped X (illiquid), Y (insufficient history), out of Z total tickers.` N should be meaningfully > 0 (if 0, stop and investigate before continuing — either the liquidity bar or `HMM_MIN_HISTORY_DAYS` is misconfigured, or Task 1's bucket/policies weren't applied correctly).

- [ ] **Step 3: Run V2 backtest**

```bash
SUPABASE_URL=<url> SUPABASE_KEY=<anon key> python src/backtest_v2.py
```

Expected: prints the test-window-only results block, ends with `[OK] Saved to Supabase: backtest_runs id=<N> (version=v2-dev, published=False)`.

- [ ] **Step 4: Compare against V1 on the same window**

Run via Supabase `execute_sql` (`project_id: soddgoonjnfclabrijtn`):

```sql
select id, version, period_start, period_end, net_profit_pct, alpha_pct, win_rate,
       profit_factor, max_drawdown, total_trades
from backtest_runs
where version in ('v1', 'v2-dev')
order by created_at desc
limit 5;
```

Read the V2 row's `period_start`/`period_end` (the test window) and sanity-check it against V1's published run's alpha/drawdown/win-rate for the *same* sub-period — per the spec's validation plan, the question is whether V2's per-trade edge and drawdown hold up out-of-sample, not whether its total profit is higher than V1's full-period number.

- [ ] **Step 5: Run V2 screener and eyeball against V1's actual Telegram signal for today**

```bash
SUPABASE_URL=<url> SUPABASE_KEY=<anon key> python src/screener_v2.py
```

Compare the printed candidates (and their `HMM` column) against whatever V1's `screener.py` sent to Telegram today. Expect V2's list to be a subset of V1's (stricter gates) — investigate if V2 shows tickers V1 didn't, since that would indicate a gate bug rather than a stricter filter.

- [ ] **Step 6: Report back**

Summarize for the user: how many stocks got HMM models, V2 test-window metrics vs V1's same-window numbers, and today's V2 vs V1 candidate list — so they can decide whether to bump `HMM_VERSION`/iterate on gates, or move toward promoting V2 (`is_published=true`) and eventually cutting over `screener.py`/`backtest.py` — both explicitly future, user-approved steps outside this plan's scope.

---

## Self-Review Notes

- **Spec coverage:** Layer 0 (ADTV) → Task 9/10. Layer 1 (per-stock HMM, BEARISH-only gate) → Tasks 5-7, 9-10. Two-Factor entry → Task 10. Train/test split → Tasks 5, 11, 12. Min-hold (SL always active) → Task 12. Cooldown → Tasks 4, 12. Asymmetric fees → Tasks 3, 12. Model lifecycle/versioning → Tasks 1, 7, 11. Everything from the spec has a task.
- **Placeholder scan:** no TBD/TODO; every step has complete, runnable code.
- **Type consistency checked:** `hmm_model.fit_stock_hmm` return shape (`{"scaler", "model", "state_label_map"}`) matches what `infer_hmm_state`, `save_artifact`, and the test fakes all consume. `risk.is_in_cooldown`/`min_hold_elapsed`/`apply_fee` signatures match their call sites in `backtest_v2.py` exactly. `get_signals()`'s new `adtv_min`/`hmm_gate` params match how `backtest_v2.py` and `screener_v2.py` call it.
- **Resolved open question from spec:** live cooldown population — resolved as backtest-only (in-memory `last_sl_idx` dict); `screener_v2.py` has no portfolio to track exits against, so cooldown doesn't apply live. No `sl_cooldowns` table needed.
