"""scratch_concentration_acceleration_baserate.py -- SCRATCH/RESEARCH ONLY,
READ-ONLY. Base-rate check for the "concentration acceleration" idea
(2026-08-31): YELO broke out +14.44% in one day; its Bandarmology broker-
concentration ratio (bandarmology_features.py's `concentration` column --
top1_broker_|net_lot| / sum(all_brokers_|net_lot|), the exact feature live
in DB2's bandarmology_flow_daily and driving BANDAR_SIZING_ENABLED's own
sizing multiplier in backtest_v4.py) had risen from a ~0.20-0.30 baseline to
0.50 / 0.46 / 0.42 over the 3 sessions immediately before the move.

ONE data point, found by looking backward at a stock that already won --
explicitly not evidence by itself. A council session on research posture
said: check the base rate with a cheap query BEFORE building a walk-forward
test or touching backtest_v4.py. This script is that check and nothing
else -- no backtest engine, no new strategy flag, does not import or modify
backtest_v4.py.

=====================================================================
Definition of "concentration acceleration" (mechanical, fixed BEFORE
looking at results, not tuned afterward to make the numbers work):
=====================================================================
  baseline_t = that stock's own trailing 20-trading-day MEDIAN concentration,
    window ending 3 sessions before day t (t-22..t-3 inclusive, computed as
    concentration.shift(3).rolling(20, min_periods=20).median()). Offset by
    3 so the baseline can't be contaminated by the very 3 days being tested
    as "elevated" against it. Requires the full 20-day window; early-history
    days for a stock (or a stock with real trading gaps) are excluded
    (NaN), never backfilled with a partial window.

  elevated_t = concentration_t >= baseline_t + 0.10  AND  concentration_t >= 0.35
    Both numbers modeled directly on what YELO showed (baseline ~0.20-0.30,
    spike to 0.42-0.50): +0.10 absolute is a conservative read of YELO's own
    +0.17..+0.25 rise off baseline; the 0.35 floor sits below YELO's own
    LOWEST spike day (0.42) with headroom, so a stock whose noisy baseline
    is already elevated (e.g. 0.30) can't clear "+0.10" at an unremarkable
    absolute level and still count.

  flag_t = elevated_t AND elevated_{t-1} AND elevated_{t-2} -- three
    CONSECUTIVE sessions, matching what YELO showed (elevated 3 straight
    days before the move). Deliberately does NOT require any particular
    day-over-day direction within those 3 days: YELO's own sequence was
    0.50 -> 0.46 -> 0.42 INTO the breakout day, i.e. falling, not rising --
    demanding a rising shape would already be curve-fit to a pattern the
    one real example didn't actually have.

Only the FIRST day of each per-stock flagged run counts as one "episode"
for sample-size / base-rate purposes: a stock that stays elevated 5 days
straight is one underlying event, not 5 -- counting every day separately
would inflate the apparent sample size (and significance) via near-total
overlap in the forward-return windows of adjacent days.

Universe: ADTV_MIN liquidity filter (config.py, Rp1bn/20d -- the same
threshold V3's own liquidity gate and diagnose_bandarmology_power.py's
"liquid" mode already use). Required: without it, this exact metric hits
concentration~0.5 trivially whenever only ~2 brokers are active that day
(one net buyer, one net seller of similar size) -- a thin-trading artifact,
not accumulation. Sanity-checked below: the unfiltered concentration
distribution's 90th/95th/99th percentiles all cluster right at 0.50,
confirming this is a real, common artifact, not a hypothetical concern.

"Real breakout" = forward 3-trading-day close-to-close return > +8% (the
task brief's own suggested number, in YELO's +14.44% neighborhood but a
much lower, more attainable bar). Close-to-close, not next-session-open --
same Layer-1 convention diagnose_bandarmology_power.py already uses (no
entry-price/fee model here; this is a base-rate check, not a strategy).

Base-rate comparison: flagged EPISODES' breakout rate vs. the unconditional
breakout rate on all other eligible (stock, day) rows in the same universe/
period (same liquidity filter, same 20-day-baseline-history requirement,
same forward-return-availability window) -- Fisher's exact test on the 2x2
(flagged/not x breakout/not) table (not chi-square: the flagged sample is
expected to be small, chi-square's asymptotics would be unreliable there).

Run directly: python src/scratch_concentration_acceleration_baserate.py
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from config import ADTV_MIN  # noqa: E402

BASELINE_WINDOW = 20
BASELINE_OFFSET = 3
ELEVATED_MARGIN = 0.10
ELEVATED_FLOOR = 0.35
RUN_LENGTH = 3
BREAKOUT_HORIZON = 3
BREAKOUT_THRESHOLD = 0.08
HORIZONS = (1, 3, 5, 10)
_EOD_FETCH_CONCURRENCY = 12  # same convention as bandarmology_features.load_eod_bands


def build_concentration_panel() -> pd.DataFrame:
    """Full local history, same pipeline attach_bandarmology() (backtest_v4.py)
    and diagnose_bandarmology_power.py already use to produce this exact
    `concentration` column -- no corrupt-row filter (load_raw(), not
    load_raw_clean()), matching what's actually live in production sizing
    today, not an idealized cleaned version."""
    raw = bf.load_raw()
    daily = bf.daily_stock_features(bf.per_broker_net(raw))
    return daily[["trade_date", "stock_code", "concentration"]].sort_values(
        ["stock_code", "trade_date"]).reset_index(drop=True)


def load_prices(stock_codes: list, start: str, end: str) -> pd.DataFrame:
    """trade_date/stock_code/close_price/volume from ihsg_eod (DB1), concurrent
    per-stock fetch -- same idiom as bandarmology_features.load_eod_bands (12
    workers, one stock's full history is well under PostgREST's 1000-row page
    cap) but keeping close_price (that helper drops it -- only needed high/
    low/volume for its own corrupt-row check) since forward returns need it."""
    from dotenv import load_dotenv
    load_dotenv()
    from supabase import create_client
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    def _fetch_one(code):
        # Intermittent httpx/HTTP2 ReadError under this concurrency level on this
        # Windows environment (WinError 10035) -- not specific to this script's
        # logic, a transient socket issue observed empirically on first run.
        # Retry each page a few times before giving up, same style as any
        # flaky-network guard would use; not present elsewhere in this codebase
        # to copy from (grepped bandarmology_features.py/data_fetch.py, neither
        # has one -- their fetches just haven't hit this yet at their concurrency).
        rows, offset = [], 0
        while True:
            for attempt in range(4):
                try:
                    batch = (
                        supabase.table("ihsg_eod")
                        .select("trade_date,close_price,volume")
                        .eq("stock_code", code)
                        .gte("trade_date", start).lte("trade_date", end)
                        .range(offset, offset + 999)
                        .execute()
                    )
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(0.5 * (attempt + 1))
            if not batch.data:
                break
            rows.extend({**r, "stock_code": code} for r in batch.data)
            if len(batch.data) < 1000:
                break
            offset += 1000
        return rows

    all_rows = []
    with ThreadPoolExecutor(max_workers=_EOD_FETCH_CONCURRENCY) as pool:
        for rows in pool.map(_fetch_one, stock_codes):
            all_rows.extend(rows)
    df = pd.DataFrame(all_rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df[["stock_code", "trade_date", "close_price", "volume"]]


def add_baseline_flag_and_episode(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds baseline/elevated/flag/eligible/episode_start per stock, in
    chronological per-stock order -- see module docstring for the exact
    definitions. Explicit per-group loop (not groupby().apply()) -- same
    footgun bandarmology_features.rolling_features's own comment already
    documents on this pandas version."""
    panel = panel.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    parts = []
    for _, sub in panel.groupby("stock_code", sort=False):
        sub = sub.copy()
        baseline = sub["concentration"].shift(BASELINE_OFFSET).rolling(
            BASELINE_WINDOW, min_periods=BASELINE_WINDOW).median()
        sub["baseline"] = baseline
        elevated = (sub["concentration"] >= baseline + ELEVATED_MARGIN) & (sub["concentration"] >= ELEVATED_FLOOR)
        sub["elevated"] = elevated
        flag = elevated & elevated.shift(1, fill_value=False) & elevated.shift(2, fill_value=False)
        sub["flag"] = flag
        # eligible: baseline well-defined at t, t-1 AND t-2 -- the population this
        # flag could possibly have fired on, used for the "not flagged" comparison group.
        sub["eligible"] = baseline.notna() & baseline.shift(1).notna() & baseline.shift(2).notna()
        # NOT `flag.shift(1).fillna(False)` -- shifting a bool-dtype Series inserts a
        # NaN at the boundary, which silently upcasts the whole Series to `object`
        # dtype holding Python True/False objects; applying `~` to THOSE gives -2/-1
        # (Python's bitwise int negation, since bool subclasses int), not logical
        # negation -- both nonzero, both truthy, so the "not previous day" check
        # silently no-ops (confirmed empirically: episode_start came out identical
        # to flag on the first run of this script). `shift(fill_value=False)` fills
        # the boundary directly without ever introducing NaN, staying bool dtype.
        sub["episode_start"] = flag & ~flag.shift(1, fill_value=False)
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)


def add_forward_returns(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    for h in HORIZONS:
        fwd_close = prices.groupby("stock_code")["close_price"].shift(-h)
        prices[f"fwd_ret_{h}d"] = fwd_close / prices["close_price"] - 1
    prices["adtv_20"] = prices.groupby("stock_code", group_keys=False).apply(
        lambda s: (s["close_price"] * s["volume"]).rolling(20, min_periods=20).mean(), include_groups=False)
    return prices


def main():
    print("[1/4] building concentration panel from full local Bandarmology history...")
    conc = build_concentration_panel()
    print(f"  {len(conc)} (stock,day) rows, {conc['stock_code'].nunique()} stocks, "
          f"{conc['trade_date'].min()} .. {conc['trade_date'].max()}")
    print("  unfiltered concentration distribution (sanity check, thin-trading artifact):")
    print("  " + conc["concentration"].describe(percentiles=[.5, .75, .9, .95, .99]).to_string().replace("\n", "\n  "))

    conc = add_baseline_flag_and_episode(conc)

    print("\n[2/4] fetching prices (ihsg_eod, DB1) for forward returns + ADTV filter...")
    stock_codes = sorted(conc["stock_code"].unique())
    start, end = conc["trade_date"].min().isoformat(), conc["trade_date"].max().isoformat()
    prices = load_prices(stock_codes, start, end)
    prices = add_forward_returns(prices)
    print(f"  {len(prices)} price rows fetched")

    merged = conc.merge(prices, on=["trade_date", "stock_code"], how="inner")

    print(f"\n[3/4] applying liquidity filter (adtv_20 >= {ADTV_MIN:,.0f}, config.ADTV_MIN)...")
    before = len(merged)
    liquid = merged[merged["adtv_20"] >= ADTV_MIN].copy()
    print(f"  {before} -> {len(liquid)} rows")
    print("  liquid-only concentration distribution (does the artifact persist after filtering?):")
    print("  " + liquid["concentration"].describe(percentiles=[.5, .75, .9, .95, .99]).to_string().replace("\n", "\n  "))

    fwd_col = f"fwd_ret_{BREAKOUT_HORIZON}d"
    population = liquid[liquid["eligible"] & liquid[fwd_col].notna()].copy()
    print(f"\n  eligible population (has 20d baseline history + fwd_ret_{BREAKOUT_HORIZON}d available): {len(population)} rows")

    flagged_rows = population[population["flag"]]
    flagged_episodes = population[population["flag"] & population["episode_start"]]
    unflagged = population[~population["flag"]]

    print(f"\n[4/4] results")
    print(f"  raw flagged (stock,day) rows: {len(flagged_rows)}")
    print(f"  deduped flagged EPISODES (first day of each run only): {len(flagged_episodes)}")
    print(f"  unflagged population rows: {len(unflagged)}")

    if len(flagged_episodes) > 0:
        print(f"\n  flagged episodes, by ticker/date:")
        print(flagged_episodes[["stock_code", "trade_date", "concentration", "baseline"]]
              .assign(baseline=lambda d: d["baseline"].round(3), concentration=lambda d: d["concentration"].round(3))
              .to_string(index=False))

    def breakout_stats(df, label):
        n = len(df)
        if n == 0:
            print(f"  {label}: n=0")
            return 0, 0
        hits = int((df[fwd_col] > BREAKOUT_THRESHOLD).sum())
        print(f"  {label}: n={n}, breakout(fwd_{BREAKOUT_HORIZON}d>{BREAKOUT_THRESHOLD:+.0%}) rate={hits/n:.1%} ({hits}/{n}), "
              f"mean fwd_{BREAKOUT_HORIZON}d={df[fwd_col].mean():+.2%}, median={df[fwd_col].median():+.2%}")
        return hits, n

    print(f"\n  --- primary test: episodes (deduped) vs unflagged population ---")
    hits_flag, n_flag = breakout_stats(flagged_episodes, "flagged episodes")
    hits_un, n_un = breakout_stats(unflagged, "unflagged (same universe/period)")
    hits_all, n_all = breakout_stats(population, "unconditional (all eligible rows, for context)")

    if n_flag > 0:
        table = [[hits_flag, n_flag - hits_flag], [hits_un, n_un - hits_un]]
        odds_ratio, p_value = fisher_exact(table, alternative="greater")
        print(f"\n  Fisher's exact test (one-sided, flagged episodes > unflagged): "
              f"odds_ratio={odds_ratio:.3f}, p={p_value:.4f}")
        false_positive_rate = 1 - hits_flag / n_flag
        print(f"  false-positive rate among flagged episodes (no breakout following): {false_positive_rate:.1%} "
              f"({n_flag - hits_flag}/{n_flag})")

    print(f"\n  --- all horizons, flagged episodes vs unflagged population (mean fwd return) ---")
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        pop_h = liquid[liquid["eligible"] & liquid[col].notna()]
        flag_h = pop_h[pop_h["flag"] & pop_h["episode_start"]]
        unflag_h = pop_h[~pop_h["flag"]]
        if len(flag_h) == 0:
            print(f"  {h}d: n_flagged=0")
            continue
        print(f"  {h}d: flagged episodes n={len(flag_h)} mean={flag_h[col].mean():+.2%} median={flag_h[col].median():+.2%}  |  "
              f"unflagged n={len(unflag_h)} mean={unflag_h[col].mean():+.2%} median={unflag_h[col].median():+.2%}")


if __name__ == "__main__":
    main()
