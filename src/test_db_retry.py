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

# ---- insert_idempotent: transient error -> check -> retry only if not landed ----
import httpx

from db_retry import insert_idempotent


class _Res:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    """Minimal supabase-py stand-in. `landed` = the server stored the row even
    though the client saw an error (the dangerous case for a blind retry)."""

    def __init__(self, errors, landed):
        self.errors, self.landed, self.rows, self.mode = list(errors), landed, [], None

    def table(self, name):
        self.mode = None
        return self

    def insert(self, row):
        self.mode, self._row = "insert", row
        return self

    def select(self, col):
        self.mode = "select"
        return self

    def eq(self, col, val):
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self.mode == "select":
            return _Res(list(self.rows))
        if self.errors:
            err = self.errors.pop(0)
            if self.landed:
                self.rows.append(self._row)
            raise err
        self.rows.append(self._row)
        return _Res([self._row])


fake = _FakeTable([httpx.ReadError("Broken pipe")], landed=False)
insert_idempotent(fake, "t", {"a": 1}, key={"a": 1}, base_delay=0.01)
assert fake.rows == [{"a": 1}], fake.rows
print("[PASS] insert_idempotent retries after a transient error when nothing landed")

fake = _FakeTable([httpx.ReadError("Broken pipe")], landed=True)
insert_idempotent(fake, "t", {"a": 1}, key={"a": 1}, base_delay=0.01)
assert fake.rows == [{"a": 1}], f"duplicate row written: {fake.rows}"
print("[PASS] insert_idempotent does not duplicate a row that already landed")

fake = _FakeTable([ValueError("bad request")], landed=False)
try:
    insert_idempotent(fake, "t", {"a": 1}, key={"a": 1}, base_delay=0.01)
    raise AssertionError("non-transient error must propagate")
except ValueError:
    assert fake.rows == []
    print("[PASS] insert_idempotent does not retry a non-transient error")

fake = _FakeTable([httpx.ReadError("x")] * 3, landed=False)
try:
    insert_idempotent(fake, "t", {"a": 1}, key={"a": 1}, attempts=3, base_delay=0.01)
    raise AssertionError("expected ReadError after exhausting attempts")
except httpx.ReadError:
    print("[PASS] insert_idempotent re-raises after exhausting attempts")

# ---- plain-Indonesian alert + daily summary (no tracebacks, real values only) ----
import paper_common as pc

assert pc.plain_failure_reason(httpx.ReadError("Broken pipe")) == "koneksi ke database putus"
assert pc.plain_failure_reason(KeyError("x")) == "ada error di program"
sent = []
pc.notify = lambda text, markdown=True: sent.append(text)
try:
    pc.run_guarded(lambda: (_ for _ in ()).throw(httpx.ReadError("Broken pipe")), "paper_signal_scan.py")
    raise AssertionError("run_guarded must re-raise")
except httpx.ReadError:
    pass
assert len(sent) == 1 and "Traceback" not in sent[0] and "Broken pipe" not in sent[0], sent
assert sent[0].startswith("Scan harian gagal jalan: koneksi ke database putus."), sent[0]
print("[PASS] run_guarded sends one plain line, no traceback, and re-raises")

from datetime import date as _date
from paper_signal_scan import _daily_summary_lines

bear = _daily_summary_lines(
    today=_date(2026, 11, 19), regime="BEARISH", idx_close=5194.4, trend_strength=-0.088, bullish_streak=0,
    regime_ok=False, index_missing=False, open_rows=[], queued=[], exits=[], equity=100_000_000.0,
    profit_pct=0.0, confirm_days=3, trend_min=0.01)
assert bear[0] == "Scan 19 Nov selesai."
assert "Pasar BEARISH (IHSG 5.194, 8,8% di bawah rata-rata 50 hari)." in bear
assert "Posisi terbuka: 0." in bear
assert "Tidak ada beli hari ini, itu normal selama pasar belum pulih." in bear
print("[PASS] daily summary, bearish day with no positions")

busy = _daily_summary_lines(
    today=_date(2026, 11, 19), regime="BULLISH", idx_close=7000.0, trend_strength=0.02, bullish_streak=4,
    regime_ok=True, index_missing=False,
    open_rows=[{"stock_code": "BBCA", "avg_price": 9000, "remaining_lots": 5}],
    queued=[("TLKM", 3500.0)], exits=[("ASII", 5000.0, "SL")], equity=100_000_000.0,
    profit_pct=1.5, confirm_days=3, trend_min=0.01)
txt = "\n".join(busy)
assert "- BBCA: dibeli di Rp9.000, 5 lot." in txt
assert "Jual ASII di Rp5.000: kena batas rugi (stop loss)." in txt
assert "Antre beli TLKM" in txt and "normal selama" not in txt
print("[PASS] daily summary, day with position, exit and entry")

print("\nAll insert_idempotent / plain-alert checks passed.")
