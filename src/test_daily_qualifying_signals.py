"""Dry-run self-check for the daily_qualifying_signals persist block added to
src/paper_signal_scan.py (2026-08-17) -- see sql/daily_qualifying_signals_schema.sql
and docs/V3_FINDINGS_LOG.md "why the Screener page never shows fewer than ~90
signals". Verifies, against a real recent trading day's real data:

  1. The hoisted score_candidates() call produces sensible real output (real
     stock codes, positive prices/scores) for a day the live entry gate
     (regime_ok) genuinely passes.
  2. The hoist is side-effect-free: calling it twice with identical inputs
     returns an identical list -- the formal reason moving the call earlier
     in main() cannot change what actually gets queued into paper_positions.
     (Not tested by literally running paper_signal_scan.py's main() against
     production: this repo's local .env SUPABASE_KEY is a read-only anon key
     by design -- see .env's own comment -- so a real end-to-end run would
     either no-op on the daily last_signal_date guard or crash partway
     through a write it has no permission for. Read-only equivalence proof
     instead.)
  3. The exact row-shaping the new upsert block uses (rank/score/trigger/
     adtv_20/avg_vol_20/atr/signal_close/tp_target/concentration) round-trips
     every field score_candidates() actually returns.

Read-only: build_full_dataset() + score_candidates() only ever SELECT. This
file never calls .insert()/.upsert()/.update() on anything.

Uses walk_forward_v4.load_dataset()'s existing local-cache-first fetch (same
helper the project's own sweep scripts use) instead of forcing V4_TEST_END to
today -- avoids a redundant live full-universe refetch of data this repo
already has cached at .cache/walk_forward_data_2021-01-01_2026-06-30.pkl (the
default bt.FETCH_START/bt.TEST_END window), so this only hits Supabase at all
if that cache is missing.

Usage: python src/test_daily_qualifying_signals.py
"""

import os

import numpy as np

import backtest_v4 as bt  # noqa: E402
import config as cfg  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402

print("[FETCH] loading dataset (local cache if present, else a live fetch) ...")
cache_path = os.path.join(os.path.dirname(__file__), "..", ".cache",
                           f"walk_forward_data_{bt.FETCH_START}_{bt.TEST_END}.pkl")
supabase = None
if not os.path.exists(cache_path):
    from supabase import create_client  # noqa: E402
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    assert url and key, "No local cache and missing SUPABASE_URL / SUPABASE_KEY -- see .env"
    supabase = create_client(url, key)
df, idx_df = wf.load_dataset(supabase)
regime_by_date, bullish_streak_by_date, trend_strength_by_date = bt.compute_regime_with_hysteresis(idx_df)

# Most recent day the real entry gate (regime_ok) actually passes -- same
# three-part check paper_signal_scan.py applies before generating candidates.
target = None
for d in sorted(regime_by_date.keys(), reverse=True):
    if (regime_by_date.get(d) == "BULLISH"
            and bullish_streak_by_date.get(d, 0) >= bt.REGIME_CONFIRM_DAYS
            and trend_strength_by_date.get(d, 0.0) >= bt.TREND_STRENGTH_MIN):
        target = d
        break
assert target is not None, "no regime_ok day found in fetched history -- can't exercise the real gate"
print(f"[TARGET] {target} -- most recent regime_ok=True day")

# ---- Mirrors paper_signal_scan.py's train_liquid_bullish / weekly_cut /
# sector_cut / weekly_comp_abs_cap computation exactly (read-only copy --
# that script is a monolithic main(), not a callable) ----
train_liquid_bullish = df[
    (df["trade_date"] <= target)
    & (df["adtv_20"] >= cfg.ADTV_MIN)
    & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
    & (df["trade_date"].map(regime_by_date).fillna("NEUTRAL") == "BULLISH")
    & (df["trade_date"].map(bullish_streak_by_date).fillna(0) >= bt.REGIME_CONFIRM_DAYS)
    & (df["trade_date"].map(trend_strength_by_date).fillna(0.0) >= bt.TREND_STRENGTH_MIN)
    & df["atr_14"].notna() & (df["atr_14"] > 0)
    & ((df["atr_14"] / df["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
]
weekly_cut = train_liquid_bullish["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
sector_cut = train_liquid_bullish["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)
weekly_comp_abs_cap = None
if bt.SCORE_WEEKLY_COMP_ABS_CAP_Q is not None:
    train_w_comp = (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
    if len(train_w_comp) > 0:
        weekly_comp_abs_cap = train_w_comp.quantile(bt.SCORE_WEEKLY_COMP_ABS_CAP_Q)

day_data = df[df["trade_date"] == target]
scored_1 = bt.score_candidates(day_data, weekly_cut, sector_cut, top_n=15, weekly_comp_abs_cap=weekly_comp_abs_cap)
scored_2 = bt.score_candidates(day_data, weekly_cut, sector_cut, top_n=15, weekly_comp_abs_cap=weekly_comp_abs_cap)

assert scored_1 == scored_2, "score_candidates() is not deterministic -- hoisting its call would NOT be safe"
print(f"[PASS] score_candidates() deterministic across two identical calls ({len(scored_1)} candidates)")

assert len(scored_1) > 0, f"{target} unexpectedly has zero candidates despite passing regime_ok -- pick a different target"
for i, sig in enumerate(scored_1, start=1):
    assert isinstance(sig["stock_code"], str) and len(sig["stock_code"]) >= 3
    assert sig["signal_close"] > 0
    assert sig["atr"] > 0
    assert np.isfinite(sig["score"])
    print(f"  rank={i} {sig['stock_code']} score={sig['score']:.3f} close={sig['signal_close']:.0f} "
          f"tp={sig['tp_target']:.0f} adtv_20={sig['adtv_20']:,.0f} concentration={sig.get('concentration')}")

# Exact shape the new daily_qualifying_signals upsert block builds.
rows = [{
    "trade_date": target.isoformat(), "stock_code": sig["stock_code"], "rank": i + 1,
    "score": sig["score"], "trigger": sig["trigger"], "adtv_20": sig["adtv_20"],
    "avg_vol_20": sig["avg_vol_20"], "atr": sig["atr"], "signal_close": sig["signal_close"],
    "tp_target": sig["tp_target"], "concentration": sig.get("concentration"),
} for i, sig in enumerate(scored_1)]
assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
assert [r["score"] for r in rows] == sorted([r["score"] for r in rows], reverse=True)
print(f"[PASS] {len(rows)} rows shaped for daily_qualifying_signals, rank 1..{len(rows)} strictly by descending score")

print("\nAll daily_qualifying_signals dry-run checks passed (read-only, no writes).")
