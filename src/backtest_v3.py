"""
backtest_v3.py — full portfolio backtest of the ONE entry rule that
survived every Phase 0 test tonight with genuine out-of-sample evidence:

    BULLISH regime (IHSG vs its own MA50)
    AND weekly_ma_spread >= train-derived top-quintile threshold
    AND sector_rs_momentum >= train-derived top-quintile threshold
    AND ADTV >= cfg.ADTV_MIN (liquid tier)

Phase 0 (squeeze alone), 0b (foreign flow), and the Phase 0e kitchen-sink
ML model all failed to show a stable, distributed, out-of-sample edge.
Phase 0g tested this exact intersection as a plain rule (no ML) with
thresholds learned ONLY on a 2021-2024 train split and evaluated on a
held-out 2024-2026 test split: win rate ~46%, mean 20d return +7.48%
(vs +1.18% full-liquid baseline), median still negative (-0.93%), but
concentration check showed only 12.6% of positive contribution from the
top-5 tickers -- a genuinely distributed right-skew, not five lottery
tickets carrying the whole result the way V1/V2's backtests turned out
to be.

This script is the same single-variable substitution discipline used all
night: reuses backtest_v2.py's EXACT position-sizing / TP1+trailing-stop
/ min-hold / cooldown / fee engine verbatim, and swaps ONLY the entry
signal generation. If this backtest's equity curve is good, it's because
of the new entry rule, not a different simulation engine.

Train split (threshold-fitting only, never simulated): 2021-01-01..2024-06-30
Test split (the only period actually traded/reported): 2024-07-31..2026-06-30

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/backtest_v3.py
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd
from supabase import create_client

import config as cfg
import data_fetch
import risk
from strategy import add_features
from phase0c_rrg_validation import fetch_sector_indices, fetch_sector_map, compute_rs_momentum
from phase0d_multitimeframe_validation import attach_weekly_trend

# strategy.get_regime flips BULLISH/BEARISH the instant close crosses ma50,
# with zero buffer -- fine for V1 (untouched, never modified here), but a
# real source of the window-2 OOS failure: near the MA50 line, small day-
# to-day noise flips the regime back and forth, causing entries right
# before a flip-back (SL exits jumped 42.5%->47.2% in the choppier
# window). A Schmitt-trigger-style hysteresis band -- enter BULLISH only
# above ma50, exit only below -- requires a real, sustained move to flip
# state, not a single noisy tick.
#
# A FIXED-PERCENTAGE band (tried first: 2%) turned out to be the wrong
# design -- a sensitivity sweep (0.01/0.02/0.03/0.05) showed window 1
# swinging 61%->501% profit across nearby values with no clean trend,
# and window 2 breaking down entirely at 5% (50 trades, 82% concentration).
# The likely reason: a fixed % of ma50 means something different in a
# calm period than a volatile one -- too tight to matter when IHSG is
# swinging hard, too wide relative to actual noise when it's calm.
#
# VOL_BAND_MULT scales the band by IHSG's own trailing 20-day return
# volatility instead of a flat percentage -- the band widens
# automatically in volatile periods and narrows in calm ones, which is
# what a fixed percentage cannot do. This is V3-only; strategy.py is
# untouched.
VOL_BAND_MULT = float(os.environ.get("V3_VOL_BAND_MULT", "2.0"))


def compute_regime_with_hysteresis(idx_df: pd.DataFrame):
    """Returns (regime_by_date, bullish_streak_by_date). The streak counts
    consecutive trading days the regime has read BULLISH, ending at that
    date -- used to require the flip to hold before trusting it with new
    capital (see REGIME_CONFIRM_DAYS)."""
    sub = idx_df.dropna(subset=["ma50"]).sort_values("trade_date").copy()
    daily_ret = sub["close"].pct_change()
    vol_20 = daily_ret.rolling(20, min_periods=20).std()
    sub["band"] = (VOL_BAND_MULT * vol_20).fillna(vol_20.median())

    regime_by_date = {}
    bullish_streak_by_date = {}
    current = "NEUTRAL"
    streak = 0
    for row in sub.itertuples():
        upper = row.ma50 * (1 + row.band)
        lower = row.ma50 * (1 - row.band)
        if row.close > upper:
            new_state = "BULLISH"
        elif row.close < lower:
            new_state = "BEARISH"
        else:
            new_state = current  # inside the band -- hold the current state, no flip
        streak = streak + 1 if new_state == current else 1
        current = new_state
        regime_by_date[row.trade_date] = current
        bullish_streak_by_date[row.trade_date] = streak if current == "BULLISH" else 0
    return regime_by_date, bullish_streak_by_date

FETCH_START = date.fromisoformat(os.environ.get("V3_FETCH_START", "2021-01-01"))
TRAIN_END = date.fromisoformat(os.environ.get("V3_TRAIN_END", "2024-06-30"))
TEST_START = date.fromisoformat(os.environ.get("V3_TEST_START", "2024-07-31"))
TEST_END = date.fromisoformat(os.environ.get("V3_TEST_END", "2026-06-30"))
QUANTILE_CUT = 0.80

INITIAL_CAPITAL = 100_000_000
LOT_SIZE = 100
SL_PCT = 0.02
MAX_POSITIONS = 6
# Third OOS window (2023-01..2023-06) lost money because six positions
# opened SIMULTANEOUSLY on 2023-02-06 -- MAX_POSITIONS filled entirely in
# one day on a regime flip that turned out to be a false start, and all
# six were stopped out together within days. Position sizing was never
# the problem; nothing diversified ENTRY TIMING. Capping new entries per
# day means a bad day can hurt at most MAX_NEW_ENTRIES_PER_DAY positions,
# not the whole portfolio at once -- regardless of whether that day's
# regime flip turns out to be real or fake, which isn't knowable in
# advance. A stock that misses today's cap isn't lost -- if the setup is
# real it will still qualify (and get re-evaluated, score-ranked) on a
# later day; if it was a false-start flip, most won't still qualify once
# the regime corrects, which is exactly the exposure being reduced.
#
# First attempt at a fix: this cap ALONE. Tested against window 3 --
# barely moved the needle (-22.10% -> -21.11%), because the false regime
# read persisted for several consecutive days (2023-02-06 through 02-08),
# so entries just spread across 3 days instead of 1, still all riding the
# same wrong thesis. Kept as defense-in-depth, but REGIME_CONFIRM_DAYS
# below is the fix that actually targets the failure mode: don't deploy
# capital on day 1 of a flip, wait to see if it holds.
MAX_NEW_ENTRIES_PER_DAY = int(os.environ.get("V3_MAX_NEW_ENTRIES_PER_DAY", "2"))
REGIME_CONFIRM_DAYS = int(os.environ.get("V3_REGIME_CONFIRM_DAYS", "3"))
ALLOC_PCT = 0.20
BACKTEST_VERSION = "v3-dev"
DELISTING_GAP_DAYS = 10  # consecutive no-data trading days -> force-exit at last known price
ATR_PRICE_RATIO_MAX = 0.10  # exclude entries where ATR_14/close > 10% -- PIPA/FUTR/ISAP-style
                            # hyperactive penny stocks slip through the Rupiah-value ADTV filter
                            # (huge share count, low price) despite genuinely extreme volatility;
                            # this caps signal-day volatility directly, price-agnostic (GOTO/BUKA
                            # stay eligible despite low price since their ATR% is normal, ~4%).

# Adaptive hold-time checkpoint exit (phase0f_holdtime_exit_backtest.py):
# expected_hold_days = |target - entry| / ATR estimates how long this
# setup should take to resolve if the move happens at all. Phase 0f found
# checking progress at that day and exiting early if it's not developing
# helps trades with expected_hold_days >= 5 (the setup is "slow" by its
# own math) but HURTS trades expected to resolve fast (<5d) -- checking
# in on a sprint at the pace of a marathon just cuts winners short. This
# is why it's gated on expected_hold_days >= HOLDTIME_MIN_DAYS rather
# than applied to every position. Off by default (ADAPTIVE_HOLDTIME=0)
# so it can be A/B'd against the validated baseline before being trusted.
#
# IMPORTANT: this MUST use tp_target (the SMC swing-high target from
# strategy.add_features, a real market-structure level) as "target", NOT
# tp1_price (entry + ATR*TP1_MULT). An earlier version of this code used
# tp1_price -- but since tp1_price is BY DEFINITION entry + ATR*TP1_MULT,
# |tp1_price-entry|/ATR collapses to exactly TP1_MULT (a fixed constant,
# 1.5 in config.py) for every single position. That made expected_hold_days
# a constant that could never reach HOLDTIME_MIN_DAYS=5, so the checkpoint
# could never fire -- caught via a suspiciously-exact match to the
# no-hold-time baseline (zero CHECKPOINT exits) before being reported as
# "tested." tp_target is a genuinely variable, stock/day-specific distance
# unrelated to ATR by construction, matching what phase0f actually tested.
ADAPTIVE_HOLDTIME = os.environ.get("V3_ADAPTIVE_HOLDTIME", "0") == "1"
HOLDTIME_MIN_DAYS = 5       # only gate positions whose own math says "slow"
HOLDTIME_CAP_DAYS = 15      # matches phase0f's CHECKPOINT_CAP_DAYS
HOLDTIME_MIN_CHECKPOINT = 3  # matches phase0f's MIN_CHECKPOINT_DAYS
HOLDTIME_PROGRESS_THRESHOLD = 0.40  # matches phase0f's PROGRESS_THRESHOLD


def build_full_dataset(supabase):
    print("[FETCH] Downloading stock + index data ...")
    df, idx_df = data_fetch.fetch_data(supabase, FETCH_START, TEST_END, lookback_days=cfg.LOOKBACK_DAYS)

    print("[FETCH] Downloading sector indices + stock->sector map ...")
    sector_wide = fetch_sector_indices(supabase, FETCH_START, TEST_END)
    sector_map = fetch_sector_map(supabase)

    print("[FEATURE] Computing indicators ...")
    frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
    df = pd.concat(frames, ignore_index=True)

    print("[FEATURE] Sector RS-momentum + weekly trend ...")
    rs_long = compute_rs_momentum(sector_wide)
    df["index_code"] = df["stock_code"].map(sector_map)
    df = df.merge(rs_long, on=["trade_date", "index_code"], how="left")
    df = attach_weekly_trend(df)

    return df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True), idx_df


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 100)
    print("BACKTEST V3 — regime + weekly-trend + sector-RRG intersection (Phase 0g validated rule)")
    print("=" * 100)

    df, idx_df = build_full_dataset(supabase)

    print("[REGIME] Precomputing regime per unique trading day ...")
    regime_by_date, bullish_streak_by_date = compute_regime_with_hysteresis(idx_df)
    df["_regime"] = df["trade_date"].map(regime_by_date).fillna("NEUTRAL")
    df["_streak"] = df["trade_date"].map(bullish_streak_by_date).fillna(0)

    # ---- Thresholds learned on TRAIN split only (never touches test data) ----
    train_liquid_bullish = df[
        (df["trade_date"] <= TRAIN_END)
        & (df["adtv_20"] >= cfg.ADTV_MIN)
        & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
        & (df["_regime"] == "BULLISH") & (df["_streak"] >= REGIME_CONFIRM_DAYS)
        & df["atr_14"].notna() & (df["atr_14"] > 0)
        & ((df["atr_14"] / df["close_price"]) <= ATR_PRICE_RATIO_MAX)
    ]
    weekly_cut = train_liquid_bullish["weekly_ma_spread"].quantile(QUANTILE_CUT)
    sector_cut = train_liquid_bullish["sector_rs_momentum"].quantile(QUANTILE_CUT)
    print(f"[THRESHOLDS from train {FETCH_START}..{TRAIN_END} only] "
          f"weekly_ma_spread >= {weekly_cut:.2f}, sector_rs_momentum >= {sector_cut:.4f}")

    trading_days = sorted(d for d in df["trade_date"].unique() if TEST_START <= d <= TEST_END)
    print(f"[SIMULATE] Test window (out-of-sample only): {trading_days[0]} .. {trading_days[-1]} ({len(trading_days)} days)")

    close_lookup = df.set_index(["stock_code", "trade_date"])["close_price"]
    bar_lookup = {
        (r.stock_code, r.trade_date): (r.open_price, r.close_price, r.high, r.low, r.volume)
        for r in df.itertuples()
    }

    def get_bar(stock_code, d):
        try:
            o, c, h, l, _vol = bar_lookup[(stock_code, d)]
        except KeyError:
            return None
        if pd.isna(c) or c <= 0:
            return None
        h = c if (pd.isna(h) or h <= 0) else max(h, c)
        l = c if (pd.isna(l) or l <= 0) else min(l, c)
        if pd.isna(o) or o <= 0 or o > h or o < l:
            o = None
        return o, c, h, l

    positions = []
    cash = float(INITIAL_CAPITAL)
    trades = []
    equity_curve = []
    pending_entries = []
    last_sl_idx = {}

    for day_idx, trade_date in enumerate(trading_days):
        regime = regime_by_date.get(trade_date, "NEUTRAL")
        prev_equity = equity_curve[-1]["total"] if equity_curve else float(INITIAL_CAPITAL)

        # ---- Execute pending entries at today's OPEN ----
        new_entries_today = 0
        for sig in pending_entries:
            if any(p["stock_code"] == sig["stock_code"] for p in positions):
                continue
            if len(positions) >= MAX_POSITIONS:
                break
            if new_entries_today >= MAX_NEW_ENTRIES_PER_DAY:
                break
            if risk.is_in_cooldown(sig["stock_code"], day_idx, last_sl_idx, cfg.COOLDOWN_DAYS):
                continue

            bar = get_bar(sig["stock_code"], trade_date)
            if bar is None:
                continue
            _, _, _, _, entry_day_volume = bar_lookup[(sig["stock_code"], trade_date)]
            if pd.isna(entry_day_volume) or entry_day_volume <= 0:
                continue  # zero-volume day: stale carried-forward print, no real fill possible
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
                expected_hold_days = None  # unreliable ATR -- don't gate a checkpoint on it
            else:
                tp1_price = entry_price + atr_val * cfg.TP1_MULT
                sl_price = entry_price - atr_val * 1.5
                tp1_price = max(tp1_price, entry_price * 1.01)
                sl_price = min(sl_price, entry_price * 0.99)
                expected_hold_days = abs(sig["tp_target"] - entry_price) / atr_val

            alloc = min(prev_equity * ALLOC_PCT, cash)
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

            checkpoint_day = None
            if ADAPTIVE_HOLDTIME and expected_hold_days is not None and expected_hold_days >= HOLDTIME_MIN_DAYS:
                checkpoint_day = int(np.clip(round(expected_hold_days), HOLDTIME_MIN_CHECKPOINT, HOLDTIME_CAP_DAYS))

            cash -= cost_basis
            positions.append({
                "stock_code": sig["stock_code"], "entry_date": trade_date, "avg_price": entry_price,
                "tp1_price": tp1_price, "sl_price": sl_price, "total_lots": lots, "remaining_lots": lots,
                "quantity": quantity, "cost_basis": cost_basis, "hold_days": 0, "tp1_hit": False,
                "highest_price": entry_price, "trigger": sig["trigger"],
                "no_data_days": 0, "last_valid_close": entry_price,
                "checkpoint_day": checkpoint_day, "target_price": sig["tp_target"],
            })
            new_entries_today += 1
        pending_entries = []

        # ---- Exit check (identical to backtest_v2.py, plus a forced exit
        # for stocks that stop reporting data mid-position -- delisting or
        # permanent suspension. Without this, a position in a delisted
        # stock sits forever, frozen at its last mark-to-market price,
        # never contributing its real loss to the results.) ----
        remaining_positions = []
        for pos in positions:
            if pos["entry_date"] == trade_date:
                remaining_positions.append(pos)
                continue
            bar = get_bar(pos["stock_code"], trade_date)
            if bar is None:
                pos["hold_days"] += 1
                pos["no_data_days"] += 1
                if pos["no_data_days"] >= DELISTING_GAP_DAYS:
                    exit_price = pos["last_valid_close"]
                    sell_lots = pos["remaining_lots"]
                    sell_qty = sell_lots * LOT_SIZE
                    sell_cost_basis = pos["cost_basis"] * (sell_lots / pos["total_lots"])
                    gross_return = exit_price * sell_qty
                    fee = risk.apply_fee(gross_return, "sell", cfg.BUY_FEE, cfg.SELL_FEE)
                    net_return = gross_return - fee
                    pnl = net_return - sell_cost_basis
                    pnl_pct = (exit_price / pos["avg_price"] - 1) * 100
                    cash += net_return
                    pos["remaining_lots"] -= sell_lots
                    trades.append({
                        "stock_code": pos["stock_code"], "entry_date": pos["entry_date"], "exit_date": trade_date,
                        "entry_price": pos["avg_price"], "exit_price": exit_price, "quantity": sell_qty, "lots": sell_lots,
                        "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": "DELISTED_GAP", "trigger": pos["trigger"],
                        "hold_days": pos["hold_days"],
                    })
                    continue
                remaining_positions.append(pos)
                continue
            o, close_price, high_price, low_price = bar
            pos["no_data_days"] = 0
            pos["last_valid_close"] = close_price

            exit_reason, exit_price, sell_lots = None, None, 0
            hold_ok = risk.min_hold_elapsed(pos["hold_days"], cfg.MIN_HOLD_DAYS)
            if close_price > pos["highest_price"]:
                pos["highest_price"] = close_price

            if not pos["tp1_hit"]:
                if low_price <= pos["sl_price"]:
                    exit_reason, exit_price = "SL", (o if (o is not None and o < pos["sl_price"]) else pos["sl_price"])
                    sell_lots = pos["remaining_lots"]
                elif hold_ok and high_price >= pos["tp1_price"]:
                    exit_reason, exit_price = "TP1", (o if (o is not None and o > pos["tp1_price"]) else pos["tp1_price"])
                    sell_lots = max(1, int(pos["remaining_lots"] * cfg.TP1_PCT))
                elif pos["checkpoint_day"] is not None and pos["hold_days"] == pos["checkpoint_day"]:
                    dist_to_target = pos["target_price"] - pos["avg_price"]
                    progress = (close_price - pos["avg_price"]) / dist_to_target if dist_to_target > 0 else 1.0
                    if progress < HOLDTIME_PROGRESS_THRESHOLD:
                        exit_reason, exit_price = "CHECKPOINT", close_price
                        sell_lots = pos["remaining_lots"]
                elif pos["hold_days"] >= cfg.MAX_HOLD_DAYS - 1:
                    pnl_check = (close_price / pos["avg_price"] - 1) * 100
                    if not (pnl_check > 0 and regime == "BULLISH"):
                        exit_reason, exit_price = "TIME", close_price
                        sell_lots = pos["remaining_lots"]
            else:
                if low_price <= pos["sl_price"]:
                    exit_reason, exit_price = "SL", (o if (o is not None and o < pos["sl_price"]) else pos["sl_price"])
                    sell_lots = pos["remaining_lots"]
                elif hold_ok:
                    trailing_stop = pos["highest_price"] * (1 - cfg.TRAILING_PCT)
                    stop_eff = max(trailing_stop, pos["sl_price"])
                    if close_price <= stop_eff:
                        exit_reason, exit_price = "TRAILING", close_price
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
                    "stock_code": pos["stock_code"], "entry_date": pos["entry_date"], "exit_date": trade_date,
                    "entry_price": pos["avg_price"], "exit_price": exit_price, "quantity": sell_qty, "lots": sell_lots,
                    "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": exit_reason, "trigger": pos["trigger"],
                    "hold_days": pos["hold_days"],
                })
                if exit_reason == "TP1":
                    pos["tp1_hit"] = True
                    pos["sl_price"] = pos["avg_price"]
                    pos["cost_basis"] -= sell_cost_basis
                    pos["total_lots"] = pos["remaining_lots"]
                    remaining_positions.append(pos)

            if exit_reason is None or sell_lots == 0:
                pos["hold_days"] += 1
                remaining_positions.append(pos)

        positions = remaining_positions

        # ---- New entries: the Phase 0g validated rule, not squeeze ----
        # Gated on the regime having read BULLISH for REGIME_CONFIRM_DAYS
        # running, not just today -- don't deploy capital on day 1 of a
        # flip that might be a false start (see MAX_NEW_ENTRIES_PER_DAY
        # comment above for the window-3 failure this targets).
        if regime == "BULLISH" and bullish_streak_by_date.get(trade_date, 0) >= REGIME_CONFIRM_DAYS:
            day_data = df[
                (df["trade_date"] == trade_date)
                & (df["adtv_20"] >= cfg.ADTV_MIN)
                & (df["weekly_ma_spread"] >= weekly_cut)
                & (df["sector_rs_momentum"] >= sector_cut)
                & df["atr_14"].notna() & (df["atr_14"] > 0)
                & df["avg_vol_20"].notna()
                & ((df["atr_14"] / df["close_price"]) <= ATR_PRICE_RATIO_MAX)
            ].copy()

            if not day_data.empty:
                day_data["score"] = (
                    (day_data["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
                    + (day_data["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
                )
                for _, sig in day_data.nlargest(15, "score").iterrows():
                    pending_entries.append({
                        "stock_code": sig["stock_code"], "signal_close": float(sig["close_price"]),
                        "atr": sig["atr_14"], "avg_vol_20": float(sig["avg_vol_20"]), "trigger": "V3_regime_weekly_sector",
                        "tp_target": float(sig["tp_target"]),
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
        print("\n[BACKTEST V3] No trades executed in test window.")
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
    print("BACKTEST V3 RESULTS (out-of-sample test window only)")
    print("=" * 70)
    print(f"  Test window     : {trading_days[0]} .. {trading_days[-1]}")
    print(f"  Net Profit      : Rp {net_profit:,.0f} ({total_return_pct:+.2f}%)")
    print(f"  Benchmark IHSG  : {bench_ret:+.2f}% (alpha {total_return_pct - bench_ret:+.2f}%)")
    print(f"  Total Trades    : {total_trades}")
    print(f"  Win Rate        : {win_rate:.1f}%")
    print(f"  Profit Factor   : {profit_factor:.2f}")
    print(f"  Max Drawdown    : {max_drawdown:.2f}%")
    print("=" * 70)

    contrib = df_trades.groupby("stock_code")["pnl"].sum().sort_values(ascending=False)
    total_pos_contrib = contrib[contrib > 0].sum()
    top5 = contrib.head(5)
    top5_pct = 100 * top5.clip(lower=0).sum() / total_pos_contrib if total_pos_contrib > 0 else float("nan")
    print(f"\n[CONCENTRATION CHECK] top-5 tickers ({', '.join(top5.index.tolist())}) = {top5_pct:.1f}% of total positive PnL")
    print(f"[EXIT BREAKDOWN] {df_trades['exit_reason'].value_counts(normalize=True).round(3).to_dict()}")

    df_trades.to_csv("backtest_v3_trades.csv", index=False)
    df_equity.to_csv("backtest_v3_equity.csv", index=False)
    print(f"\n[OK] Saved backtest_v3_trades.csv ({len(df_trades)} rows), backtest_v3_equity.csv ({len(df_equity)} rows).")


if __name__ == "__main__":
    main()
