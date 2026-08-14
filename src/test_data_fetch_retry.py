"""Dry-run self-check for data_fetch.py's _retry() -- added 2026-08-14
alongside the exception-classification/jitter fix (see _retry's own
docstring for why). No Supabase connection needed.

Usage: python src/test_data_fetch_retry.py
"""

import time

from postgrest.exceptions import APIError

from data_fetch import _retry

# ---- generic exception: retries then succeeds ----
calls = {"n": 0}


def flaky_then_ok():
    calls["n"] += 1
    if calls["n"] < 3:
        raise ConnectionError("simulated network blip")
    return "ok"


t0 = time.monotonic()
result = _retry(flaky_then_ok, attempts=4, base_delay=0.01)
elapsed = time.monotonic() - t0
assert result == "ok", f"expected 'ok', got {result!r}"
assert calls["n"] == 3, f"expected 3 calls, got {calls['n']}"
assert elapsed < 1.0, f"jittered backoff at base_delay=0.01 took too long: {elapsed:.2f}s"
print("[PASS] generic exception retries then succeeds")

# ---- generic exception: exhausts attempts, re-raises ----
try:
    _retry(lambda: (_ for _ in ()).throw(ConnectionError("always fails")), attempts=2, base_delay=0.01)
    raise AssertionError("expected ConnectionError to propagate after exhausting attempts")
except ConnectionError:
    print("[PASS] generic exception re-raises after exhausting attempts")

# ---- APIError 57014: classified, still retries, eventually re-raises ----
calls2 = {"n": 0}


def always_57014():
    calls2["n"] += 1
    raise APIError({"message": "canceling statement due to statement timeout", "code": "57014"})


try:
    _retry(always_57014, attempts=3, base_delay=0.01)
    raise AssertionError("expected APIError(57014) to propagate after exhausting attempts")
except APIError as e:
    assert e.code == "57014"
    assert calls2["n"] == 3, f"expected 3 attempts, got {calls2['n']}"
    print("[PASS] APIError 57014 classified, retried, and re-raised correctly")

print("\nAll data_fetch._retry checks passed.")
