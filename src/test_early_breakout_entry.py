"""Is an EARLIER entry actually better, judged per trade rather than per portfolio?

Two rejections already stand (extension gate, removing the weekly feature's
Friday lag). Both tested a modification of the existing entry, and both were
judged on 9-window portfolio alpha. That metric is structurally unkind to what
the user is actually proposing: a system that trades rarely, sits in cash, and
wins big when it wins would show weak per-window alpha and still be the better
strategy for him. So this test changes both things -- a genuinely separate entry
rule, and a per-trade verdict.

Design, and what it deliberately holds constant:

  ENTRY (the only thing that differs)
    Neira  : the live rule -- weekly_ma_spread and sector_rs_momentum both above
             their train-derived cuts, ranked by score, top 15.
    Early  : a UT Bot flip to long (close crosses above its ATR trailing line,
             key=1.0, ATR 10) -- the same trigger that bought EMAS at 6,100 and
             BEEF at 160 while Neira waited until 7,900 and 414.

  EXITS, LIQUIDITY, REGIME (identical for both)
    Neira's own exit logic replayed bar by bar: SL 1.5xATR, TP1 1.5xATR selling
    10%, 8% trailing off the peak close once TP1 has fired, MIN_HOLD_DAYS 3, and
    the 20-day cap with its in-profit-and-bullish escape hatch. Same ADTV floor,
    same ATR/price ceiling, same bullish-regime requirement.

  So any difference in the numbers is attributable to entry timing alone. This
  is NOT a portfolio simulation: no slots, no capital, no position sizing, one
  trade per signal. It answers "are these better trades", not "would this make
  more money" -- that is the follow-up if and only if it wins here.

Honest limits, stated before the numbers: every signal is taken, so the Early
rule gets far more trades and no slot competition; costs are modelled (fees +
slippage are NOT, see below) so both sides are equally flattered; and a
per-trade win says nothing about whether 6 slots could have held the winners.

Usage:
    python src/test_early_breakout_entry.py
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import config as cfg  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from scratch_utbot_emas import wilder_atr  # noqa: E402

START = date(2022, 1, 1)


def replay_exit(highs, lows, closes, ei, atr_at_entry, regime_ok_by_i):
    """Neira's exit rules, bar by bar, from entry index `ei`.

    Returns (reason, exit_index, pct). Mirrors evaluate_position_exit as of
    2026-09-02; see scratch_can_we_hold_a_multibagger.py for the same replay
    used on hand-picked winners.
    """
    entry = closes[ei]
    sl = entry - cfg.ATR_SL_MULTIPLIER * atr_at_entry
    tp1 = entry + cfg.TP1_MULT * atr_at_entry
    tp1_hit = False
    highest = entry
    for i in range(ei + 1, len(closes)):
        held = i - ei
        hold_ok = held >= cfg.MIN_HOLD_DAYS
        if closes[i] > highest:
            highest = closes[i]
        if lows[i] <= sl:
            return "SL", i, 100 * (sl / entry - 1)
        if not tp1_hit:
            if hold_ok and highs[i] >= tp1:
                tp1_hit = True
            elif held >= cfg.MAX_HOLD_DAYS - 1:
                if not (closes[i] > entry and regime_ok_by_i[i]):
                    return "TIME", i, 100 * (closes[i] / entry - 1)
        elif hold_ok:
            stop = max(highest * (1 - cfg.TRAILING_PCT), sl)
            if closes[i] <= stop:
                return "TRAILING", i, 100 * (closes[i] / entry - 1)
    return "OPEN", len(closes) - 1, 100 * (closes[-1] / entry - 1)


def ut_bot_flips(highs, lows, closes, key=1.0, period=10):
    """Indices where UT Bot flips from flat/short to long."""
    atr = wilder_atr(highs, lows, closes, period)
    stop = None
    pos = 0
    out = []
    for i, c in enumerate(closes):
        if atr[i] is None:
            continue
        n_loss = key * atr[i]
        prev = stop if stop is not None else 0.0
        prev_c = closes[i - 1] if i else c
        if c > prev and prev_c > prev:
            stop = max(prev, c - n_loss)
        elif c < prev and prev_c < prev:
            stop = min(prev, c + n_loss)
        elif c > prev:
            stop = c - n_loss
        else:
            stop = c + n_loss
        new = 1 if c > stop else -1
        if pos != 0 and new == 1 and pos != new:
            out.append(i)
        pos = new
    return out


def stats(name, rets):
    if not rets:
        print(f"  {name:<26} no trades")
        return None
    r = np.array(rets, dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.size and losses.sum() else float("inf")
    print(f"  {name:<26} n={len(r):<6} win {100 * len(wins) / len(r):5.1f}%  "
          f"mean {r.mean():+6.2f}%  median {np.median(r):+6.2f}%  "
          f"avgW {wins.mean() if wins.size else 0:+6.2f}%  "
          f"avgL {losses.mean() if losses.size else 0:+6.2f}%  PF {pf:5.2f}")
    return {"n": len(r), "win": 100 * len(wins) / len(r), "mean": r.mean(),
            "median": float(np.median(r)), "pf": pf}


def main():
    df, idx_df = wf.load_dataset(None)
    regime_by_date, streak_by_date, trend_by_date = bt.compute_regime_with_hysteresis(idx_df)

    def regime_ok(d):
        return (regime_by_date.get(d) == "BULLISH"
                and streak_by_date.get(d, 0) >= bt.REGIME_CONFIRM_DAYS
                and trend_by_date.get(d, 0.0) >= bt.TREND_STRENGTH_MIN)

    df = df[df["trade_date"] >= START].sort_values(["stock_code", "trade_date"])
    # The cuts the live rule uses are train-derived per window; for a per-trade
    # comparison over one span, use the same quantile on the same liquid pool
    # the backtest learns from. Not a walk-forward -- stated as a limit above.
    liq = df[(df["adtv_20"] >= cfg.ADTV_MIN) & df["weekly_ma_spread"].notna()
             & df["sector_rs_momentum"].notna() & df["atr_14"].notna() & (df["atr_14"] > 0)]
    wk_cut = liq["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
    sec_cut = liq["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)
    print(f"cuts: weekly_ma_spread >= {wk_cut:.2f}, sector_rs_momentum >= {sec_cut:.4f}\n")

    neira_rets, early_rets, early_lag = [], [], []
    n_codes = 0
    for code, g in df.groupby("stock_code", sort=False):
        g = g.reset_index(drop=True)
        if len(g) < 60:
            continue
        n_codes += 1
        highs = g["high"].astype(float).tolist()
        lows = g["low"].astype(float).tolist()
        closes = g["close_price"].astype(float).tolist()
        dates = g["trade_date"].tolist()
        atr14 = g["atr_14"].astype(float).tolist()
        adtv = g["adtv_20"].astype(float).tolist()
        wk = g["weekly_ma_spread"].astype(float).tolist()
        sec = g["sector_rs_momentum"].astype(float).tolist()
        ok = [regime_ok(d) for d in dates]

        def tradeable(i):
            return (adtv[i] >= cfg.ADTV_MIN and closes[i] > 0 and highs[i] > 0
                    and atr14[i] and atr14[i] > 0
                    and atr14[i] / closes[i] <= bt.ATR_PRICE_RATIO_MAX and ok[i])

        # --- Neira's entry: both cuts cleared, and it is a NEW qualification
        # (not every day of a long qualifying stretch, which would count the
        # same setup dozens of times and drown the comparison).
        qual = [tradeable(i) and wk[i] >= wk_cut and sec[i] >= sec_cut
                for i in range(len(g))]
        neira_idx = [i for i in range(1, len(g)) if qual[i] and not qual[i - 1]]

        # --- Early entry: UT Bot flip, same liquidity/ATR/regime conditions.
        early_idx = [i for i in ut_bot_flips(highs, lows, closes) if tradeable(i)]

        for i in neira_idx:
            _, _, pct = replay_exit(highs, lows, closes, i, atr14[i], ok)
            neira_rets.append(pct)
        for i in early_idx:
            _, _, pct = replay_exit(highs, lows, closes, i, atr14[i], ok)
            early_rets.append(pct)
        # How much earlier is Early, when both fire on the same setup?
        for i in early_idx:
            later = [j for j in neira_idx if 0 < j - i <= 30]
            if later:
                early_lag.append((later[0] - i, 100 * (closes[later[0]] / closes[i] - 1)))

    print(f"{n_codes} tickers, {START} .. {bt.TEST_END}, identical exits both sides\n")
    n = stats("Neira (current entry)", neira_rets)
    e = stats("Early (UT Bot flip)", early_rets)

    if early_lag:
        lags = np.array([x[0] for x in early_lag])
        gaps = np.array([x[1] for x in early_lag])
        print(f"\n  When both fire on the same setup ({len(lags)} pairs): Early is "
              f"{np.median(lags):.0f} sessions earlier (median), at a price "
              f"{np.median(gaps):+.1f}% lower.")

    if n and e:
        print(f"\n  Trades per year: Neira {n['n'] / 4.5:.0f}, Early {e['n'] / 4.5:.0f}")
        print(f"  Verdict on trade QUALITY (not portfolio): "
              f"{'Early wins' if e['pf'] > n['pf'] and e['mean'] > n['mean'] else 'Early does NOT win'}")
    print("\n  Reminder: no slots, no sizing, no fees/slippage on either side. "
          "This compares entries, not strategies.")


if __name__ == "__main__":
    main()
