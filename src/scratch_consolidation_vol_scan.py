"""Round 2 of the NICE-pattern research thread (2026-08-27, see
docs/V3_FINDINGS_LOG.md for Round 1). Round 1 ("long tight consolidation" defined by a
60-trading-day trailing high-low range) was REJECTED cleanly: 257 episodes, +10d alpha
+0.18pp (bar: +3pp), win rate 46.1% (bar: 55%), null stable across an 8-point sweep. The
specific flaw identified in Round 1's own writeup: a 60-day trailing range is slow to
"forget" an old sharp move -- NICE itself never appeared as an episode because its
early-June crash kept its 60-day range measure wide for weeks after the stock had actually
already calmed down.

THIS SCRIPT IS THE ONE APPROVED FOLLOW-UP, using a volatility-COMPRESSION measure with a
much shorter lookback instead of the fixed 60-day range window. Everything else (population,
liquidity filter, "long" persistence requirement, forward-return methodology, benchmark,
pass bar) is held IDENTICAL to Round 1 on purpose, so a pass/fail here is attributable to
the one thing being changed -- the tightness metric's responsiveness -- not to several
things changed at once.

PRE-REGISTRATION (written and committed to BEFORE this script's output is looked at, and
BEFORE NICE's own numbers under this new rule are checked):

RULE ("long tight consolidation", volatility-compression version):
  - Per stock, per day: vol_pct = atr_14 / close_price. atr_14 is the project's own existing
    14-trading-day simple average of true range (see src/strategy.py lines ~104-109: true
    range = max(high-low, |high-prev_close|, |low-prev_close|), then a plain 14-day rolling
    mean) -- already computed in the cached dataset and already used by the live liquidity
    filter, not a new metric invented for this test. 14 trading days (~3 weeks) is a much
    shorter lookback than Round 1's 60-day range window, so it "forgets" an old spike in
    about a quarter of the time.
  - "Tight" threshold = the 10th percentile of vol_pct across the WHOLE liquid population's
    history (population-relative, same percentile and same liquidity filter as Round 1, for
    direct comparability). Liquid population = existing adtv_20 >= cfg.ADTV_MIN AND
    atr_14/close <= ATR_PRICE_RATIO_MAX filter score_candidates() already uses.
  - "Long" = the tight condition holds for >=40 CONSECUTIVE trading days for the same stock
    -- UNCHANGED from Round 1. This is the one deliberate constant: Round 1's flaw was in
    how fast the metric adapts, not in how long "long" should mean, so the persistence
    requirement is held fixed to isolate the single change being tested. One episode per
    maximal qualifying run; episode date = the LAST day of the run (still "inside" the
    compressed regime, the honest entry day, same convention as Round 1).
  - Forward outcome measured at +5/+10/+20 trading days from the episode date's close.
    Benchmark = IHSG's own return over the identical calendar window. Same known limitation
    as Round 1, inherited unchanged (not a new issue introduced here): the 10th-percentile
    threshold is computed once over the full sample, so it has a mild look-ahead flavor --
    accepted here only because Round 1 used the identical convention and this test's whole
    point is a controlled single-variable comparison against it.

PASS BAR (decided before running, identical to Round 1's bar for direct comparability):
  - >=50 real episodes (below that: describe only, don't validate).
  - At +10 trading days: population mean AND median return each beat IHSG's own mean/
    median return over the same episode dates by >=3 percentage points, AND population win
    rate (return > 0) >= 55%. All three must hold simultaneously to call this "worth
    pursuing further" (a Stage-4-equivalent entry-rule backtest). Any one failing = clean
    rejection, and per this session's explicit instruction, no third variant follows either
    way -- this closes the NICE-pattern research thread.

Run: .venv/Scripts/python.exe src/scratch_consolidation_vol_scan.py (from worktree root;
needs .cache/walk_forward_data_2021-01-01_2026-06-30.pkl)."""
import sys
import pickle

sys.path.insert(0, "src")
import numpy as np
import pandas as pd
import backtest_v4 as bt
import config as cfg

MIN_RUN = 40
PCTILE = 0.10

with open(".cache/walk_forward_data_2021-01-01_2026-06-30.pkl", "rb") as f:
    df, idx_df = pickle.load(f)
df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
idx_df = idx_df.sort_values("trade_date").reset_index(drop=True)
idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"])
df["trade_date"] = pd.to_datetime(df["trade_date"])

df["vol_pct"] = df["atr_14"] / df["close_price"]

liquid_mask = (
    (df["adtv_20"] >= cfg.ADTV_MIN)
    & df["atr_14"].notna() & (df["atr_14"] > 0)
    & ((df["atr_14"] / df["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
)
threshold = df.loc[liquid_mask & df["vol_pct"].notna(), "vol_pct"].quantile(PCTILE)
print(f"Population liquid-universe {PCTILE:.0%}-ile vol_pct (atr_14/close) threshold: "
      f"{threshold:.4f} ({threshold * 100:.2f}%)")

qualifies = liquid_mask & df["vol_pct"].notna() & (df["vol_pct"] <= threshold)
df["qualifies"] = qualifies
df["_new_run"] = qualifies & ~(qualifies.groupby(df["stock_code"]).shift(1, fill_value=False))
df["_run_id"] = df["_new_run"].cumsum()
df.loc[~qualifies, "_run_id"] = -1

run_lengths = df[df["_run_id"] >= 0].groupby("_run_id").size()
long_run_ids = run_lengths[run_lengths >= MIN_RUN].index
episodes = df[df["_run_id"].isin(long_run_ids)].groupby("_run_id").tail(1).copy()
print(f"\nn qualifying long-tight-consolidation episodes: {len(episodes)}")
print(f"n unique stocks involved: {episodes['stock_code'].nunique()}")
vc = episodes["stock_code"].value_counts()
print(f">=3-episode stocks: {(vc >= 3).sum()} stocks account for {vc[vc >= 3].sum()} episodes "
      f"-- not independent across tickers, same caveat Round 1 and the base-rate spike study logged.")

idx_close = idx_df.set_index("trade_date")["close"]
idx_dates = idx_df["trade_date"].values
idx_pos = {d: i for i, d in enumerate(idx_dates)}


def idx_fwd_return(trade_date, n):
    i = idx_pos.get(np.datetime64(trade_date))
    if i is None or i + n >= len(idx_dates):
        return np.nan
    return idx_close.iloc[i + n] / idx_close.iloc[i] - 1


df_sorted = df.sort_values(["stock_code", "trade_date"])
for n in (5, 10, 20):
    fwd = df_sorted.groupby("stock_code")["close_price"].transform(lambda s: s.shift(-n) / s - 1)
    df[f"fwd_{n}"] = fwd
    episodes[f"stock_fwd_{n}"] = df.loc[episodes.index, f"fwd_{n}"]
    episodes[f"idx_fwd_{n}"] = [idx_fwd_return(d, n) for d in episodes["trade_date"]]

for n in (5, 10, 20):
    sub = episodes.dropna(subset=[f"stock_fwd_{n}", f"idx_fwd_{n}"])
    sr, ir = sub[f"stock_fwd_{n}"], sub[f"idx_fwd_{n}"]
    up, down = (sr >= 0.05).mean(), (sr <= -0.05).mean()
    print(f"\n--- +{n}d (n={len(sub)}) ---")
    print(f"  stock: mean={sr.mean() * 100:.2f}% median={sr.median() * 100:.2f}% "
          f"win={100 * (sr > 0).mean():.1f}%")
    print(f"  IHSG:  mean={ir.mean() * 100:.2f}% median={ir.median() * 100:.2f}%")
    print(f"  alpha: mean={(sr.mean() - ir.mean()) * 100:.2f}pp "
          f"median={(sr.median() - ir.median()) * 100:.2f}pp")
    print(f"  up(>=+5%)={up * 100:.1f}%  flat(-5%..+5%)={100 - up * 100 - down * 100:.1f}%  "
          f"down(<=-5%)={down * 100:.1f}%")

episodes.to_csv(".cache/consolidation_vol_episodes.csv", index=False)
print("\nSaved to .cache/consolidation_vol_episodes.csv")

nice = df[df["stock_code"] == "NICE"].tail(15)
print("\nNICE context (checked AFTER the rule/scan above; NICE's real 2026-08-26 breakout "
      "is outside this cache's 2026-06-30 cutoff, so it cannot appear as an episode here "
      "either way -- this only checks whether the NEW metric reads NICE as tight as of the "
      "cache's last available date, which Round 1's 60-day-range metric did not):")
print(nice[["trade_date", "close_price", "vol_pct", "qualifies"]].to_string(index=False))
