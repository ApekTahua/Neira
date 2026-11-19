"""db_retry.py -- shared Supabase call retry/backoff helper.

Extracted from data_fetch.py (2026-08-14 origin -- see the docstring below,
kept verbatim) so both the backtest/research data-loading path
(data_fetch.py) and the live paper-trading path (paper_common.py,
paper_monitor.py, paper_signal_scan.py) share one retry implementation
instead of two copies that would silently drift apart the next time one
gets tuned -- exactly what this project's CLAUDE.md cautions against.
data_fetch.py now imports `retry` from here rather than defining its own;
this is a relocation, its behavior is unchanged (see
test_data_fetch_retry.py, which still exercises this same function object
via that import).

Lives as its own tiny module (not inside data_fetch.py, which is
conceptually a backtest/research data-loading module) so paper_common.py --
the live trading path -- doesn't have to carry an odd dependency on it.
"""

import random
import time

import httpx
from postgrest.exceptions import APIError


# Transient transport failures only -- a dropped/stale connection, not a
# server-side rejection. 2026-11-18 10:37 UTC (and 2026-11-12 13:39 UTC):
# paper_signal_scan.py died with httpx.ReadError ([Errno 32] Broken pipe) in
# data_fetch._fetch_chunk, i.e. inside retry() below, after all 4 attempts
# (~18s of total backoff) hit the same dead connection. The retry existed but
# gave up too fast for a Supabase/PostgREST hiccup that lasts longer.

TRANSIENT_HTTPX_ERRORS = (
    httpx.ReadError, httpx.WriteError, httpx.ConnectError, httpx.TimeoutException,
    httpx.RemoteProtocolError, httpx.CloseError,
)


# Network errors get more, longer-spaced attempts than other errors (2s, 4s, 8s,
# 16s, 30s + jitter = ~60s total): a dropped connection usually recovers within a
# minute, while a deterministic error (bad query, 57014) gains nothing from waiting.
TRANSIENT_ATTEMPTS = 6
TRANSIENT_MAX_DELAY = 30.0


def retry(fn, attempts=4, base_delay=2.0):
    """2026-08-14: found in production that a Postgres statement timeout
    (57014, e.g. ihsg_eod missing an index) crashed this exact retry loop --
    all 12 concurrent workers hit the same deterministic failure and retried
    on the identical fixed schedule (2s/4s/6s), a thundering-herd pattern
    that just re-triggers the same DB load instead of relieving it. Jitter
    spreads the retries out; classifying 57014 specifically (vs a generic
    network blip) makes the next incident's log immediately diagnosable
    instead of needing a full GitHub Actions log pull to identify, like this
    one did."""
    transient = 0  # network errors seen so far
    other = 0      # every other kind of error seen so far
    while True:
        try:
            return fn()
        except TRANSIENT_HTTPX_ERRORS:
            transient += 1
            if transient >= TRANSIENT_ATTEMPTS:
                raise
            delay = min(TRANSIENT_MAX_DELAY, base_delay * (2 ** (transient - 1)))
            print(f"  [RETRY] network error (attempt {transient}/{TRANSIENT_ATTEMPTS}), waiting ~{delay:.0f}s.")
            time.sleep(delay + random.uniform(0, base_delay))
        except APIError as e:
            other += 1
            if other >= attempts:
                raise
            if e.code == "57014":
                print(f"  [RETRY] Postgres statement timeout (57014) on attempt {other}/{attempts} -- "
                      f"likely a missing/inadequate index, not a transient blip.")
            time.sleep(base_delay * other + random.uniform(0, base_delay))
        except Exception:
            other += 1
            if other >= attempts:
                raise
            time.sleep(base_delay * other + random.uniform(0, base_delay))


def insert_idempotent(supabase, table, row, key, attempts=3, base_delay=2.0):
    """INSERT `row` into `table`, safe to retry after a transient network error.

    The tables used here have no unique constraint to upsert on, so a blind
    retry could write the same row twice if the first attempt succeeded and
    only the response was lost. Instead: on a transient httpx error, first
    SELECT for a row matching `key` (a dict of column -> value that identifies
    this exact row); if it exists, the first attempt landed and we are done,
    otherwise insert again. Non-transient errors (constraint, auth, bad
    request) are raised immediately, never retried."""
    for i in range(attempts):
        try:
            return supabase.table(table).insert(row).execute()
        except TRANSIENT_HTTPX_ERRORS:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i) + random.uniform(0, base_delay))

            def _exists():
                q = supabase.table(table).select(next(iter(key)))
                for col, val in key.items():
                    q = q.eq(col, val)
                return q.limit(1).execute()

            if retry(_exists, attempts=3, base_delay=base_delay).data:
                print(f"  [RETRY] {table}: first insert had already landed -- not inserting again.")
                return None
