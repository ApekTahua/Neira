"""broker_summary_history_backfill.py -- one-off seed of DB2's
broker_summary_history table (see sql/broker_summary_history_schema.sql)
from the local Parquet archive (data/bandarmology_history/), which has the
exact same per-broker/per-side granularity broker_summary itself has.

broker_summary (DB2) only ever holds the LATEST trading day -- it can't be
backfilled FROM. The local archive can: same schema
(stock_code, broker_code, side, lot, val_rupiah, avg_price, trade_date),
one file per trading day, going back to 2020-06-02 (1489 files as of
2026-08-16), far more than the 90-day window this table keeps.

Only backfills the last 90 CALENDAR days (matching
sync_broker_summary_history()'s own prune cutoff, `interval '90 days'` on
trade_date) -- not the whole archive, this table is a bounded rolling
window by design, not a full-history store (see the schema file's own
"CORRECTION 2026-08-12" note on why a full-history version of this exact
granularity would blow the free-tier quota).

Table must already exist (sql/broker_summary_history_schema.sql applied)
before running this -- a bare INSERT against a missing table fails loudly,
which is the correct behavior (fail closed, not silently no-op).

Needs DB2 write credentials in a local .env (never committed, see .gitignore):
    SUPABASE_BROKER_URL=https://ptuvkgleurjcniznveye.supabase.co
    SUPABASE_BROKER_KEY=<service_role key>

Usage: python src/broker_summary_history_backfill.py
"""

import glob
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bandarmology_history"
BATCH_SIZE = 5000
WINDOW_DAYS = 90


def _stems_in_window(stems: list[str], window_days: int = WINDOW_DAYS) -> list[str]:
    """Pure date-filter, split out from files_in_window() so it's testable
    without touching the filesystem."""
    if not stems:
        return []
    latest = date.fromisoformat(stems[-1])
    cutoff = latest - timedelta(days=window_days)
    return [s for s in stems if date.fromisoformat(s) > cutoff]


def files_in_window() -> list[Path]:
    files = sorted(DATA_DIR.glob("*/*/*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files under {DATA_DIR}")
    by_stem = {f.stem: f for f in files}
    kept_stems = _stems_in_window(sorted(by_stem))
    return [by_stem[s] for s in kept_stems]


def main():
    load_dotenv()
    url = os.environ["SUPABASE_BROKER_URL"]
    key = os.environ["SUPABASE_BROKER_KEY"]

    files = files_in_window()
    print(f"{len(files)} trading days in the {WINDOW_DAYS}-day window "
          f"({files[0].stem} .. {files[-1].stem})")

    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    for col in ("lot", "val_rupiah"):  # parquet stores these as float64, Postgres bigint rejects "18562.0"
        df[col] = df[col].round().astype("Int64")
    df = df.where(df.notna(), None)
    records = df[["trade_date", "stock_code", "broker_code", "side", "lot", "val_rupiah", "avg_price"]].to_dict("records")

    print(f"pushing {len(records)} rows to broker_summary_history...")
    endpoint = f"{url}/rest/v1/broker_summary_history"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        resp = requests.post(endpoint, json=batch, headers=headers, timeout=60)
        if not resp.ok:
            print(f"  ERROR {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()
        print(f"  {i + len(batch)}/{len(records)}")

    print("done")


def _self_check():
    """No network/filesystem needed -- proves the date-window boundary math
    (calendar days, not trading days, matching the plpgsql prune's own
    `interval '90 days'` cutoff)."""
    stems = ["2026-01-01", "2026-05-01", "2026-05-14", "2026-08-11"]
    kept = _stems_in_window(stems, window_days=90)
    # cutoff = 2026-08-11 - 90d = 2026-05-13 (exclusive) -> only 05-14 and 08-11 survive
    assert kept == ["2026-05-14", "2026-08-11"], kept
    assert _stems_in_window([]) == []
    print("self-check passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _self_check()
    else:
        main()
