# V2 Screener/Backtester — HMM Regime Confirmation + Anti-Overfitting Harness

## Context

V1 (live in production, `main` branch, powers the Telegram cron and the Neira website) uses threshold-based rules for everything: IHSG regime is close-vs-MA50, entry signals are 4 boolean technical conditions, liquidity filter is raw volume, and the published backtest is a single static window with no train/test discipline — real risk of the headline numbers being in-sample-optimistic rather than a genuine forward-looking edge.

V2's goal: make the system honest about out-of-sample robustness before it's trusted with more capital or shown more prominently, per user's explicit framing ("jangan halusinasi profit di in-sample data"). This is internal core-system work only — the website is untouched until V2 is validated.

## Non-negotiable ground rules (carried over from V1)

- Never alter or edit `ihsg_eod` / `index_eod` tables — fed by the user's own n8n pipeline.
- `strategy.py` stays the single source of signal logic shared by `screener.py` (live) and `backtest.py` (simulation) — never duplicate signal logic in either consumer.
- V1 stays live and untouched in production until V2 is validated and the user explicitly approves cutover. V2 development happens on config flags / new files, not by mutating V1's proven path.

## Architecture

```
Layer 0: Liquidity gate (ADTV >= Rp 1B, 20-day rolling)     [strategy.py]
Layer 1: Per-stock HMM regime confirm (block BEARISH only)   [hmm_model.py]
Layer 2: Existing V1 technical signals (unchanged)            [strategy.py]
Layer 3: Portfolio risk mgmt — IHSG macro regime sizing        [backtest.py / screener.py]
         (unchanged) + new: min-hold, cooldown, asymmetric fees
```

The IHSG-level macro regime (`get_regime()`, position sizing / max-positions / alloc% by BULLISH/NEUTRAL/BEARISH) is **kept as-is** — that's a portfolio risk-sizing decision, a different job from entry confirmation. The new per-stock HMM is an *additional* required gate at the entry-signal layer: a stock's own technical signal can only fire if that stock's own HMM dominant state is NOT BEARISH. Two regime concepts coexist, each doing a distinct job.

## Layer 0 — Liquidity gate

New feature in `add_features()`: `adtv_20 = (close_price * volume).rolling(20, min_periods=20).mean()`.

Hard filter (config: `ADTV_MIN = 1_000_000_000`): stocks with `adtv_20 < ADTV_MIN` are excluded before HMM inference and before technical signal evaluation — same slot as V1's existing `illiquid` volume filter, now Rupiah-value-based and set to a realistic exit-liquidity bar instead of an arbitrary raw-volume cutoff.

## Layer 1 — Per-stock HMM regime detection

**Model:** `hmmlearn.hmm.GaussianHMM`, `n_components=3`, `covariance_type="diag"` (avoids singular-covariance failures on thin per-stock series), fixed `random_state` for reproducibility.

**Features** (per stock, daily, matching the brief's suggested feature set):
- `return` = `close_price.pct_change()`
- `range` = `(high - low) / close_price`, sanitized the same way `backtest.py`'s existing `get_bar()` already sanitizes OHLC (missing/invalid high/low collapse to close)
- `log_volume_change` = `log(volume / volume.shift(1).clip(lower=1))`

All three z-scored with a `StandardScaler` fit **only on that stock's train-split rows** — the scaler is part of the frozen artifact, never refit on test or live data.

**State labeling:** hmmlearn states are unordered. After fitting, rank the 3 states by their fitted mean `return` component (ascending): lowest → BEARISH, middle → SIDEWAYS, highest → BULLISH. This label map is saved alongside the model.

**Minimum-history gate** (config: `HMM_MIN_HISTORY_DAYS = 300`): a stock needs at least this many clean trading days in the train split to attempt fitting. Below that, or if `hmmlearn` fails to converge, the stock is excluded from the V2 candidate universe entirely — no fallback to V1's threshold logic for that ticker. No signal is better than a signal from a model that hasn't seen enough data to have learned anything real.

**Confirmation rule (revised after design review):** gate on argmax state ∈ {BULLISH, SIDEWAYS} — reject only if argmax state is BEARISH. No additional probability-threshold knob on top of argmax — argmax already means "most likely state right now"; a second threshold is an extra parameter to overfit later without a principled way to set it.

Requiring argmax == BULLISH outright was the first draft and it's wrong: V1's entire signal set (MA squeeze, BB squeeze, low bandwidth, flat price) is purpose-built to detect *accumulation during consolidation* — by construction a low-volatility, near-zero-recent-return phase, which the HMM's return-ranked labeling will mark SIDEWAYS, not BULLISH (BULLISH requires already-elevated mean return, i.e. the move has already happened). A BULLISH-only gate would systematically reject the exact setups the strategy targets and only admit stocks after they've already broken out — turning an accumulation detector into a late-momentum chaser. SIDEWAYS is exactly the state the technical layer is designed to catch and act as the final trigger inside; HMM's job here is narrower than "confirm bullishness" — it's "reject confirmed distribution," i.e. keep out of names where the HMM's own read of return/range/volume already says smart money is unloading (BEARISH), and let the existing 4-condition technical logic decide entry timing within everything else.

**Inference:** a single batched `predict_proba()` call per stock over its full available history, computed once during feature engineering (same pass as `add_features()` today) — not a per-day rolling-window recomputation. This is both the statistically correct filtered-probability approach (uses full history up to each day) and matches V1's existing "compute indicators once per stock" architecture.

**Model lifecycle:** `src/train_hmm.py` (new, manual-trigger script) fits scaler + HMM per qualifying stock on the train split only, serializes each to Supabase Storage bucket `hmm-models`, path `v2/{HMM_VERSION}/{stock_code}.pkl`. Both `screener.py` (live) and `backtest.py` (test-window simulation) load frozen artifacts and never refit. Retraining = rerun the script manually, bump `HMM_VERSION`; the previous version's artifacts stay in Storage until the new version is validated (same "version" pattern already used for `backtest_runs.version`).

## Anti-overfitting backtest harness

Chronological split, no shuffling (this is time-series data — random shuffling would leak future information into training). Split boundary: train = everything before the cutoff, test = the last 30% of available history, computed dynamically off the fetched date range rather than a hardcoded calendar date (stays correct as more history accumulates over time).

Scaler + all per-stock HMM models are fit once, on train data only. `backtest.py`'s existing day-by-day simulation loop is otherwise unchanged, but now only runs over the test window — that run *is* the out-of-sample validation. The report/`backtest_runs` insert shows both windows' metrics side by side: train-period metrics for reference/sanity-check only, test-period metrics are the ones that get published and matter for the go/no-go decision on V2.

## Risk management additions

- **Min hold period** (config: `MIN_HOLD_DAYS = 3`): for the first N trading days after entry, TP1/Trailing exits are suppressed (avoids whipsaw profit-taking on 1-2 day noise). **SL fires every day starting day 1** — capital protection is never suppressed, confirmed non-negotiable during design review.
- **Cooldown period** (config: `COOLDOWN_DAYS = 10`): after a stock is stopped out via SL, new entries on that same ticker are blocked until the cooldown elapses. Backtest: an in-memory `last_sl_date` dict per stock_code, checked at entry time alongside the existing "already in positions" check. Live: a new Supabase table `sl_cooldowns(stock_code, sl_date)` — `screener.py` inserts a row on every SL-triggered close (if this data even reaches it; V1's screener doesn't currently track exits since it doesn't manage a live portfolio, so this needs a decision at implementation time about how cooldown state is populated live — flagged as an open question for the implementation plan, not blocking the design).
- **Asymmetric transaction cost**: replaces flat `TRANSACTION_COST = 0.002` with `BUY_FEE = 0.0018` and `SELL_FEE = 0.0028` (typical IDX retail broker fee + 0.1% sell-side bursa levy), applied wherever `TRANSACTION_COST` is currently used in `backtest.py`'s entry cost-basis and exit gross-return calculations.

## New/changed files

- `src/hmm_model.py` — new: fit, state-label, save/load (Supabase Storage), batched inference helpers.
- `src/train_hmm.py` — new: offline manual-trigger script.
- `src/strategy.py` — add `adtv_20` feature + liquidity gate; wire HMM confirmation into `get_signals()`.
- `src/backtest.py` — train/test split harness, cooldown tracker, min-hold logic, asymmetric fees, load frozen HMM artifacts (no live fitting).
- `src/screener.py` — load frozen HMM artifacts, cooldown table check.
- `src/config.py` — new constants: `ADTV_MIN`, `MIN_HOLD_DAYS`, `COOLDOWN_DAYS`, `BUY_FEE`, `SELL_FEE`, `HMM_MIN_HISTORY_DAYS`, `HMM_VERSION`.
- New Supabase: Storage bucket `hmm-models`, table `sl_cooldowns`.
- `requirements.txt`: add `hmmlearn`, `scikit-learn`.

## Validation plan

Compare V2's test-window metrics against V1's already-published run over the *same* test window (apples-to-apples, not V1's full-period numbers). Metrics: alpha vs IHSG, win rate, max drawdown, profit factor, trade count. V2 trades a smaller, stricter-filtered universe (liquidity + HMM confirmation), so fewer trades are expected — the question this validates is whether per-trade edge and drawdown genuinely hold up on unseen data, not whether total profit is higher than V1's number (which already carries the in-sample bias this whole effort exists to remove).

V2 stays unpublished (`backtest_runs.is_published = false`, `version = 'v2-dev'`) until the user reviews test-window results and explicitly approves promotion — mirrors the existing versioning mechanism already built for this exact purpose.

## Open questions carried into implementation

1. Live cooldown population: `screener.py` doesn't currently track its own executed trades/exits (it only emits signals) — needs a decision on how `sl_cooldowns` gets populated in live use, or whether cooldown is backtest-only for V2 launch.
2. Supabase Storage bucket setup — needs to be created (new infra, not yet provisioned) before `train_hmm.py` can run.
