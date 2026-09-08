"""Stage 1 of the NICE-pattern research pass (2026-08-27, see docs/V3_FINDINGS_LOG.md):
cheap feasibility check on whether buying ON a big-up-move day itself (variant b: buy the
breakout/ARA day) or the day after (variant c: the already-rejected spike-confirm pattern)
would even be fillable in principle. Reuses the project's own board-limit-aware
is_ara_locked() (src/backtest_v4.py) rather than a naive open==high==low check -- that
function already accounts for IDX's per-board 10/20/25/35% limit tiers inferred from each
stock's own trailing history, which a fixed threshold can't.

Run: .venv/Scripts/python.exe src/scratch_consolidation_ara_feasibility.py
(from the worktree root; needs .cache/walk_forward_data_2021-01-01_2026-06-30.pkl, the
existing walk_forward_v4.py dataset cache)."""
import sys
import pickle

sys.path.insert(0, "src")
import backtest_v4 as bt
import config as cfg

with open(".cache/walk_forward_data_2021-01-01_2026-06-30.pkl", "rb") as f:
    df, idx_df = pickle.load(f)
df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)

# General population: any day with a >=20% close-over-previous move (no volume filter).
big_up = df[(df["previous"] > 0) & ((df["close_price"] / df["previous"] - 1) >= 0.20)].copy()
big_up["locked"] = [
    bt.is_ara_locked(r.previous, r.close_price, r.high, r.observed_max_move)
    for r in big_up.itertuples()
]
print(f"n big-up days (>=20% move, unfiltered): {len(big_up)}")
print(f"ARA-locked at the close (no realistic fill at that price): "
      f"{big_up['locked'].sum()}/{len(big_up)} = {100 * big_up['locked'].mean():.1f}%")

big_up["range_pct"] = (big_up["high"] - big_up["low"]) / big_up["previous"]
zero_range = (big_up.loc[big_up["locked"], "range_pct"] < 0.005).mean()
print(f"Of locked days, fraction with essentially ZERO intraday range (untradeable all "
      f"day, not just pinned at the close): {100 * zero_range:.1f}%")

liquid_mask = (
    (big_up["adtv_20"] >= cfg.ADTV_MIN)
    & big_up["atr_14"].notna() & (big_up["atr_14"] > 0)
    & ((big_up["atr_14"] / big_up["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
)
liquid_big_up = big_up[liquid_mask]
print(f"\nn liquid big-up days (existing ADTV+ATR filter applied): {len(liquid_big_up)}")
print(f"ARA-locked rate within the liquid universe: {100 * liquid_big_up['locked'].mean():.1f}%")

# Cross-check against the base-rate study's own exact spike definition (932 episodes,
# volume>=10x trailing avg, move>=20%, ADTV_MIN, ATR/price<=10%) for direct comparability.
spike = df[
    (df["avg_vol_20_prev"] > 0)
    & (df["volume"] >= 10.0 * df["avg_vol_20_prev"])
    & ((df["close_price"] / df["previous"] - 1) >= 0.20)
    & (df["adtv_20"] >= cfg.ADTV_MIN)
    & (df["atr_14"] / df["close_price"] <= 0.10)
].copy()
spike["locked"] = [
    bt.is_ara_locked(r.previous, r.close_price, r.high, r.observed_max_move)
    for r in spike.itertuples()
]
print(f"\nn spike episodes (base-rate study's exact definition, sanity-check n should be "
      f"~932): {len(spike)}")
print(f"ARA-locked on the spike day itself: {spike['locked'].sum()}/{len(spike)} = "
      f"{100 * spike['locked'].mean():.1f}%")
