"""Stage 2+3 of the NICE-pattern research pass (2026-08-27, see docs/V3_FINDINGS_LOG.md):
population scan for "long tight consolidation -> what happens next," through the
project's existing liquidity filter. NICE (IHSG, tight range 2026-06-08..2026-08-24 then
+25% ARA) is the hypothesis generator, NOT an input to the rule below -- the rule and the
pass/fail bar were written and committed to BEFORE this script's output was looked at.

STAGE 2 PRE-REGISTRATION (unchanged from the version run to produce this session's result):

RULE ("long tight consolidation"):
  - Per stock, per day: range_pct_60 = (rolling 60-trading-day max(high) - rolling
    60-trading-day min(low)) / rolling 60-trading-day median(close_price). 60 trading days
    ~= 3 calendar months, a standard base-length convention, not fit to NICE's own
    ~55-trading-day case.
  - "Tight" threshold = the 10th percentile of range_pct_60 across the WHOLE liquid
    population's history (population-relative, not a fixed % picked to match NICE's own
    ~21% range). Liquid population = the existing adtv_20 >= cfg.ADTV_MIN AND
    atr_14/close <= ATR_PRICE_RATIO_MAX filter score_candidates() already uses.
  - "Long" = the tight condition holds for >=40 CONSECUTIVE trading days (~2 months) for
    the same stock. One episode per maximal qualifying run; episode date = the LAST day of
    the run (closest point to "still inside the range" -- the honest entry day for a
    variant-(a)-style rule, not the day it already broke out).
  - Forward outcome measured at +5/+10/+20 trading days from the episode date's close.
    Benchmark = IHSG's own return over the identical calendar window.

PASS BAR (decided before running):
  - >=50 real episodes (below that: describe only, don't validate).
  - At +10 trading days: population mean AND median return each beat IHSG's own mean/
    median return over the same episode dates by >=3 percentage points, AND population
    win rate (return > 0) >= 55%. All three must hold simultaneously to call this "worth
    pursuing further" (Stage 4). Any one failing = clean rejection.

Run: .venv/Scripts/python.exe src/scratch_consolidation_scan.py (from worktree root; needs
.cache/walk_forward_data_2021-01-01_2026-06-30.pkl)."""
import sys
import pickle

sys.path.insert(0, "src")
import numpy as np
import pandas as pd
import backtest_v4 as bt
import config as cfg

WIN = 60
MIN_RUN = 40
PCTILE = 0.10

with open(".cache/walk_forward_data_2021-01-01_2026-06-30.pkl", "rb") as f:
    df, idx_df = pickle.load(f)
df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
idx_df = idx_df.sort_values("trade_date").reset_index(drop=True)
idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"])
df["trade_date"] = pd.to_datetime(df["trade_date"])

g = df.groupby("stock_code")
roll_max_high = g["high"].transform(lambda s: s.rolling(WIN, min_periods=WIN).max())
roll_min_low = g["low"].transform(lambda s: s.rolling(WIN, min_periods=WIN).min())
roll_med_close = g["close_price"].transform(lambda s: s.rolling(WIN, min_periods=WIN).median())
df["range_pct_60"] = (roll_max_high - roll_min_low) / roll_med_close

liquid_mask = (
    (df["adtv_20"] >= cfg.ADTV_MIN)
    & df["atr_14"].notna() & (df["atr_14"] > 0)
    & ((df["atr_14"] / df["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
)
threshold = df.loc[liquid_mask & df["range_pct_60"].notna(), "range_pct_60"].quantile(PCTILE)
print(f"Population liquid-universe {PCTILE:.0%}-ile range_pct_60 threshold: "
      f"{threshold:.4f} ({threshold * 100:.2f}%)")

qualifies = liquid_mask & df["range_pct_60"].notna() & (df["range_pct_60"] <= threshold)
df["qualifies"] = qualifies
df["_new_run"] = qualifies & ~(qualifies.groupby(df["stock_code"]).shift(1, fill_value=False))
df["_run_id"] = df["_new_run"].cumsum()
df.loc[~qualifies, "_run_id"] = -1

run_lengths = df[df["_run_id"] >= 0].groupby("_run_id").size()
long_run_ids = run_lengths[run_lengths >= MIN_RUN].index
episodes = df[df["_run_id"].isin(long_run_ids)].groupby("_run_id").tail(1).copy()
print(f"\nn qualifying long-tight-consolidation episodes: {len(episodes)}")
print(f"n unique stocks involved: {episodes['stock_code'].nunique()}")
print(f">=3-episode stocks: {(episodes['stock_code'].value_counts() >= 3).sum()} stocks "
      f"account for {episodes['stock_code'].value_counts()[episodes['stock_code'].value_counts() >= 3].sum()} episodes "
      f"-- not independent across tickers, same caveat the base-rate spike study logged.")

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

episodes.to_csv(".cache/consolidation_episodes.csv", index=False)
print("\nSaved to .cache/consolidation_episodes.csv")

nice = df[df["stock_code"] == "NICE"].tail(5)
print("\nNICE context (checked AFTER the rule/scan above; NICE's real 2026-08-26 breakout "
      "is outside this cache's 2026-06-30 cutoff, so it cannot appear as an episode here):")
print(nice[["trade_date", "close_price", "range_pct_60", "qualifies"]].to_string(index=False))
