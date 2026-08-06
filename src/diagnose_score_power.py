"""diagnose_score_power.py -- does the score actually rank anything?

The question this answers (raised 2026-08-04): stock A scores 99 and stops
out tomorrow while stock B scores 97 and rises. Is the system wrong?

It is only wrong if the score claims to predict tomorrow. It doesn't -- it
is a cross-sectional RANK on two features (weekly_ma_spread,
sector_rs_momentum), and the edge was only ever validated as a portfolio
effect over many trades. At ~55% win rate, ~45% of picks losing is the
design, not a defect.

But that defence is only honest if the ranking carries information at all.
If rank #1 and rank #12 have the same forward return, then taking the top
MAX_NEW_ENTRIES_PER_DAY=2 is arbitrary, the 99-vs-97 difference shown on
the site is fake precision, and the right move is to stop pretending the
order means something -- diversify across the qualifying set instead, or
tie-break on something that IS predictive.

That is a measurable question, so this measures it. For every day in the
sample it takes the full qualifying candidate set (the same
score_candidates() gate the live engine uses, just without the top-N cut),
buys nothing, and simply records what each candidate did afterwards:

  * forward return from the NEXT session's open (the price the engine would
    actually have paid) over 5 / 10 / 20 sessions
  * whether the ATR-based stop would have been hit first

Then it groups by rank-within-day and reports the spread. Also compares the
score ordering against two alternative orderings that cost nothing to adopt:
liquidity (adtv_20) and calmness (lowest ATR/price) -- the user's own
instinct was "kalau disuruh memilih, pasti saya pilih yang top dan liquid",
which is a testable hypothesis, not just a feeling.

Run #1 (2026-08-04) found the OPPOSITE of what you'd want: top-2 by score
underperformed rank 6-12 on every metric (win rate, mean return, SL-hit
rate), and the same inversion held under the liquidity and calmness
orderings too. Fair pushback received the same night: one aggregate number
over one sample window is exactly the kind of single-point read that burned
the hysteresis-band tuning earlier this session (2% band looked great in
isolation, then the surrounding sweep showed a 61%-501% swing on nearby
values -- one lucky point, not a real optimum). "Top rank could still be
better in some other period" is a real possibility this script's original
aggregate-only output couldn't rule out. So it now ALSO breaks the same
comparison down by the same 6-month rolling windows walk_forward_v3.py
uses, and reports whether "top 2 underperforms rank 6-12" holds in most/
all windows or is itself period-specific -- the walk-forward's own
consistency standard, applied to this question too.

Reads only. Writes no Supabase table, touches no paper-trading state.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/diagnose_score_power.py
"""

import os
import sys
from datetime import date, timedelta

os.environ.setdefault("V3_TEST_END", date.today().isoformat())

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as cfg  # noqa: E402
import backtest_v3 as bt  # noqa: E402
from supabase import create_client  # noqa: E402

HORIZONS = (5, 10, 20)
TOP_N_TRACKED = 12  # how deep into the daily ranking to follow
START = os.environ.get("DIAG_START", "2022-01-01")
WINDOW_MONTHS = 6  # matches walk_forward_v3.py's rolling-window size


def _month_add(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def window_label(d: date, first_start: date, months: int = WINDOW_MONTHS) -> str:
    """Which non-overlapping N-month block `d` falls into, counted from
    first_start -- same block boundaries walk_forward_v3.py's own
    build_schedule() produces, so results from the two scripts line up."""
    cursor = first_start
    while True:
        nxt = _month_add(cursor, months)
        if d < nxt:
            return f"{cursor.isoformat()}..{(nxt - timedelta(days=1)).isoformat()}"
        cursor = nxt


def main():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("[FETCH] Building full dataset ...", flush=True)
    df, idx_df = bt.build_full_dataset(supabase)
    regime_by_date, streak_by_date, trend_by_date = bt.compute_regime_with_hysteresis(idx_df)

    start = date.fromisoformat(START)
    days = sorted(d for d in df["trade_date"].unique() if d >= start)
    print(f"[DIAG] {len(days)} sessions from {days[0]} to {days[-1]}", flush=True)

    # Forward opens/closes per stock, positionally -- the engine buys at the
    # NEXT session's open, so that is the anchor, not the signal close.
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    g = df.groupby("stock_code", sort=False)
    df["next_open"] = g["open_price"].shift(-1)
    for h in HORIZONS:
        df[f"fwd_close_{h}"] = g["close_price"].shift(-(h + 1))
        df[f"fwd_min_low_{h}"] = g["low"].shift(-1).rolling(h, min_periods=1).min().reset_index(level=0, drop=True)

    indexed = df.set_index(["stock_code", "trade_date"])
    rows = []

    for d in days:
        if regime_by_date.get(d, "NEUTRAL") != "BULLISH":
            continue
        if streak_by_date.get(d, 0) < bt.REGIME_CONFIRM_DAYS:
            continue
        if trend_by_date.get(d, 0.0) < bt.TREND_STRENGTH_MIN:
            continue

        train = df[
            (df["trade_date"] <= d)
            & (df["adtv_20"] >= cfg.ADTV_MIN)
            & df["weekly_ma_spread"].notna() & df["sector_rs_momentum"].notna()
        ]
        if train.empty:
            continue
        weekly_cut = train["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
        sector_cut = train["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)

        scored = bt.score_candidates(df[df["trade_date"] == d], weekly_cut, sector_cut, top_n=TOP_N_TRACKED)
        for rank, sig in enumerate(scored, start=1):
            try:
                bar = indexed.loc[(sig["stock_code"], d)]
            except KeyError:
                continue
            entry = bar["next_open"]
            if pd.isna(entry) or entry <= 0:
                continue
            atr = sig["atr"]
            sl = entry - atr * 1.5 if atr and atr > 0 else entry * 0.98
            rec = {
                "trade_date": d, "window": window_label(d, days[0]), "stock_code": sig["stock_code"], "rank": rank,
                "score": sig["score"], "adtv_20": sig["adtv_20"],
                "atr_pct": (atr / entry) if atr and entry else np.nan,
            }
            for h in HORIZONS:
                fwd = bar[f"fwd_close_{h}"]
                rec[f"ret_{h}"] = (fwd / entry - 1) * 100 if pd.notna(fwd) and fwd > 0 else np.nan
                low = bar[f"fwd_min_low_{h}"]
                rec[f"sl_hit_{h}"] = bool(pd.notna(low) and low <= sl)
            rows.append(rec)

    res = pd.DataFrame(rows)
    if res.empty:
        sys.exit("[DIAG] No qualifying candidate-days in the sample.")

    print(f"\n[DIAG] {len(res):,} candidate-days across {res['trade_date'].nunique():,} sessions")

    summaries = []

    def block(key, title, order_col, ascending):
        print("\n" + "=" * 96)
        print(title)
        print("=" * 96)
        r = res.copy()
        r["alt_rank"] = r.groupby("trade_date")[order_col].rank(ascending=ascending, method="first")
        r["bucket"] = np.where(r["alt_rank"] <= 2, "top 2", np.where(r["alt_rank"] <= 5, "rank 3-5", "rank 6-12"))
        agg = r.groupby("bucket").agg(
            n=("ret_5", "size"),
            **{f"ret_{h}_mean": (f"ret_{h}", "mean") for h in HORIZONS},
            **{f"win_{h}": (f"ret_{h}", lambda s: 100 * (s > 0).mean()) for h in HORIZONS},
            sl_hit_10=("sl_hit_10", lambda s: 100 * s.mean()),
        ).round(2)
        agg = agg.reindex(["top 2", "rank 3-5", "rank 6-12"])
        print(agg.to_string())
        summaries.append(agg.reset_index().assign(ordered_by=key))

    block("score", "A. ORDERED BY SCORE -- the ordering the engine actually uses", "score", False)
    block("liquidity", "B. ORDERED BY LIQUIDITY (adtv_20) -- 'pilih yang top dan liquid'", "adtv_20", False)
    block("calmness", "C. ORDERED BY CALMNESS (lowest ATR/price)", "atr_pct", True)

    # ---- Per-window robustness check (the direct answer to "top rank could
    # still be better sometimes -- one aggregate number doesn't rule that
    # out") -- same score ordering as block A, but broken down by the same
    # 6-month windows walk_forward_v3.py uses, so a period-specific fluke
    # can't hide inside one big average. ----
    print("\n" + "=" * 96)
    print("D. PER-WINDOW CHECK -- does 'top 2 underperforms rank 6-12' hold consistently,")
    print("   or is it specific to some periods? (score ordering, same buckets as A)")
    print("=" * 96)
    rw = res.copy()
    rw["alt_rank"] = rw.groupby("trade_date")["score"].rank(ascending=False, method="first")
    rw["bucket"] = np.where(rw["alt_rank"] <= 2, "top 2", np.where(rw["alt_rank"] <= 5, "rank 3-5", "rank 6-12"))
    per_window = (
        rw.groupby(["window", "bucket"])
        .agg(n=("ret_10", "size"), win_10=("ret_10", lambda s: 100 * (s > 0).mean()), ret_10_mean=("ret_10", "mean"))
        .round(2)
        .reset_index()
    )
    pivot = per_window.pivot(index="window", columns="bucket", values="ret_10_mean")
    for col in ["top 2", "rank 3-5", "rank 6-12"]:
        if col not in pivot.columns:
            pivot[col] = np.nan
    pivot["top2_minus_rank6_12"] = pivot["top 2"] - pivot["rank 6-12"]
    pivot = pivot[["top 2", "rank 3-5", "rank 6-12", "top2_minus_rank6_12"]].sort_index()
    print(pivot.to_string())
    windows_with_data = pivot.dropna(subset=["top2_minus_rank6_12"])
    windows_top2_worse = (windows_with_data["top2_minus_rank6_12"] < 0).sum()
    print(f"\nWindows where top-2 underperformed rank 6-12 (10-session return): "
          f"{windows_top2_worse} / {len(windows_with_data)}")
    print("If that's most/all windows: the inversion is real and consistent -- worth")
    print("designing a fix (diversify across ranks, or find why the gate's extremes")
    print("underperform its middle). If it's a minority of windows: the 2026-08-04")
    print("aggregate was itself a period-specific read, same failure mode as the")
    print("hysteresis-band episode -- do not change the live rule off it.")

    print("\n" + "=" * 96)
    print("READ THIS AS")
    print("=" * 96)
    print("If block A's 'top 2' row does NOT beat its 'rank 6-12' row, the score")
    print("does not discriminate WITHIN the qualifying set. The gate would still")
    print("be doing the work, but the 99-vs-97 ordering would be noise -- and the")
    print("honest responses are (1) stop displaying it as precision, and (2) spread")
    print("entries across the set instead of concentrating in the top 2.")
    print("If B or C separates more cleanly than A, that is the better tie-break.")
    print("Block D is what decides whether A's finding is a real, actionable pattern")
    print("or a single-sample artifact -- read it before acting on A at all.")
    print("\nOne diagnostic is not a mandate: anything adopted from here still has")
    print("to clear walk_forward_v3.py before it goes anywhere near a live run.")

    # Small aggregates are what get published/read afterwards; the raw
    # candidate-day table stays a build artifact (it can run to tens of
    # thousands of rows and nothing downstream needs that detail).
    pd.concat(summaries, ignore_index=True).to_csv("diagnose_score_power_summary.csv", index=False)
    pivot.reset_index().to_csv("diagnose_score_power_by_window.csv", index=False)
    res.to_csv("diagnose_score_power_raw.csv", index=False)
    print("\n[OK] Saved diagnose_score_power_summary.csv + diagnose_score_power_by_window.csv + _raw.csv")


if __name__ == "__main__":
    main()
