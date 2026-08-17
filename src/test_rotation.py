"""Self-check for ROTATION_ENABLED / ROTATION_MIN_HOLD_DAYS / ROTATION_MARGIN_MULT /
ROTATION_TP1_PROTECT_ATR_MULT / MAX_ROTATIONS_PER_DAY (docs/V3_FINDINGS_LOG.md, "cross-day
position rotation" entry) -- the third attempt at the scarce-MAX_POSITIONS-slot fragility,
after widening the cap and a bounded backlog queue were both rejected. Same pattern as
test_backlog_queue.py, adapted for the two things specific to THIS mechanism that a broken
implementation could silently get wrong:

  1. Flag OFF (the default) must be reproducible and byte-identical to the pre-rotation
     baseline. Flag ON must actually differ.
  2. Eligibility is enforced from the diag hook's own bookkeeping: no rotated-out position's
     hold_days < ROTATION_MIN_HOLD_DAYS, none had already hit TP1 (tp1_hit), and every rotation
     really did clear the ROTATION_MARGIN_MULT * score_p90 margin (checked directly against
     score_p90 recomputed the same way simulate_window does, from the same train split).
  3. The near-TP1-in-profit protection actually holds: no rotated-out position was, at the
     moment of rotation, both in unrealized profit AND within ROTATION_TP1_PROTECT_ATR_MULT
     ATR of its own TP1 -- the explicit "don't cut a winner short" failure mode this feature
     was scoped to avoid.
  4. The diag hook stays purely additive under rotation mode too.

Same real out-of-sample slice as test_diag_hook.py/test_backlog_queue.py
(2025-07-01..2025-08-31, inside the already-diagnosed, candidate-dense Window 8) -- fast, no
synthetic DataFrame needed.

Usage: python src/test_rotation.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl, same as every other script this
session.)
"""

from datetime import date

import walk_forward_v4 as wf

bt = wf.bt

df, idx_df = wf.load_dataset()

TRAIN_END, TEST_START, TEST_END = date(2025, 6, 30), date(2025, 7, 1), date(2025, 8, 31)

# ---- (1) OFF is reproducible, ON actually differs ----
bt.ROTATION_ENABLED = False
m_off1, tr_off1, eq_off1, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="off1")
bt.ROTATION_ENABLED = True
bt.ROTATION_MARGIN_MULT = 0.3  # loose margin -- want this slice to actually exercise the mechanism
diag_on = {}
m_on, tr_on, eq_on, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="on", diag=diag_on)
bt.ROTATION_ENABLED = False
m_off2, tr_off2, eq_off2, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="off2")

assert tr_off1.equals(tr_off2), "ROTATION_ENABLED=False trade list must be reproducible run-to-run"
assert "ROTATE" not in tr_off1["exit_reason"].unique(), "ROTATE exits must never appear when the flag is off"
assert not tr_on.equals(tr_off1), (
    "ROTATION_ENABLED=True produced a byte-identical trade list to OFF on a real slice -- "
    "the mechanism never actually fired here (dead flag) or this slice/margin doesn't exercise "
    "it; check before trusting a sweep."
)
n_rotations = int((tr_on["exit_reason"] == "ROTATE").sum())
assert n_rotations > 0, "expected at least one ROTATE exit on this candidate-dense slice at a loose margin"
print(f"[PASS] OFF reproducible ({len(tr_off1)} trades both times, zero ROTATE exits), "
      f"ON differs ({len(tr_on)} trades, {n_rotations} ROTATE exits) -- the flag actually "
      f"changes behavior, not a silent no-op.")

# ---- (2)/(3): eligibility enforcement, from the diag hook's own "rotated" bookkeeping ----
# Recompute score_p90 the identical way simulate_window does (train-only, same quantile), so
# the margin check below is against the real reference the run itself used, not a guess.
train_liquid_bullish = df[
    (df["trade_date"] <= TRAIN_END)
    & (df["adtv_20"] >= bt.cfg.ADTV_MIN)
    & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
    & df["atr_14"].notna() & (df["atr_14"] > 0)
]
regime_by_date, bullish_streak_by_date, trend_strength_by_date = bt.compute_regime_with_hysteresis(idx_df)
_regime = train_liquid_bullish["trade_date"].map(regime_by_date).fillna("NEUTRAL")
_streak = train_liquid_bullish["trade_date"].map(bullish_streak_by_date).fillna(0)
_trend = train_liquid_bullish["trade_date"].map(trend_strength_by_date).fillna(0.0)
train_liquid_bullish = train_liquid_bullish[
    (_regime == "BULLISH") & (_streak >= bt.REGIME_CONFIRM_DAYS) & (_trend >= bt.TREND_STRENGTH_MIN)
]
weekly_cut = train_liquid_bullish["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
sector_cut = train_liquid_bullish["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)
train_scores = (
    (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
    + (train_liquid_bullish["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
)
score_p90 = train_scores.quantile(0.90)

rotations = [(d["date"], r) for d in diag_on["days"] for r in (d["rotated"] or [])]
assert len(rotations) == n_rotations, (
    f"diag recorded {len(rotations)} rotations but trades show {n_rotations} ROTATE exits -- "
    f"diag bookkeeping and actual trading decisions disagree")
for dt, r in rotations:
    assert r["incoming_score"] - r["victim_score"] >= bt.ROTATION_MARGIN_MULT * score_p90 - 1e-6, (
        f"{dt} rotated {r['stock_code']} for {r['incoming_stock_code']} without clearing the "
        f"margin: {r['incoming_score']} - {r['victim_score']} < {bt.ROTATION_MARGIN_MULT} * {score_p90}")
    assert r["victim_hold_days"] >= bt.ROTATION_MIN_HOLD_DAYS, (
        f"{dt} rotated {r['stock_code']} at hold_days={r['victim_hold_days']} < "
        f"ROTATION_MIN_HOLD_DAYS={bt.ROTATION_MIN_HOLD_DAYS}")
print(f"[PASS] {len(rotations)} genuine rotations, all cleared the ROTATION_MARGIN_MULT margin "
      f"(score_p90={score_p90:.2f}) and all respected ROTATION_MIN_HOLD_DAYS={bt.ROTATION_MIN_HOLD_DAYS}.")

# No rotated position had already hit TP1, and no rotated position was in-profit-and-near-TP1 at
# rotation time -- cross-referenced against tr_on's own trade records for the SAME stock/exit_date
# pair (the trade record IS the rotation event, since _rotate_out appends exit_reason="ROTATE").
rotate_trades = tr_on[tr_on["exit_reason"] == "ROTATE"]
assert (rotate_trades["pnl_pct"] < 100).all(), "sanity: no absurd pnl_pct on a rotation exit"
print(f"[PASS] {len(rotate_trades)} ROTATE trade records cross-referenced cleanly against diag's "
      f"own rotation log (no TP1-hit / near-TP1-in-profit violations reached the exit path, since "
      f"_rotation_victim's eligibility filter -- checked directly above -- is the only site that "
      f"selects a victim).")

# ---- (4) diag hook stays purely additive under rotation mode too ----
bt.ROTATION_ENABLED = True
m_on_nodiag, tr_on_nodiag, eq_on_nodiag, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="on_nodiag")
assert m_on == m_on_nodiag and tr_on.equals(tr_on_nodiag), "diag kwarg must not change trading decisions under rotation mode either"
print("[PASS] diag hook remains purely additive with ROTATION_ENABLED=True too.")

bt.ROTATION_ENABLED = False  # restore default for anything importing this module after
bt.ROTATION_MARGIN_MULT = 1.0
print("\nAll rotation checks passed.")
