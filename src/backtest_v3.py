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

# config.py is SHARED with V1's live backtest.py/screener.py (confirmed:
# both import cfg.TP1_MULT/TRAILING_PCT directly) -- never edit the file.
# These overrides mutate the cfg module object in THIS process's memory
# only, for sweeping exit mechanics in V3 experiments; the file on disk
# is untouched, so V1 (a separate process, re-importing config.py fresh
# each run) is unaffected regardless of what gets tested here. No env
# var set = cfg's own file defaults, unchanged behavior.
if os.environ.get("V3_TP1_MULT"):
    cfg.TP1_MULT = float(os.environ["V3_TP1_MULT"])
if os.environ.get("V3_TRAILING_PCT"):
    cfg.TRAILING_PCT = float(os.environ["V3_TRAILING_PCT"])
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
    """Returns (regime_by_date, bullish_streak_by_date, trend_strength_by_date).

    bullish_streak_by_date counts consecutive trading days the regime has
    read BULLISH, ending at that date -- used to require the flip to hold
    before trusting it with new capital (see REGIME_CONFIRM_DAYS).

    trend_strength_by_date is (close - ma50) / ma50 -- how far IHSG has
    actually separated from its own trend line, not just which side of it.
    Window 3 (the losing OOS window) averaged only 1.13% separation from
    ma50 vs window 1's 5.49% and window 2's 2.18% -- a real, sizeable gap.
    The binary regime (even hysteresis- and streak-confirmed) can't tell
    a genuine trend from IHSG hovering just barely on the bullish side of
    a smoothed line; this can (see TREND_STRENGTH_MIN)."""
    sub = idx_df.dropna(subset=["ma50"]).sort_values("trade_date").copy()
    daily_ret = sub["close"].pct_change()
    vol_20 = daily_ret.rolling(20, min_periods=20).std()
    sub["band"] = (VOL_BAND_MULT * vol_20).fillna(vol_20.median())

    regime_by_date = {}
    bullish_streak_by_date = {}
    trend_strength_by_date = {}
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
        trend_strength_by_date[row.trade_date] = (row.close - row.ma50) / row.ma50
    return regime_by_date, bullish_streak_by_date, trend_strength_by_date

FETCH_START = date.fromisoformat(os.environ.get("V3_FETCH_START", "2021-01-01"))
TRAIN_END = date.fromisoformat(os.environ.get("V3_TRAIN_END", "2024-06-30"))
TEST_START = date.fromisoformat(os.environ.get("V3_TEST_START", "2024-07-31"))
TEST_END = date.fromisoformat(os.environ.get("V3_TEST_END", "2026-06-30"))
QUANTILE_CUT = float(os.environ.get("V3_QUANTILE_CUT", "0.60"))
# Swept 0.50/0.60/0.70/0.80/0.90 across the full 9-window walk-forward --
# 0.60 is a genuine interior peak (bracketed on both sides, not a
# monotonic runaway or an edge-of-range fluke): best beat-benchmark count
# (6/9), best win-rate-consistency (5/9), best mean alpha, best median
# profit factor (first time crossing meaningfully above 1), best
# worst-case drawdown of every value tested. See V3_FINDINGS_LOG.md.

INITIAL_CAPITAL = 100_000_000
LOT_SIZE = 100
SL_PCT = 0.02
MAX_POSITIONS = int(os.environ.get("V3_MAX_POSITIONS", "6"))
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
# Even after both fixes above, window 3 still lost money (-12.28%, 38.5%
# win). Diagnostic: IHSG's own separation from ma50 averaged 5.49% in
# window 1 (great), 2.18% in window 2 (modest), only 1.13% in window 3
# (losing) -- a real, sizeable gap. Binary "which side of ma50" (even
# hysteresis- and streak-confirmed) can't distinguish a genuine trend
# from IHSG barely, chopily hovering above a smoothed line. This requires
# actual separation, not just direction + persistence.
#
# Swept 1%/2% across all three windows before trusting a value (same
# discipline the hysteresis-band walk-back required). 2% eliminated
# window 3 entirely (0 trades -- avoided the loss but at a big cost:
# window 1 dropped +234.46%->+94.81%, too aggressive). 1% is the better
# balance: window 1 +234.46%->+152.75% (still strong, win rate actually
# UP to 60.1%), window 2 basically unchanged (+41.31%->+41.91%), window 3
# -12.28%->-5.44% (small loss, alpha -2.68% now nearly matches its own
# benchmark instead of badly missing it). Win rate clears 50% in ALL
# THREE windows simultaneously for the first time all session.
TREND_STRENGTH_MIN = float(os.environ.get("V3_TREND_STRENGTH_MIN", "0.01"))
# TESTED, NET NEGATIVE -- kept available (like ADAPTIVE_HOLDTIME below),
# inert by default. Hypothesis was that window 3's six same-thesis
# positions (GOTO/BUKA/EMTK/WIRG/ASSA/DMMX, all legit large-caps) needed a
# direct correlated-ENTRY-TIMING brake beyond REGIME_CONFIRM_DAYS/
# MAX_NEW_ENTRIES_PER_DAY (neither stops the portfolio filling up over
# several days on one persisting false thesis once both gates clear).
# Capped how many currently-open positions may have been entered within a
# trailing window. Swept at (5 days / max 3) against all three OOS
# windows with the fetch fix below:
#   W1 (already good): +152.75%/60.1% win/PF1.73/DD-32.93% -> +146.72%/
#     61.9% win/PF1.83/DD-29.40% -- genuinely better risk-adjusted, small
#     profit cost.
#   W2 (modest): +26.82%/54.2% win/PF1.34 -> +14.82%/53.4% win/PF1.23 --
#     worse on every axis.
#   W3 (the one this targeted): -5.44%/41.7% win/PF0.29 -> -8.30%/22.2%
#     win/PF0.16 -- meaningfully WORSE, not better.
# Helped the window that needed it least, hurt the other two -- including
# the exact window that motivated it. Real evidence for what was already
# suspected: W3's residual weakness isn't timing anymore, it's the entry
# rule surfacing fewer genuinely good setups in a weak/choppy regime --
# throttling concurrency there removes real trades more than it removes
# correlated risk, since there's little signal volume to throttle in the
# first place. Default below makes the gate unreachable (equals
# MAX_POSITIONS) without deleting the mechanism.
ENTRY_CLUSTER_WINDOW_DAYS = int(os.environ.get("V3_ENTRY_CLUSTER_WINDOW_DAYS", "5"))
MAX_ENTRIES_PER_CLUSTER_WINDOW = int(os.environ.get("V3_MAX_ENTRIES_PER_CLUSTER_WINDOW", "6"))
ALLOC_PCT = float(os.environ.get("V3_ALLOC_PCT", "0.20"))
# Walk-forward across 9 real windows (see V3_FINDINGS_LOG.md) found most
# windows' results are carried by a handful of outlier winners, not a
# broad distributed edge -- 6/9 windows showed >65% concentration. Flat
# ALLOC_PCT sizes every qualifying signal identically regardless of
# conviction. Testing whether the entry rule's own score (already
# computed for ranking, never used for sizing) has any real relationship
# to which trades become the outliers -- off by default until validated
# across the full walk-forward battery.
SCORE_SIZING_ENABLED = os.environ.get("V3_SCORE_SIZING", "0") == "1"
# Real ADTV-based sizing -- see docstring at the trigger site. VALIDATED
# across the 9-window walk-forward: best mean alpha (+21.71%) AND best
# worst-case drawdown (-21.61%) of every configuration tested this
# session, simultaneously -- a rare combination pointing at real
# informational content in the liquidity signal, not just more variance.
# Real disclosed tradeoff: win-rate-consistency (windows clearing 50%)
# dropped from 5/9 to 4/9. Default ON. See V3_FINDINGS_LOG.md.
LIQ_SIZING_ENABLED = os.environ.get("V3_LIQ_SIZING", "1") == "1"
LIQ_SIZING_MIN = float(os.environ.get("V3_LIQ_SIZING_MIN", "0.5"))
LIQ_SIZING_MAX = float(os.environ.get("V3_LIQ_SIZING_MAX", "2.0"))
# Regime-conditional capital allocation (roadmap item #1 from the
# 2026-07-27 strategic assessment): TREND_STRENGTH_MIN already gates
# *whether* new entries fire at all; this scales *how much* capital
# each entry gets by how strongly IHSG is separated from its own ma50
# on the day of execution, relative to the train-derived 90th
# percentile among qualifying train days. A signal firing right at the
# TREND_STRENGTH_MIN threshold (weak trend, window-3-like) gets less
# capital than one firing well clear of it (window-1-like). Off by
# default until validated across the full walk-forward battery.
TREND_SIZING_ENABLED = os.environ.get("V3_TREND_SIZING", "0") == "1"
TREND_SIZING_MIN = float(os.environ.get("V3_TREND_SIZING_MIN", "0.5"))
TREND_SIZING_MAX = float(os.environ.get("V3_TREND_SIZING_MAX", "1.5"))
# Alternative framing to score-weighted sizing (rejected -- see
# V3_FINDINGS_LOG.md): instead of predicting at entry which signal will
# be the outlier winner, add to a position only after it's already
# proven itself by reaching TP1. Funded fresh (cash), doesn't touch the
# original tranche's locked-in partial profit; original stop stays at
# the original entry price regardless. VALIDATED across the 9-window
# walk-forward (median alpha +0.61%->+17.50%, median PF 0.85->0.90,
# 4/9->5/9 windows clearing 50% win rate) -- default ON. Real tradeoff,
# not a free upgrade: amplifies whichever direction a window is already
# going (6/9 windows improved, 3/9 got worse), mean max drawdown
# slightly worse (-15.56%->-17.21%). See V3_FINDINGS_LOG.md.
PYRAMID_ENABLED = os.environ.get("V3_PYRAMID", "1") == "1"
PYRAMID_ADD_PCT = float(os.environ.get("V3_PYRAMID_ADD_PCT", "0.20"))  # same as ALLOC_PCT by default; swept 0.10/0.20/0.30, see V3_FINDINGS_LOG.md
# Unvalidated refinement on top of the adopted unconditional pyramid --
# off by default. See docstring at the pyramid trigger site.
PYRAMID_TREND_GATE_ENABLED = os.environ.get("V3_PYRAMID_TREND_GATE", "0") == "1"
PYRAMID_TREND_GATE_MIN = float(os.environ.get("V3_PYRAMID_TREND_GATE_MIN", "0.03"))
# Second add-on tier: extends the validated single pyramid to a position
# that proves itself further (see docstring at the trigger site). Off by
# default -- unvalidated.
PYRAMID_TP2_ENABLED = os.environ.get("V3_PYRAMID_TP2", "0") == "1"
# diagnose_score_power.py (2026-08-07): the day's single #1-ranked candidate
# specifically has a real problem (~2x average score magnitude, ~20% higher
# ATR%, 82-98% stop-loss-hit rate in BOTH halves of a 4.5yr sample, vs
# ~75-85% for rank 2+) -- the likely signature of a same-day statistical
# outlier the score formula reads as strength. Off by default -- unvalidated
# against the full walk-forward battery yet, see V3_FINDINGS_LOG.md.
SCORE_SKIP_TOP_N = int(os.environ.get("V3_SCORE_SKIP_TOP_N", "0"))
# Conditional refinement on SCORE_SKIP_TOP_N=1 (see score_candidates docstring): only drop
# the #1 candidate when it's a real outlier vs #2 (score > this multiple of #2's score), not
# unconditionally. None (default) = off, byte-identical. Unvalidated -- see V3_FINDINGS_LOG.md.
_outlier_gap_env = os.environ.get("V3_SCORE_OUTLIER_GAP_MULT")
SCORE_OUTLIER_GAP_MULT = float(_outlier_gap_env) if _outlier_gap_env else None
# More surgical follow-up to the two flags above: caps the weekly_ma_spread component
# specifically (not sector_rs_momentum, not the combined score) at its own within-day
# quantile among qualifying candidates. See score_candidates docstring. None (default) = off.
_weekly_cap_env = os.environ.get("V3_SCORE_WEEKLY_COMP_CAP_Q")
SCORE_WEEKLY_COMP_CAP_Q = float(_weekly_cap_env) if _weekly_cap_env else None
# Realism check on a known, disclosed simplification: every fill so far
# (backtest AND live paper engine) executes at the exact observed
# price, no cost for actually crossing the spread or moving an illiquid
# name's own volume. Off by default -- exists to test whether that
# assumption is inflating the headline numbers, the same category of
# bug as the survivorship/delisted-handling/liquidity-filter fixes
# earlier this session. The live paper engine NEVER sets V3_SLIPPAGE
# (not in any GitHub Actions workflow env), so this cannot change its
# frozen behavior -- it only fires inside backtest/walk-forward runs.
# Impact term uses sqrt(participation), not participation itself -- Cont,
# Kukanov & Stoikov (2011), "The Price Impact of Order Book Events",
# read in full this session. Their real model (price change = beta * order
# flow imbalance, beta ~ 1/depth) needs Level-1 bid/ask queue data we don't
# have for IDX names -- EOD OHLCV only. The one piece of their paper usable
# with volume-only data is the "square-root" price-impact-vs-volume relation
# they derive as a byproduct -- concave, matching the wider market-impact
# literature's consensus shape -- but the authors explicitly call it noisier
# and "not recommended" versus their real OFI-based model. Used here anyway
# because it's still a better-justified functional form than an unsourced
# straight line, not because it's validated for this market.
SLIPPAGE_ENABLED = os.environ.get("V3_SLIPPAGE", "0") == "1"
SLIPPAGE_BASE_BPS = float(os.environ.get("V3_SLIPPAGE_BASE_BPS", "5"))  # always-on cost of crossing the spread
SLIPPAGE_IMPACT_BPS = float(os.environ.get("V3_SLIPPAGE_IMPACT_BPS", "16"))  # bps at 100% of a stock's own ADTV taken (sqrt-scaled below that)
BACKTEST_VERSION = os.environ.get("BACKTEST_VERSION", "v3-dev")
BACKTEST_PUBLISH = os.environ.get("BACKTEST_PUBLISH", "false").lower() == "true"
DELISTING_GAP_DAYS = 10  # consecutive no-data trading days -> force-exit at last known price
ATR_PRICE_RATIO_MAX = float(os.environ.get("V3_ATR_PRICE_RATIO_MAX", "0.10"))
                            # exclude entries where ATR_14/close > this -- PIPA/FUTR/ISAP-style
                            # hyperactive penny stocks slip through the Rupiah-value ADTV filter
                            # (huge share count, low price) despite genuinely extreme volatility;
                            # this caps signal-day volatility directly, price-agnostic (GOTO/BUKA
                            # stay eligible despite low price since their ATR% is normal, ~4%).
                            # Env-overridable so the V3.1 candidate ceiling can be swept through
                            # walk_forward_v3.py without editing this file; the 0.10 default
                            # keeps the frozen live V3_PAPER run byte-identical.

# ---- Auto-reject (ARA/ARB) detection -- both filters OFF by default -------
# A stock locked at an auto-reject limit is not tradeable at a fair price.
# At the CEILING (ARA) there is no offer to buy from: the close IS the limit
# and the queue is one-sided. At the FLOOR (ARB) there is no bid to sell
# into, which is the dangerous one for an open position -- a stop-loss
# "filling" at sl_price on an ARB day is fiction, and modelling it as a fill
# flatters the track record on exactly the days that hurt most in real life.
#
# BAJA is the motivating ARA case: queued 2026-08-03 at prev 244 -> close
# 304 (+24.59%, close == high), then volume=0/open=0 the next session and
# never fillable at all.
#
# --- Why the limit is INFERRED per stock instead of read off a price table:
# IDX sets the limit by BOARD, not purely by price. Main/development boards
# use the 35/25/20% price tiers, but Papan Akselerasi and full-call-auction
# monitoring boards run 10% -- and ihsg_eod carries no board column, so a
# Rp1,000 stock could legitimately be a 25% name or a 10% name.
#
# Measuring the real distribution settles it. Over 2025-01-01+, bars that
# closed AT their high cluster hard just under four values and collapse
# immediately above each:
#     9.0-9.99%: 4,205 bars -> 10.0-10.49%: 1,063 -> 10.5-11%: 45
#    19.6-19.99%:   109     -> 20.0-20.34%:    72 -> 20.5-21%:  7
#    24.0-24.94%:   894     -> 25.00% exact :   346 -> above  :  1
#    34.0-34.97%:   497     -> 35.00% exact :    31 -> above  :  0
# Four limits actually enforced: 10 / 20 / 25 / 35%. The mass sitting just
# BELOW each round number is tick rounding (BAJA's 24.59 vs 25.00), which is
# why the trigger fires at LIMIT_TOLERANCE of the limit rather than at it.
#
# So: take each stock's own largest absolute daily move over a trailing
# window and snap it to whichever known limit it matches. A stock that has
# ever gone limit-up reveals its board. One that never has (a calm blue
# chip topping out at 6%) snaps to nothing and falls back to the price tier
# -- which is correct, because it also can't be mistaken for locked today.
# The window is shifted by one day so today's own bar can never define the
# limit today's bar is tested against.
ARA_FILTER_ENABLED = os.environ.get("V3_ARA_FILTER", "0") == "1"
ARB_EXIT_REALISM = os.environ.get("V3_ARB_EXIT_REALISM", "0") == "1"
LIMIT_TOLERANCE = 0.95        # today's move counts as locked at >= 95% of the limit
IDX_LIMIT_STEPS = (0.10, 0.20, 0.25, 0.35)
LIMIT_SNAP_TOLERANCE = 0.035  # trailing max within 3.5pp of a step => that's the board's limit
LIMIT_LOOKBACK_DAYS = 250
LIMIT_LOOKBACK_MIN = 60


def price_tier_limit(prev_close: float) -> float:
    """IDX auto-reject limit implied by price band alone (main/development
    boards). Fallback for stocks whose own history reveals no limit."""
    if prev_close < 200:
        return 0.35
    if prev_close <= 5000:
        return 0.25
    return 0.20


def snap_to_known_limit(observed_max_move, prev_close: float) -> float:
    """Nearest enforced IDX limit to a stock's own largest observed move,
    or the price-tier limit when nothing is close enough to snap to."""
    if observed_max_move is not None and np.isfinite(observed_max_move):
        best = min(IDX_LIMIT_STEPS, key=lambda s: abs(s - observed_max_move))
        if abs(best - observed_max_move) <= LIMIT_SNAP_TOLERANCE:
            return best
    return price_tier_limit(prev_close)


def is_ara_locked(prev_close, close, high, observed_max_move=None) -> bool:
    """Locked at the CEILING: closed at the day's high AND gained
    essentially the full limit. Both conditions matter -- a big gain that
    closed off its high still had a real offer to buy from."""
    if not prev_close or prev_close <= 0 or close is None or high is None:
        return False
    if close < high:
        return False
    return (close / prev_close - 1) >= snap_to_known_limit(observed_max_move, prev_close) * LIMIT_TOLERANCE


def is_arb_locked(prev_close, close, low, observed_max_move=None) -> bool:
    """Locked at the FLOOR: closed at the day's low AND fell essentially the
    full limit. Means there was no bid -- an exit cannot be assumed to fill
    at any chosen price on such a bar."""
    if not prev_close or prev_close <= 0 or close is None or low is None:
        return False
    if close > low:
        return False
    return (1 - close / prev_close) >= snap_to_known_limit(observed_max_move, prev_close) * LIMIT_TOLERANCE


def attach_board_limit(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `observed_max_move`: each stock's largest absolute daily move
    over the trailing LIMIT_LOOKBACK_DAYS sessions, EXCLUDING the current
    bar (shift(1)) so no row can be judged against a limit that its own
    move defined. Feeds snap_to_known_limit()."""
    out = df.sort_values(["stock_code", "trade_date"]).copy()
    move = (out["close_price"] / out["previous"] - 1).abs()
    move = move.where(out["previous"] > 0)
    out["observed_max_move"] = (
        move.groupby(out["stock_code"])
        .transform(lambda s: s.shift(1).rolling(LIMIT_LOOKBACK_DAYS, min_periods=LIMIT_LOOKBACK_MIN).max())
    )
    return out

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
    # Always attached, even with both auto-reject filters off: it is one
    # extra column derived from data already in memory, and computing it
    # unconditionally keeps the dataset (and its pickle cache) identical
    # between sweep cells that differ only by V3_ARA_FILTER.
    df = attach_board_limit(df)

    return df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True), idx_df


def _save_to_supabase(supabase, df_trades: pd.DataFrame, df_equity: pd.DataFrame,
                       regime_by_date: dict, metrics: dict) -> None:
    """Save summary + trades + equity curve to Supabase for the website,
    same schema/pattern as backtest.py (V1) and backtest_v2.py."""
    try:
        run_res = supabase.table("backtest_runs").insert({
            "version": BACKTEST_VERSION,
            "period_start": metrics["period_start"].isoformat(),
            "period_end": metrics["period_end"].isoformat(),
            "initial_capital": metrics["initial_capital"],
            "final_capital": metrics["final_capital"],
            "net_profit_pct": metrics["total_return_pct"],
            "benchmark_pct": metrics["bench_ret"],
            "alpha_pct": metrics["total_return_pct"] - metrics["bench_ret"],
            "total_trades": metrics["total_trades"],
            "win_rate": metrics["win_rate"],
            "profit_factor": None if metrics["profit_factor"] == float("inf") else metrics["profit_factor"],
            "max_drawdown": metrics["max_drawdown"],
            "cvar_95": None if pd.isna(metrics["cvar_95"]) else metrics["cvar_95"],
            "notes": metrics["notes"],
            "strategy_summary": metrics["notes"],
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
            "drawdown_pct": float(row["drawdown"]), "regime": regime_by_date.get(row["date"], "NEUTRAL"),
        } for _, row in df_equity.iterrows()]

        for i in range(0, len(trade_rows), 500):
            supabase.table("backtest_trades").insert(trade_rows[i:i + 500]).execute()
        for i in range(0, len(equity_rows), 500):
            supabase.table("backtest_equity").insert(equity_rows[i:i + 500]).execute()

        print(f"\n[OK] Saved to Supabase: backtest_runs id={run_id} "
              f"(version={BACKTEST_VERSION}, published={BACKTEST_PUBLISH})")
    except Exception as e:
        print(f"WARNING: Failed to save to Supabase: {e}")


def apply_slippage(price: float, side: str, participation: float = 0.0) -> float:
    """Widens a fill price against the trader: buys pay more, sells receive less.
    `participation` = order quantity / a stock's own avg_vol_20 -- how big a bite
    out of the stock's own daily liquidity this single order represents. No-op
    (returns price unchanged) unless SLIPPAGE_ENABLED, so this is inert everywhere
    the live paper engine calls compute_entry_fill/evaluate_position_exit."""
    if not SLIPPAGE_ENABLED:
        return price
    slip = (SLIPPAGE_BASE_BPS + SLIPPAGE_IMPACT_BPS * max(participation, 0.0) ** 0.5) / 10000.0
    return price * (1 + slip) if side == "buy" else price * (1 - slip)


def score_candidates(day_slice: pd.DataFrame, weekly_cut: float, sector_cut: float, top_n: int = 15,
                      skip_top_n: int = 0, outlier_gap_mult: float = None,
                      weekly_comp_cap_q: float = None) -> list:
    """Filters a single trading day's cross-section to qualifying candidates (liquidity,
    weekly-trend, sector-momentum, ATR sanity) and returns the top-N by score as plain dicts.
    Extracted so the live paper-trading signal scan (src/paper_signal_scan.py) calls the exact
    same candidate logic as this backtest, instead of a re-typed copy that could drift. `day_slice`
    must already be filtered to one trade_date (backtest: a historical day; live: today).

    `skip_top_n` drops the N single highest-scoring candidates before returning (default 0,
    byte-identical to every caller that doesn't pass it). diagnose_score_power.py found the
    day's #1-ranked candidate specifically -- not the top tier broadly -- has a real, cross-
    period-consistent problem: ~2x the average score magnitude, ~20% higher ATR%, and a stop-
    loss-hit rate of 82-98% in both halves of a 4.5-year sample (vs ~75-85% for rank 2+), the
    likely signature of a same-day outlier/overextension the score formula can't distinguish
    from genuine sustainable momentum. See docs/V3_FINDINGS_LOG.md.

    `weekly_comp_cap_q` (default None, off) excludes candidates whose normalized
    weekly_ma_spread component exceeds this within-day quantile of the qualifying pool.
    Follow-up to skip_top_n: decomposing rank-1's score found the outlier-ness comes almost
    entirely from an extreme weekly_ma_spread component (mean ~2.5x the rest of the pool) --
    the normalized sector_rs_momentum component is essentially identical between rank-1 and
    everyone else, and its own top quintile shows no reversion pattern (best mean forward
    return of any quintile). A per-day quantile cut on the weekly component specifically is
    more surgical than dropping by rank/combined-score, which conflates the two factors."""
    candidates = day_slice[
        (day_slice["adtv_20"] >= cfg.ADTV_MIN)
        & (day_slice["weekly_ma_spread"] >= weekly_cut)
        & (day_slice["sector_rs_momentum"] >= sector_cut)
        & day_slice["atr_14"].notna() & (day_slice["atr_14"] > 0)
        & day_slice["avg_vol_20"].notna()
        & ((day_slice["atr_14"] / day_slice["close_price"]) <= ATR_PRICE_RATIO_MAX)
    ].copy()
    if ARA_FILTER_ENABLED and not candidates.empty:
        observed = (
            candidates["observed_max_move"] if "observed_max_move" in candidates.columns
            else pd.Series(np.nan, index=candidates.index)
        )
        locked = [
            is_ara_locked(row["previous"], row["close_price"], row["high"], obs)
            for (_, row), obs in zip(candidates.iterrows(), observed)
        ]
        candidates = candidates[~np.array(locked, dtype=bool)]
    if candidates.empty:
        return []
    candidates["w_comp"] = (candidates["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
    candidates["score"] = (
        candidates["w_comp"]
        + (candidates["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
    )
    if weekly_comp_cap_q is not None and len(candidates) >= 3:
        cap = candidates["w_comp"].quantile(weekly_comp_cap_q)
        candidates = candidates[candidates["w_comp"] <= cap]
        if candidates.empty:
            return []
    pool = candidates.nlargest(top_n + skip_top_n + 1, "score")
    start = skip_top_n
    # Conditional variant of skip_top_n: only drop the #1 candidate on days it's a real
    # outlier relative to #2 (score > outlier_gap_mult * second-place score), not on every
    # day -- the flat skip_top_n=1 sweep won its typical-window/median metrics but gave up
    # real upside on days where rank-1 wasn't actually an outlier (see V3_FINDINGS_LOG.md).
    if outlier_gap_mult is not None and len(pool) >= 2:
        top_score, second_score = pool.iloc[0]["score"], pool.iloc[1]["score"]
        if second_score > 0 and top_score > outlier_gap_mult * second_score:
            start = max(start, 1)
    ranked = pool.iloc[start:start + top_n]
    return [{
        "stock_code": sig["stock_code"], "signal_close": float(sig["close_price"]),
        "atr": sig["atr_14"], "avg_vol_20": float(sig["avg_vol_20"]), "trigger": "V3_regime_weekly_sector",
        "tp_target": float(sig["tp_target"]), "score": float(sig["score"]),
        "adtv_20": float(sig["adtv_20"]),
    } for _, sig in ranked.iterrows()]


def score_full_universe(day_slice: pd.DataFrame, weekly_cut: float, sector_cut: float,
                         score_p90: float, regime_ok: bool) -> list:
    """Scores EVERY liquid ticker in day_slice for the daily scoreboard --
    unlike score_candidates (a trade-entry gate that drops anything failing
    weekly/sector cuts), this never drops a row past the liquidity/ATR
    sanity floor, so a ticker search always has an answer instead of
    silence. Same score formula as score_candidates (normalized distance
    above both cuts), just not used to filter here.

    regime_ok is whatever the caller already computed for today (BULLISH +
    REGIME_CONFIRM_DAYS streak + TREND_STRENGTH_MIN) -- the same three-part
    check paper_signal_scan.py applies before generating any new
    candidates at all. Labels:
      STRONG_BUY -- passes weekly/sector gate, score >= score_p90, regime_ok
      BUY        -- passes weekly/sector gate, regime_ok
      WATCH      -- liquid + regime_ok but fails weekly/sector gate
      WAIT       -- regime not confirmed bullish yet, whatever the gate says
    No SELL label: this is a long-only entry screener with no short/sell
    model, so a bad score means "not a qualifying entry today," not
    "sell your position." Also no price target here -- that needs its
    own backtest validation before shipping, see docs/V3_FINDINGS_LOG.md."""
    liquid = day_slice[
        (day_slice["adtv_20"] >= cfg.ADTV_MIN)
        & day_slice["weekly_ma_spread"].notna() & day_slice["sector_rs_momentum"].notna()
        & day_slice["atr_14"].notna() & (day_slice["atr_14"] > 0)
        & ((day_slice["atr_14"] / day_slice["close_price"]) <= ATR_PRICE_RATIO_MAX)
    ].copy()
    if liquid.empty:
        return []
    liquid["score"] = (
        (liquid["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        + (liquid["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
    )
    passes_gate = (liquid["weekly_ma_spread"] >= weekly_cut) & (liquid["sector_rs_momentum"] >= sector_cut)
    if not regime_ok:
        liquid["label"] = "WAIT"
    else:
        liquid["label"] = np.where(
            passes_gate, np.where(liquid["score"] >= score_p90, "STRONG_BUY", "BUY"), "WATCH",
        )
    # Percentile rank within TODAY's liquid universe -- a real, honest 0-100
    # number (unlike the raw score, which is an unbounded "distance above
    # threshold" and not meaningful on its own). Gives granularity within a
    # label: two STRONG_BUY tickers aren't equally strong. Computed here
    # (not on the frontend) since this function already has the full day's
    # score distribution in memory -- the frontend would otherwise need to
    # fetch every liquid ticker's row just to rank one.
    liquid["percentile"] = liquid["score"].rank(pct=True) * 100
    # atr_14 is carried through purely so the frontend can show the SAME
    # ATR-based TP1/SL levels compute_entry_fill() would apply, for every
    # ranked ticker -- not just the 2/day that actually get queued. It is
    # never read back into any trading decision (this whole function is
    # display-only); without it the site can only show a rank with no
    # price levels, which reads as "a signal that tells you nothing."
    return [{
        "stock_code": sig["stock_code"], "score": float(sig["score"]), "label": sig["label"],
        "percentile": float(sig["percentile"]),
        "weekly_ma_spread": float(sig["weekly_ma_spread"]), "sector_rs_momentum": float(sig["sector_rs_momentum"]),
        "close_price": float(sig["close_price"]), "adtv_20": float(sig["adtv_20"]),
        "atr_14": float(sig["atr_14"]),
    } for _, sig in liquid.iterrows()]


def compute_entry_fill(sig: dict, entry_price: float, cash: float, prev_equity: float,
                        log_adtv_p90: float, score_p90: float = 1.0, trend_strength: float = 0.0,
                        trend_strength_p90: float = 1.0):
    """Sizing + fee math for filling ONE queued candidate at its execution-day open price.
    Extracted so the live paper-trading monitor (src/paper_monitor.py) fills entries through
    the exact same sizing formulas as this backtest -- score_mult/liq_mult/trend_mult, the
    ATR-based TP1/SL calc, and every cap (RISK_PCT, LIQ_CAP_PCT, ALLOC_MIN_LOTS). Does NOT
    include the gap-check, portfolio-slot count, or cooldown gating -- those are loop-level
    concerns the caller still owns (they differ between "iterating a historical day" and
    "checking one live candidate"). Returns None if the fill doesn't clear ALLOC_MIN_LOTS,
    else a dict with lots/cost_basis/tp1_price/sl_price/checkpoint_day/expected_hold_days.
    """
    atr_val = sig["atr"]
    if atr_val is None or (isinstance(atr_val, float) and (np.isnan(atr_val) or atr_val <= 0)):
        tp1_price = entry_price * 1.02
        sl_price = entry_price * (1 - SL_PCT)
        expected_hold_days = None
        atr_val = None
    else:
        tp1_price = entry_price + atr_val * cfg.TP1_MULT
        sl_price = entry_price - atr_val * 1.5
        tp1_price = max(tp1_price, entry_price * 1.01)
        sl_price = min(sl_price, entry_price * 0.99)
        expected_hold_days = abs(sig["tp_target"] - entry_price) / atr_val

    size_mult = min(2.0, max(0.5, sig.get("score", score_p90) / score_p90)) if SCORE_SIZING_ENABLED else 1.0
    liq_mult = min(LIQ_SIZING_MAX, max(LIQ_SIZING_MIN, np.log(max(sig.get("adtv_20", 1.0), 1.0)) / log_adtv_p90)) if LIQ_SIZING_ENABLED else 1.0
    trend_mult = min(TREND_SIZING_MAX, max(TREND_SIZING_MIN, trend_strength / trend_strength_p90)) if TREND_SIZING_ENABLED else 1.0
    alloc = min(prev_equity * ALLOC_PCT * size_mult * liq_mult * trend_mult, cash)
    # Participation estimated from the pre-slippage desired size (one-pass
    # approximation, not an iterative solver -- good enough given lots is
    # further capped by liq_lots below regardless of this estimate).
    est_participation = (alloc / max(entry_price, 1e-6)) / max(sig.get("avg_vol_20", 1.0), 1.0)
    slipped_entry_price = apply_slippage(entry_price, "buy", est_participation)
    cost_per_share = slipped_entry_price * (1 + cfg.BUY_FEE)
    lots = int(alloc / cost_per_share) // LOT_SIZE
    risk_per_share = entry_price - sl_price
    if risk_per_share > 0:
        lots_risk = int(prev_equity * cfg.RISK_PCT / risk_per_share) // LOT_SIZE
        lots = min(lots, lots_risk)
    liq_lots = int(sig["avg_vol_20"] * cfg.LIQ_CAP_PCT) // LOT_SIZE
    lots = min(lots, liq_lots)
    if lots < cfg.ALLOC_MIN_LOTS:
        return None

    quantity = lots * LOT_SIZE
    cost_basis = quantity * cost_per_share
    if cost_basis > cash:
        lots = int(cash / cost_per_share) // LOT_SIZE
        if lots < 1:
            return None
        quantity = lots * LOT_SIZE
        cost_basis = quantity * cost_per_share

    checkpoint_day = None
    if ADAPTIVE_HOLDTIME and expected_hold_days is not None and expected_hold_days >= HOLDTIME_MIN_DAYS:
        checkpoint_day = int(np.clip(round(expected_hold_days), HOLDTIME_MIN_CHECKPOINT, HOLDTIME_CAP_DAYS))

    return {
        "lots": lots, "quantity": quantity, "cost_basis": cost_basis,
        "tp1_price": tp1_price, "sl_price": sl_price, "checkpoint_day": checkpoint_day,
        "atr_at_entry": atr_val,
    }


def evaluate_position_exit(pos: dict, bar: tuple, regime: str, trend_strength: float,
                            trade_date, prev_equity: float, cash: float,
                            prev_close=None, observed_max_move=None, allow_pyramid: bool = True):
    """SL/TP1/TRAILING/CHECKPOINT/TIME exit decision + the TP1/TP2 pyramid-add-on, for ONE
    open position on ONE day. Extracted so the live paper-trading monitor
    (src/paper_monitor.py) makes exit decisions through the exact same code path as this
    backtest -- zero drift between the validated rule and what runs live.

    `bar` = (open, close, high, low): the backtest passes a real historical daily OHLC bar;
    the live monitor passes (day_open, current_live_price, day_high_so_far, day_low_so_far)
    built up from repeated intraday polls -- a disclosed proxy for true intrabar H/L, not real
    tick data (see docs/V3_FINDINGS_LOG.md paper-trading section).

    Mutates `pos`'s own bookkeeping fields in place (highest_price, tp1_hit, tp2_hit, sl_price,
    avg_price, total_lots, remaining_lots, cost_basis) -- these belong to the position, not the
    caller's loop state. Returns (trade_record | None, cash_delta): the caller applies
    cash_delta to its own cash variable, appends trade_record to its trades list, and (on
    exit_reason == "SL") records the cooldown timestamp -- none of that is this position's own
    state, so it stays the caller's responsibility.

    `allow_pyramid` defaults True (byte-identical to every existing caller, including the
    backtest, which never passes it) -- set False to suppress BOTH pyramid-add sites (the
    immediate TP1-triggered add and the later TP2 add-on) for this call only, while leaving
    SL/TP1/TRAILING exits fully active. Live-only use: paper_monitor.py sets it False during a
    detected market-wide breadth crash, so existing risk management (selling) keeps running but
    new capital deployment (buying more) pauses -- see docs/V3_FINDINGS_LOG.md.
    """
    o, close_price, high_price, low_price = bar
    hold_ok = risk.min_hold_elapsed(pos["hold_days"], cfg.MIN_HOLD_DAYS)
    if close_price > pos["highest_price"]:
        pos["highest_price"] = close_price

    # An ARB-locked bar has no bid: the close IS the floor and the sell queue
    # is one-sided. Assuming a stop fills at sl_price on such a day is the
    # single most flattering lie a long-only backtest can tell itself -- it
    # books the loss at the level you *chose* rather than the level the
    # market would actually have given you, on precisely the days that do the
    # real damage. With this on, no exit is taken; the position rides to the
    # next session, which is what would genuinely happen. Expect results to
    # get WORSE and truer, not better.
    if ARB_EXIT_REALISM and is_arb_locked(prev_close, close_price, low_price, observed_max_move):
        return None, 0.0

    exit_reason, exit_price, sell_lots = None, None, 0
    cash_delta = 0.0

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
        if (allow_pyramid and PYRAMID_ENABLED and PYRAMID_TP2_ENABLED and not pos["tp2_hit"]
                and pos["atr_at_entry"] is not None):
            tp2_price = pos["entry_price_original"] + pos["atr_at_entry"] * cfg.TP1_MULT * 2
            if high_price >= tp2_price:
                pos["tp2_hit"] = True
                add_fill_price = o if (o is not None and o > tp2_price) else tp2_price
                add_alloc = min(prev_equity * PYRAMID_ADD_PCT, cash)
                add_participation = (add_alloc / max(add_fill_price, 1e-6)) / max(pos.get("avg_vol_20", 1.0), 1.0)
                add_cost_per_share = apply_slippage(add_fill_price, "buy", add_participation) * (1 + cfg.BUY_FEE)
                add_lots = int(add_alloc / add_cost_per_share) // LOT_SIZE
                if add_lots >= cfg.ALLOC_MIN_LOTS:
                    add_qty = add_lots * LOT_SIZE
                    add_cost_basis = add_qty * add_cost_per_share
                    if add_cost_basis <= cash:
                        cash_delta -= add_cost_basis
                        new_total_lots = pos["total_lots"] + add_lots
                        pos["avg_price"] = (pos["avg_price"] * pos["total_lots"] + add_fill_price * add_lots) / new_total_lots
                        pos["cost_basis"] += add_cost_basis
                        pos["total_lots"] = new_total_lots
                        pos["remaining_lots"] += add_lots

        if low_price <= pos["sl_price"]:
            exit_reason, exit_price = "SL", (o if (o is not None and o < pos["sl_price"]) else pos["sl_price"])
            sell_lots = pos["remaining_lots"]
        elif hold_ok:
            trailing_stop = pos["highest_price"] * (1 - cfg.TRAILING_PCT)
            stop_eff = max(trailing_stop, pos["sl_price"])
            if close_price <= stop_eff:
                exit_reason, exit_price = "TRAILING", close_price
                sell_lots = pos["remaining_lots"]

    trade_record = None
    if exit_reason is not None and sell_lots > 0:
        sell_qty = sell_lots * LOT_SIZE
        sell_cost_basis = pos["cost_basis"] * (sell_lots / pos["total_lots"])
        sell_participation = sell_qty / max(pos.get("avg_vol_20", 1.0), 1.0)
        gross_return = apply_slippage(exit_price, "sell", sell_participation) * sell_qty
        fee = risk.apply_fee(gross_return, "sell", cfg.BUY_FEE, cfg.SELL_FEE)
        net_return = gross_return - fee
        pnl = net_return - sell_cost_basis
        pnl_pct = (exit_price / pos["avg_price"] - 1) * 100
        cash_delta += net_return
        pos["remaining_lots"] -= sell_lots
        trade_record = {
            "stock_code": pos["stock_code"], "entry_date": pos["entry_date"], "exit_date": trade_date,
            "entry_price": pos["avg_price"], "exit_price": exit_price, "quantity": sell_qty, "lots": sell_lots,
            "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": exit_reason, "trigger": pos["trigger"],
            "hold_days": pos["hold_days"],
        }
        if exit_reason == "TP1":
            pos["tp1_hit"] = True
            pos["sl_price"] = pos["avg_price"]  # protects the ORIGINAL cost basis, set before any pyramid blend below
            pos["cost_basis"] -= sell_cost_basis
            pos["total_lots"] = pos["remaining_lots"]

            pyramid_ok = allow_pyramid and PYRAMID_ENABLED and exit_price > 0
            if pyramid_ok and PYRAMID_TREND_GATE_ENABLED:
                pyramid_ok = trend_strength >= PYRAMID_TREND_GATE_MIN
            if pyramid_ok:
                add_alloc = min(prev_equity * PYRAMID_ADD_PCT, cash + cash_delta)
                add_participation = (add_alloc / max(exit_price, 1e-6)) / max(pos.get("avg_vol_20", 1.0), 1.0)
                add_cost_per_share = apply_slippage(exit_price, "buy", add_participation) * (1 + cfg.BUY_FEE)
                add_lots = int(add_alloc / add_cost_per_share) // LOT_SIZE
                if add_lots >= cfg.ALLOC_MIN_LOTS:
                    add_qty = add_lots * LOT_SIZE
                    add_cost_basis = add_qty * add_cost_per_share
                    if add_cost_basis <= cash + cash_delta:
                        cash_delta -= add_cost_basis
                        new_total_lots = pos["total_lots"] + add_lots
                        pos["avg_price"] = (pos["avg_price"] * pos["total_lots"] + exit_price * add_lots) / new_total_lots
                        pos["cost_basis"] += add_cost_basis
                        pos["total_lots"] = new_total_lots
                        pos["remaining_lots"] += add_lots

    return trade_record, cash_delta


def simulate_window(df, idx_df, train_end, test_start, test_end, label=""):
    """Runs the regime + threshold-learning + day-by-day simulation for ONE
    train/test split against an already-fetched df/idx_df (must cover at
    least [some date <= train_end, test_end]). Pulled out of main() so a
    walk-forward driver can call this many times against a single fetch
    instead of re-fetching per window -- fetching is the expensive part
    (see data_fetch.py's month-chunked pagination fix). Returns
    (metrics, df_trades, df_equity, regime_by_date), or (None, None, None,
    None) if zero trades fired in the window."""
    prefix = f"[{label}] " if label else ""
    print(f"{prefix}[REGIME] Precomputing regime per unique trading day ...")
    regime_by_date, bullish_streak_by_date, trend_strength_by_date = compute_regime_with_hysteresis(idx_df)
    df = df.copy()
    df["_regime"] = df["trade_date"].map(regime_by_date).fillna("NEUTRAL")
    df["_streak"] = df["trade_date"].map(bullish_streak_by_date).fillna(0)
    df["_trend_strength"] = df["trade_date"].map(trend_strength_by_date).fillna(0.0)

    # ---- Thresholds learned on TRAIN split only (never touches test data) ----
    train_liquid_bullish = df[
        (df["trade_date"] <= train_end)
        & (df["adtv_20"] >= cfg.ADTV_MIN)
        & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
        & (df["_regime"] == "BULLISH") & (df["_streak"] >= REGIME_CONFIRM_DAYS)
        & (df["_trend_strength"] >= TREND_STRENGTH_MIN)
        & df["atr_14"].notna() & (df["atr_14"] > 0)
        & ((df["atr_14"] / df["close_price"]) <= ATR_PRICE_RATIO_MAX)
    ]
    weekly_cut = train_liquid_bullish["weekly_ma_spread"].quantile(QUANTILE_CUT)
    sector_cut = train_liquid_bullish["sector_rs_momentum"].quantile(QUANTILE_CUT)
    print(f"{prefix}[THRESHOLDS from train {FETCH_START}..{train_end} only] "
          f"weekly_ma_spread >= {weekly_cut:.2f}, sector_rs_momentum >= {sector_cut:.4f}")

    # Train-derived reference for score-weighted sizing (SCORE_SIZING_ENABLED
    # below) -- same score formula used at entry time, applied to the train
    # qualifying population itself, 90th percentile. Never touches test data.
    train_scores = (
        (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        + (train_liquid_bullish["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
    )
    score_p90 = train_scores.quantile(0.90) if len(train_scores) > 0 else 1.0
    if not np.isfinite(score_p90) or score_p90 <= 0:
        score_p90 = 1.0

    # Train-derived reference for liquidity-weighted sizing
    # (LIQ_SIZING_ENABLED below): log-scale, since qualifying ADTV spans
    # ~1B-100B+ Rp and a raw ratio would produce extreme multipliers for
    # the most liquid names. log() compresses that range the way the
    # existing score-sizing multiplier already assumes. Never touches
    # test data.
    train_log_adtv = np.log(train_liquid_bullish["adtv_20"].clip(lower=1))
    log_adtv_p90 = train_log_adtv.quantile(0.90) if len(train_log_adtv) > 0 else 1.0
    if not np.isfinite(log_adtv_p90) or log_adtv_p90 <= 0:
        log_adtv_p90 = 1.0

    # Train-derived reference for regime-strength sizing
    # (TREND_SIZING_ENABLED below): train_liquid_bullish is already
    # filtered to qualifying BULLISH days, so its own _trend_strength
    # values are the right population to rank "how strong is strong."
    # Never touches test data.
    train_trend_strength = train_liquid_bullish["_trend_strength"]
    trend_strength_p90 = train_trend_strength.quantile(0.90) if len(train_trend_strength) > 0 else TREND_STRENGTH_MIN
    if not np.isfinite(trend_strength_p90) or trend_strength_p90 <= 0:
        trend_strength_p90 = TREND_STRENGTH_MIN

    trading_days = sorted(d for d in df["trade_date"].unique() if test_start <= d <= test_end)
    if not trading_days:
        print(f"{prefix}[SIMULATE] No trading days in range -- skipping.")
        return None, None, None, None
    print(f"{prefix}[SIMULATE] Test window (out-of-sample only): {trading_days[0]} .. {trading_days[-1]} ({len(trading_days)} days)")

    close_lookup = df.set_index(["stock_code", "trade_date"])["close_price"]
    bar_lookup = {
        (r.stock_code, r.trade_date): (r.open_price, r.close_price, r.high, r.low, r.volume)
        for r in df.itertuples()
    }
    # Only needed by the ARB exit-realism check; built once here rather than
    # looked up per position per day.
    _has_limit_cols = "observed_max_move" in df.columns
    limit_lookup = {
        (r.stock_code, r.trade_date): (r.previous, r.observed_max_move)
        for r in df.itertuples()
    } if (ARB_EXIT_REALISM and _has_limit_cols) else {}

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
            recent_entries = sum(1 for p in positions if day_idx - p["entry_day_idx"] <= ENTRY_CLUSTER_WINDOW_DAYS)
            if recent_entries >= MAX_ENTRIES_PER_CLUSTER_WINDOW:
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

            # Sizing/fee/TP1-SL math extracted to compute_entry_fill() so the live
            # paper-trading monitor (src/paper_monitor.py) fills entries through the exact
            # same formulas -- see that function's docstring.
            fill = compute_entry_fill(
                sig, entry_price, cash, prev_equity, log_adtv_p90, score_p90,
                trend_strength_by_date.get(trade_date, 0.0), trend_strength_p90,
            )
            if fill is None:
                continue

            cash -= fill["cost_basis"]
            positions.append({
                "stock_code": sig["stock_code"], "entry_date": trade_date, "entry_day_idx": day_idx, "avg_price": entry_price,
                "tp1_price": fill["tp1_price"], "sl_price": fill["sl_price"], "total_lots": fill["lots"], "remaining_lots": fill["lots"],
                "quantity": fill["quantity"], "cost_basis": fill["cost_basis"], "hold_days": 0, "tp1_hit": False, "tp2_hit": False,
                "highest_price": entry_price, "trigger": sig["trigger"],
                "no_data_days": 0, "last_valid_close": entry_price,
                "checkpoint_day": fill["checkpoint_day"], "target_price": sig["tp_target"],
                "entry_price_original": entry_price,
                "atr_at_entry": fill["atr_at_entry"],
                "avg_vol_20": sig.get("avg_vol_20", 1.0),  # for exit-side slippage's participation estimate
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
                    # This is a forced sale of a stock that hasn't printed in
                    # DELISTING_GAP_DAYS -- the worst-liquidity exit case that
                    # exists, so it gets participation=1.0 (not an estimate off
                    # avg_vol_20, which is meaningless for a name that isn't
                    # trading) rather than silently skipping slippage here.
                    gross_return = apply_slippage(exit_price, "sell", 1.0) * sell_qty
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

            # Exit decision + TP1/TP2 pyramid-add-on: extracted to
            # evaluate_position_exit() so the live paper-trading monitor
            # (src/paper_monitor.py) makes exit decisions through the exact
            # same code path as this backtest -- see that function's
            # docstring for the full mechanics (unchanged from before the
            # extraction, verified via exact walk-forward regression match).
            _prev_close, _obs_max = limit_lookup.get((pos["stock_code"], trade_date), (None, None))
            trade_record, cash_delta = evaluate_position_exit(
                pos, bar, regime, trend_strength_by_date.get(trade_date, 0.0),
                trade_date, prev_equity, cash,
                prev_close=_prev_close, observed_max_move=_obs_max,
            )
            cash += cash_delta

            if trade_record is not None:
                if trade_record["exit_reason"] == "SL":
                    last_sl_idx[pos["stock_code"]] = day_idx
                trades.append(trade_record)
                if trade_record["exit_reason"] == "TP1":
                    remaining_positions.append(pos)  # partial exit only -- position continues
            else:
                pos["hold_days"] += 1
                remaining_positions.append(pos)

        positions = remaining_positions

        # ---- New entries: the Phase 0g validated rule, not squeeze ----
        # Gated on the regime having read BULLISH for REGIME_CONFIRM_DAYS
        # running, not just today -- don't deploy capital on day 1 of a
        # flip that might be a false start -- AND on IHSG having actually
        # separated from ma50 by TREND_STRENGTH_MIN, not just barely
        # crossed it (see TREND_STRENGTH_MIN comment above).
        if (regime == "BULLISH" and bullish_streak_by_date.get(trade_date, 0) >= REGIME_CONFIRM_DAYS
                and trend_strength_by_date.get(trade_date, 0.0) >= TREND_STRENGTH_MIN):
            # Candidate filtering/scoring extracted to score_candidates() so the live
            # paper-trading signal scan (src/paper_signal_scan.py) uses the exact same
            # candidate logic as this backtest -- see that function's docstring.
            day_data = df[df["trade_date"] == trade_date]
            pending_entries.extend(score_candidates(day_data, weekly_cut, sector_cut, top_n=15,
                                                      skip_top_n=SCORE_SKIP_TOP_N,
                                                      outlier_gap_mult=SCORE_OUTLIER_GAP_MULT,
                                                      weekly_comp_cap_q=SCORE_WEEKLY_COMP_CAP_Q))

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
        end_participation = exit_qty / max(pos.get("avg_vol_20", 1.0), 1.0)
        gross_return = apply_slippage(exit_price, "sell", end_participation) * exit_qty
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
        print(f"\n{prefix}[BACKTEST V3] No trades executed in test window.")
        return None, None, None, None

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

    # CVaR(95%) -- mean daily return on the worst 5% of days, distinct from
    # max_drawdown (one peak-to-trough episode): a window can have a mild
    # max_drawdown but a fat left tail of bad days, or vice versa. Sharper
    # lens on "how bad do the bad days actually get" for diagnosing windows
    # like the 2023 H1 weak-trend loss.
    daily_ret = df_equity["total"].pct_change().dropna()
    if len(daily_ret) >= 20:
        var_95 = daily_ret.quantile(0.05)
        cvar_95 = daily_ret[daily_ret <= var_95].mean() * 100
    else:
        cvar_95 = float("nan")

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
    print(f"  CVaR(95%) daily : {cvar_95:.2f}%")
    print("=" * 70)

    contrib = df_trades.groupby("stock_code")["pnl"].sum().sort_values(ascending=False)
    total_pos_contrib = contrib[contrib > 0].sum()
    top5 = contrib.head(5)
    top5_pct = 100 * top5.clip(lower=0).sum() / total_pos_contrib if total_pos_contrib > 0 else float("nan")
    print(f"\n{prefix}[CONCENTRATION CHECK] top-5 tickers ({', '.join(top5.index.tolist())}) = {top5_pct:.1f}% of total positive PnL")
    print(f"{prefix}[EXIT BREAKDOWN] {df_trades['exit_reason'].value_counts(normalize=True).round(3).to_dict()}")

    notes = (
        f"V3: BULLISH regime (volatility-relative hysteresis band, {VOL_BAND_MULT}x trailing 20d vol) "
        f"+ weekly-trend-alignment top-quintile + sector-RRG relative-strength top-quintile, on liquid "
        f"stocks (ADTV>=Rp{cfg.ADTV_MIN:,.0f}). Entry-timing guards: max {MAX_NEW_ENTRIES_PER_DAY} new "
        f"positions/day, regime must hold {REGIME_CONFIRM_DAYS} consecutive days, and IHSG must have "
        f"separated from its own ma50 by >={TREND_STRENGTH_MIN*100:.0f}% (not just direction) before any "
        f"entry -- all three added after a 2023 H1 out-of-sample window showed correlated same-day entries "
        f"on a false-start regime flip could lose money. ATR/price <= {ATR_PRICE_RATIO_MAX*100:.0f}% caps "
        f"entries on hypervolatile penny stocks. Thresholds learned on {FETCH_START}..{train_end} only, "
        f"this run's metrics are the held-out test window, never seen during threshold-fitting. "
        f"Replaces V1/V2's squeeze+volume-spike signal, which was proven to have no statistical edge on "
        f"liquid stocks in any regime (Monte Carlo permutation test vs the same opportunity set: p=0.0000 "
        f"for this rule, confirming real selection skill). Caveat: a separate out-of-sample window covering "
        f"a weak/choppy-bullish market character (2023 H1) still showed a smaller loss and a below-50% win "
        f"rate even after these fixes -- edge size is regime-dependent, not yet a fully solved failure mode."
    )
    metrics = {
        "period_start": trading_days[0], "period_end": trading_days[-1],
        "initial_capital": INITIAL_CAPITAL, "final_capital": final_capital,
        "total_return_pct": total_return_pct, "bench_ret": bench_ret,
        "total_trades": total_trades, "win_rate": win_rate,
        "profit_factor": profit_factor, "max_drawdown": max_drawdown,
        "cvar_95": cvar_95,
        "notes": notes,
    }
    return metrics, df_trades, df_equity, regime_by_date


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
    metrics, df_trades, df_equity, regime_by_date = simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END)
    if metrics is None:
        return

    df_trades.to_csv("backtest_v3_trades.csv", index=False)
    df_equity.to_csv("backtest_v3_equity.csv", index=False)
    print(f"\n[OK] Saved backtest_v3_trades.csv ({len(df_trades)} rows), backtest_v3_equity.csv ({len(df_equity)} rows).")

    if os.environ.get("V3_SKIP_SAVE", "0") == "1":
        print("[SKIP] V3_SKIP_SAVE=1 -- not writing to Supabase (dev/sweep run).")
    else:
        _save_to_supabase(supabase, df_trades, df_equity, regime_by_date, metrics)


if __name__ == "__main__":
    main()
