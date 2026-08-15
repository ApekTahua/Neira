"""Dry-run self-check for db_retry.py -- the module data_fetch.py's _retry
and the live paper-trading path (paper_common.py, paper_monitor.py) now both
import from. test_data_fetch_retry.py already exercises this exact same
function object via data_fetch's re-export; this test just confirms the
shared module also works when imported directly (its own advertised import
path), independent of that re-export continuing to exist.

Usage: python src/test_db_retry.py
"""

import time

from db_retry import retry

calls = {"n": 0}


def flaky_then_ok():
    calls["n"] += 1
    if calls["n"] < 3:
        raise ConnectionError("simulated network blip")
    return "ok"


t0 = time.monotonic()
result = retry(flaky_then_ok, attempts=4, base_delay=0.01)
elapsed = time.monotonic() - t0
assert result == "ok", f"expected 'ok', got {result!r}"
assert calls["n"] == 3, f"expected 3 calls, got {calls['n']}"
assert elapsed < 1.0, f"jittered backoff at base_delay=0.01 took too long: {elapsed:.2f}s"
print("[PASS] db_retry.retry retries then succeeds")

try:
    retry(lambda: (_ for _ in ()).throw(ConnectionError("always fails")), attempts=2, base_delay=0.01)
    raise AssertionError("expected ConnectionError to propagate after exhausting attempts")
except ConnectionError:
    print("[PASS] db_retry.retry re-raises after exhausting attempts")

print("\nAll db_retry.retry checks passed.")
