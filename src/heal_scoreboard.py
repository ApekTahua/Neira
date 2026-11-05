"""heal_scoreboard.py -- self-healing safety net for the display tables.

Why this exists (2026-11-01): from 2026-10-22 the daily scoreboard went dark
and stayed dark. Two independent failures stacked:
  1. index_eod for 10-22 never loaded, so that day's scan wrote a default
     NEUTRAL/regime_ok=False gate row and an EMPTY scoreboard (F-023's shape).
  2. ihsg_eod itself stopped loading after 10-23 (dead Browserless credential).
Even after the data is repaired, paper_signal_scan.py will not revisit a day
it already marked processed (last_signal_date == that day), so a bad gate row
or an empty scoreboard would stay forever. This script is the missing second
half of the safety net: it looks back HEAL_LOOKBACK_DAYS, and for every day
where BOTH stock and index prices now exist but the gate row is missing /
is the no-index default / the scoreboard is empty, it recomputes with the
SAME functions the live scan uses and upserts.

Scope is deliberately narrow:
  - writes ONLY daily_gate_summary, daily_scoreboard, and (only when a
    regime_ok day has none) daily_qualifying_signals -- the three display
    tables, never read back into trading decisions;
  - never touches paper_positions / paper_account / backtest_* -- a missed
    entry stays missed (HOLDOUT_PROTOCOL.md, 2026-10-01 amendment);
  - no-ops in a few seconds, with no heavy fetch, when nothing needs healing.

Env: SUPABASE_URL, SUPABASE_KEY (service role). Optional HEAL_LOOKBACK_DAYS.
"""

import os
import sys
from datetime import date, timedelta

from supabase import create_client

os.environ.setdefault("V4_BANDAR_SIZING", "1")
os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")  # matches paper_signal_scan_v4_trigger.yml

LOOKBACK_DAYS = int(os.environ.get("HEAL_LOOKBACK_DAYS", "14"))


def _retry(fn, attempts=4):
    import time
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2 * (i + 1))


def _is_default_gate(g) -> bool:
    """The row paper_signal_scan.py writes when it has no index bar for the
    day: regime=NEUTRAL, streak 0, trend exactly 0.0. A genuine NEUTRAL read
    never has trend_strength == 0.0 to machine precision."""
    return (g["regime"] == "NEUTRAL" and int(g["bullish_streak"]) == 0
            and abs(float(g["trend_strength"])) < 1e-12)


def find_days_to_heal(supabase, today: date) -> list:
    start = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    stock_days = {r["trade_date"] for r in _retry(lambda: supabase.table("ihsg_eod")
                  .select("trade_date").eq("stock_code", "BBCA").gte("trade_date", start).execute()).data}
    index_days = {r["trade_date"] for r in _retry(lambda: supabase.table("index_eod")
                  .select("trade_date").eq("index_code", "COMPOSITE").gte("trade_date", start).execute()).data}
    gates = {r["trade_date"]: r for r in _retry(lambda: supabase.table("daily_gate_summary")
             .select("trade_date,regime,bullish_streak,trend_strength").gte("trade_date", start).execute()).data}
    todo = []
    for d in sorted(stock_days & index_days):
        sb = _retry(lambda: supabase.table("daily_scoreboard").select("stock_code", count="exact")
                    .eq("trade_date", d).limit(1).execute())
        reasons = []
        if d not in gates:
            reasons.append("no gate row")
        elif _is_default_gate(gates[d]):
            reasons.append("gate row is the no-index NEUTRAL default")
        if (sb.count or 0) == 0:
            reasons.append("scoreboard empty")
        if reasons:
            todo.append((d, "; ".join(reasons)))
    return todo


def main():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_KEY not set")
    supabase = create_client(url, key)

    todo = find_days_to_heal(supabase, date.today())
    if not todo:
        print(f"[HEAL] nothing to heal in the last {LOOKBACK_DAYS} days -- gate + scoreboard complete.")
        return
    for d, why in todo:
        print(f"[HEAL] {d}: {why}")

    # backtest_v4 reads V4_TEST_END at import time -> set it before importing.
    os.environ["V4_TEST_END"] = max(d for d, _ in todo)
    import numpy as np
    import backtest_v4 as bt
    import config as cfg

    df, idx_df = bt.build_full_dataset(supabase)

    for d_iso, _ in todo:
        trade_date = date.fromisoformat(d_iso)
        # Walk-forward truncation: a day is scored using only data up to that day.
        df_t = df[df["trade_date"] <= trade_date]
        idx_t = idx_df[idx_df["trade_date"] <= trade_date]
        regime_by_date, streak_by_date, trend_by_date = bt.compute_regime_with_hysteresis(idx_t)
        regime = regime_by_date.get(trade_date)
        if regime is None:
            print(f"[HEAL] {d_iso}: still no computable regime (ma50 not available) -- left untouched.")
            continue
        streak = streak_by_date.get(trade_date, 0)
        trend = trend_by_date.get(trade_date, 0.0)

        pool = df_t[
            (df_t["adtv_20"] >= cfg.ADTV_MIN)
            & df_t["weekly_ma_spread"].notna() & df_t["sector_rs_momentum"].notna()
            & (df_t["trade_date"].map(regime_by_date).fillna("NEUTRAL") == "BULLISH")
            & (df_t["trade_date"].map(streak_by_date).fillna(0) >= bt.REGIME_CONFIRM_DAYS)
            & (df_t["trade_date"].map(trend_by_date).fillna(0.0) >= bt.TREND_STRENGTH_MIN)
            & df_t["atr_14"].notna() & (df_t["atr_14"] > 0)
            & ((df_t["atr_14"] / df_t["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
        ]
        weekly_cut = pool["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
        sector_cut = pool["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)
        train_scores = ((pool["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
                        + (pool["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6))
        score_p90 = train_scores.quantile(0.90) if len(train_scores) > 0 else 1.0
        if not np.isfinite(score_p90) or score_p90 <= 0:
            score_p90 = 1.0
        regime_ok = bool(regime == "BULLISH" and streak >= bt.REGIME_CONFIRM_DAYS
                         and trend >= bt.TREND_STRENGTH_MIN)

        day = df_t[df_t["trade_date"] == trade_date]
        scoreboard = bt.score_full_universe(day, weekly_cut, sector_cut, score_p90, regime_ok)
        scored = bt.score_candidates(day, weekly_cut, sector_cut, top_n=15) if regime_ok else []

        _retry(lambda: supabase.table("daily_gate_summary").upsert({
            "trade_date": d_iso, "regime": regime, "bullish_streak": int(streak),
            "trend_strength": float(trend), "regime_ok": regime_ok,
            "weekly_cut": float(weekly_cut), "sector_cut": float(sector_cut), "score_p90": float(score_p90),
            "atr_ratio_max": float(bt.ATR_PRICE_RATIO_MAX), "adtv_min": float(cfg.ADTV_MIN),
        }, on_conflict="trade_date").execute())
        if scoreboard:
            rows = [{
                "trade_date": d_iso, "stock_code": r["stock_code"], "score": r["score"], "label": r["label"],
                "percentile": r["percentile"], "weekly_ma_spread": r["weekly_ma_spread"],
                "sector_rs_momentum": r["sector_rs_momentum"], "close_price": r["close_price"],
                "adtv_20": r["adtv_20"], "atr_14": r["atr_14"],
            } for r in scoreboard]
            for i in range(0, len(rows), 200):
                _retry(lambda c=rows[i:i + 200]: supabase.table("daily_scoreboard")
                       .upsert(c, on_conflict="trade_date,stock_code").execute())
        if scored:
            have = _retry(lambda: supabase.table("daily_qualifying_signals").select("stock_code", count="exact")
                          .eq("trade_date", d_iso).limit(1).execute())
            if (have.count or 0) == 0:  # never overwrite what the live scan already published
                _retry(lambda: supabase.table("daily_qualifying_signals").upsert([{
                    "trade_date": d_iso, "stock_code": s["stock_code"], "rank": i + 1, "score": s["score"],
                    "trigger": s["trigger"], "adtv_20": s["adtv_20"], "avg_vol_20": s["avg_vol_20"], "atr": s["atr"],
                    "signal_close": s["signal_close"], "tp_target": s["tp_target"], "concentration": s.get("concentration"),
                } for i, s in enumerate(scored)], on_conflict="trade_date,stock_code").execute())
        print(f"[HEAL] {d_iso}: regime={regime} streak={streak} regime_ok={regime_ok} trend={trend:+.4f} "
              f"-> scoreboard {len(scoreboard)} rows, qualifying {len(scored)}")


if __name__ == "__main__":
    main()
