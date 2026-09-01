"""
Blind-holdout test: V4_PAPER's exact frozen live config, run ONCE over
2026-07-01..2026-08-11 -- a window no backtest/sweep/walk-forward run in
this project's history has ever touched (the walk-forward cache ends
2026-06-30; V4_PAPER itself only went live 2026-08-12). See
docs/V3_FINDINGS_LOG.md 2026-09-01 entry for the full write-up and the
pre-declared interpretation bar (declared before this script was run).

Frozen config = backtest_v4.py module defaults, with the two env-var
overrides V4_PAPER's live GitHub Actions workflows actually set
(paper_signal_scan_v4_trigger.yml / paper_monitor_v4_trigger.yml on
`main`, confirmed by reading those files directly): V4_BANDAR_SIZING=1
(already the module default) and V4_ATR_PRICE_RATIO_MAX=0.08 (module
default is 0.10). No other env var is set -- everything else rides the
module default exactly as it does in production. Printed and logged
below before any data is touched.

Single train/test split, train_end = test_start - 1 day (2026-06-30),
expanding from FETCH_START (2021-01-01) -- same methodology
walk_forward_v4.py's own build_schedule() uses for every other window in
this project's walk-forward schedule (NOT the live paper engine's own
daily-expanding retrain -- that's a disclosed, deliberate methodology
difference, see the findings-log write-up).

Not swept. Not tuned. Run once. Do not add a second call to
simulate_window with different parameters in this file -- that would
burn the one holdout this project has.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/scratch_v4_blind_holdout_2026h2.py
(or rely on a local .env -- see load_dotenv() call below)
"""
import os

os.environ["V4_BANDAR_SIZING"] = "1"
os.environ["V4_ATR_PRICE_RATIO_MAX"] = "0.08"
os.environ["V4_TEST_END"] = "2026-08-11"

from datetime import date  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import backtest_v4 as bt  # noqa: E402
from supabase import create_client  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402

print(f"[CONFIG CHECK] BANDAR_SIZING_ENABLED={bt.BANDAR_SIZING_ENABLED}  "
      f"ATR_PRICE_RATIO_MAX={bt.ATR_PRICE_RATIO_MAX}  FETCH_START={bt.FETCH_START}  "
      f"TEST_END={bt.TEST_END}  LIQ_SIZING_ENABLED={bt.LIQ_SIZING_ENABLED}  "
      f"PYRAMID_ENABLED={bt.PYRAMID_ENABLED}  MAX_POSITIONS={bt.MAX_POSITIONS}  "
      f"TREND_STRENGTH_MIN={bt.TREND_STRENGTH_MIN}  REGIME_CONFIRM_DAYS={bt.REGIME_CONFIRM_DAYS}")

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key) if url and key else None

df, idx_df = wf.load_dataset(supabase)
print(f"[DATA] df rows={len(df)}  date range {df['trade_date'].min()}..{df['trade_date'].max()}")
print(f"[DATA] idx_df rows={len(idx_df)}  date range {idx_df['trade_date'].min()}..{idx_df['trade_date'].max()}")

train_end = date(2026, 6, 30)
test_start = date(2026, 7, 1)
test_end = date(2026, 8, 11)

metrics, df_trades, df_equity, regime_by_date = bt.simulate_window(
    df, idx_df, train_end, test_start, test_end, label="HOLDOUT"
)

print("\n" + "=" * 80)
print("HOLDOUT RESULT: 2026-07-01 .. 2026-08-11 (blind, never touched before)")
print("=" * 80)
if metrics is None:
    print("ZERO TRADES fired in this window.")
    regimes_in_window = {d: r for d, r in regime_by_date.items() if test_start <= d <= test_end}
    from collections import Counter
    print("Regime day counts in window:", Counter(regimes_in_window.values()))
else:
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print("\n--- Trades ---")
    print(df_trades.to_string(index=False))
