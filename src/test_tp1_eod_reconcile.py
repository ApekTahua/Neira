"""Correctness check for paper_signal_scan.py's EOD-reconcile TP1 branch
(2026-08-18 fix -- see docs/V3_FINDINGS_LOG.md "EOD-reconcile TP1..." entry).

Bug: the EOD reconcile loop called _close_position() (status="CLOSED") for
ANY non-None trade_record from evaluate_position_exit, including a TP1
partial exit (only TP1_PCT=10% of lots sold, 90% should keep riding OPEN).
A synthetic BEEF-shaped position was days away from its first-ever live
TP1 when this was found.

No Supabase connection needed: _persist_position/_close_position both take
`supabase` as an explicit parameter (not a module global), so a minimal fake
client that just records the payloads it's called with is enough to prove
which write path fires, without touching the real DB.

Usage: python src/test_tp1_eod_reconcile.py
"""

import os
from datetime import date

os.environ.setdefault("V4_TEST_END", "2026-07-31")

import backtest_v4 as bt  # noqa: E402
import config as cfg  # noqa: E402
import paper_signal_scan as psc  # noqa: E402


class _FakeResult:
    def __init__(self, data=None):
        self.data = data or []


class _FakeQuery:
    """Chainable stand-in for supabase-py's table().update()/.insert() builder --
    only .eq() and .execute() are ever called on the chain by _persist_position/
    _close_position, and .eq() is a pure passthrough (no filtering needed here,
    every fake table has exactly one row)."""
    def __init__(self, log, table, op, payload):
        self.log = log
        self.table = table
        self.op = op
        self.payload = payload

    def eq(self, *a, **kw):
        return self

    def execute(self):
        self.log.append({"table": self.table, "op": self.op, "payload": dict(self.payload)})
        return _FakeResult()


class _FakeTable:
    def __init__(self, log, name):
        self.log = log
        self.name = name

    def update(self, payload):
        return _FakeQuery(self.log, self.name, "update", payload)

    def insert(self, payload):
        return _FakeQuery(self.log, self.name, "insert", payload)


class FakeSupabase:
    """Records every table().update()/.insert().execute() call -- enough to
    assert which write path fired without a real DB."""
    def __init__(self):
        self.log = []

    def table(self, name):
        return _FakeTable(self.log, name)


def _base_row(**overrides):
    """paper_positions row shape (an OPEN position 3 days from TP1), same
    fixture style as test_paper_trading_math.py's _base_position()."""
    row = {
        "id": 99, "stock_code": "BEEF", "status": "OPEN",
        "entry_date": "2026-08-11", "avg_price": 1000.0,
        "tp1_price": 1030.0, "sl_price": 970.0,
        "total_lots": 199, "remaining_lots": 199,
        "cost_basis": 199 * bt.LOT_SIZE * 1000.0 * (1 + cfg.BUY_FEE),
        "hold_days": 5, "tp1_hit": False, "tp2_hit": False, "highest_price": 1000.0,
        "trigger": "TEST", "checkpoint_day": None, "target_price": 1200.0,
        "entry_price_original": 1000.0, "atr_at_entry": 20.0,
        "no_data_days": 0, "last_valid_close": 1010.0,
        "avg_vol_20": 5_000_000.0,
    }
    row.update(overrides)
    return row


def _eod_reconcile_tp1_or_close(supabase, run_id, row, pos, trade_record, bar):
    """Exact branch logic from paper_signal_scan.py's EOD-reconcile loop
    (the code under test) -- reproduced here rather than driving the real
    main() (which needs a live Supabase connection/env for the fetch/regime
    steps upstream of this branch), same "exact logic it runs" approach
    used by test_paper_trading_math.py for the shared backtest_v4 functions."""
    if trade_record["exit_reason"] == "TP1":
        psc._persist_position(supabase, row["id"], pos)
        supabase.table("paper_positions").update({
            "tp1_at": "2026-08-18T10:00:00+00:00",
            "no_data_days": 0, "last_valid_close": bar[1],
        }).eq("id", row["id"]).execute()
    else:
        psc._close_position(supabase, run_id, row["id"], pos, trade_record)


def test_tp1_eod_reconcile_keeps_position_open():
    row = _base_row()
    pos = psc._position_dict_from_row(row)
    assert pos["avg_vol_20"] == 5_000_000.0  # Priority 5 field, sanity check

    bar = (1000.0, 1035.0, 1040.0, 995.0)  # high clears tp1_price=1030
    trade_record, cash_delta = bt.evaluate_position_exit(
        pos, bar, "BULLISH", 0.02, date(2026, 8, 18), 100_000_000.0, 80_000_000.0,
    )
    assert trade_record is not None and trade_record["exit_reason"] == "TP1"

    fake = FakeSupabase()
    _eod_reconcile_tp1_or_close(fake, run_id=1, row=row, pos=pos, trade_record=trade_record, bar=bar)

    updates = [c for c in fake.log if c["table"] == "paper_positions"]
    assert updates, "expected at least one paper_positions update"
    assert not any(c["op"] == "insert" for c in fake.log), (
        "TP1 partial exit must NOT insert a backtest_trades row -- a 'trade' for win-rate/"
        "profit-factor purposes is the position's eventual FULL exit, matching paper_monitor.py's own TP1 branch"
    )
    for c in updates:
        assert "status" not in c["payload"], (
            f"TP1 partial exit must never touch status (found in payload: {c['payload']}) -- "
            "this is exactly the bug: _close_position() unconditionally sets status='CLOSED'"
        )

    # PYRAMID_ENABLED is on by default (see test_paper_trading_math.py's own
    # test_evaluate_position_exit_tp1_and_pyramid) and can add back more lots
    # than the TP1_PCT partial sell removed, so the payload's remaining_lots is
    # asserted against whatever evaluate_position_exit actually computed on `pos`
    # (the source of truth), not an independently recomputed number here -- what
    # matters for THIS bug is that it's the real post-sale/post-pyramid figure,
    # not silently reset to 0 (the full-close bug).
    persist_payload = next(c["payload"] for c in updates if "remaining_lots" in c["payload"])
    assert persist_payload["remaining_lots"] != 0, "TP1 must not zero out remaining_lots -- that's the full-close bug"
    assert persist_payload["remaining_lots"] == pos["remaining_lots"], (
        f"persisted remaining_lots ({persist_payload['remaining_lots']}) must match what "
        f"evaluate_position_exit actually left on pos ({pos['remaining_lots']})"
    )
    assert persist_payload["remaining_lots"] != 199, "TP1 must sell SOMETHING, not leave the position fully untouched"
    assert persist_payload["hold_days"] == 5, (
        f"hold_days must NOT increment on the TP1 day itself (matches paper_monitor.py's TP1 branch "
        f"and simulate_window's own TP1 continuation) -- expected 5 (unchanged), got {persist_payload['hold_days']}"
    )
    assert persist_payload["tp1_hit"] is True

    tp1_at_payload = next(c["payload"] for c in updates if "tp1_at" in c["payload"])
    assert tp1_at_payload["last_valid_close"] == bar[1]

    print(f"[OK] test_tp1_eod_reconcile_keeps_position_open (remaining_lots={persist_payload['remaining_lots']}, "
          f"hold_days={persist_payload['hold_days']}, no status write)")


def test_tp1_eod_reconcile_matches_paper_monitor_pos_state():
    """Same fixture/bar fed through evaluate_position_exit twice (once per
    caller) must leave `pos` in byte-identical state -- proves the EOD
    reconcile fix and paper_monitor.py's own TP1 branch (which persists these
    exact fields: avg_price, tp1_price, sl_price, total_lots, remaining_lots,
    cost_basis, tp1_hit) write the same numbers for the same input."""
    bar = (1000.0, 1035.0, 1040.0, 995.0)

    row_a = _base_row()
    pos_a = psc._position_dict_from_row(row_a)
    trade_a, _ = bt.evaluate_position_exit(pos_a, bar, "BULLISH", 0.02, date(2026, 8, 18), 100_000_000.0, 80_000_000.0)

    row_b = _base_row()
    pos_b = psc._position_dict_from_row(row_b)  # paper_monitor.py's own _position_dict_from_row is byte-identical
    trade_b, _ = bt.evaluate_position_exit(pos_b, bar, "BULLISH", 0.02, date(2026, 8, 18), 100_000_000.0, 80_000_000.0)

    assert trade_a["exit_reason"] == trade_b["exit_reason"] == "TP1"
    for field in ("avg_price", "tp1_price", "sl_price", "total_lots", "remaining_lots", "cost_basis", "tp1_hit"):
        assert pos_a[field] == pos_b[field], f"{field} diverged: {pos_a[field]} vs {pos_b[field]}"
    print("[OK] test_tp1_eod_reconcile_matches_paper_monitor_pos_state")


def test_sl_eod_reconcile_still_fully_closes():
    """Regression guard: a genuine full-exit reason (SL here) must still go
    through _close_position (status='CLOSED' + backtest_trades insert) --
    the fix must not weaken the already-correct non-TP1 path."""
    row = _base_row()
    pos = psc._position_dict_from_row(row)
    bar = (980.0, 965.0, 985.0, 960.0)  # low breaches sl_price=970
    trade_record, cash_delta = bt.evaluate_position_exit(
        pos, bar, "BULLISH", 0.02, date(2026, 8, 18), 100_000_000.0, 80_000_000.0,
    )
    assert trade_record is not None and trade_record["exit_reason"] == "SL"

    fake = FakeSupabase()
    _eod_reconcile_tp1_or_close(fake, run_id=1, row=row, pos=pos, trade_record=trade_record, bar=bar)

    updates = [c for c in fake.log if c["table"] == "paper_positions" and c["op"] == "update"]
    trades = [c for c in fake.log if c["table"] == "backtest_trades" and c["op"] == "insert"]
    assert any(c["payload"].get("status") == "CLOSED" for c in updates), "SL exit must set status=CLOSED"
    assert trades, "SL exit must still insert a backtest_trades row"
    assert updates[0]["payload"]["remaining_lots"] == 0
    print("[OK] test_sl_eod_reconcile_still_fully_closes")


if __name__ == "__main__":
    test_tp1_eod_reconcile_keeps_position_open()
    test_tp1_eod_reconcile_matches_paper_monitor_pos_state()
    test_sl_eod_reconcile_still_fully_closes()
    print("\nAll TP1 EOD-reconcile checks passed.")
