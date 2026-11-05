"""Self-check for paper_common.is_filled_closed_position() (F-003): the
holdout bar in docs/HOLDOUT_PROTOCOL.md is 60 FILLED, closed positions, not
raw status='CLOSED'. A stale PENDING order that expired unfilled also lands
in status='CLOSED' (exit_reason='UNFILLED_EXPIRED', entry_date/filled_at
both NULL, pnl=0) and must not inflate the count. VERIFIED 2026-09-13: this
exact row shape (V4_PAPER's PSAB, id=30) inflated the live count 10 -> 11
before being traced to its root cause.

No DB connection needed -- paper_common.is_filled_closed_position() is a
pure function over a plain dict.

Run: python src/test_holdout_bar_filter.py
"""
import paper_common as pc  # noqa: E402

# Real shape of V4_PAPER's PSAB row (id=30), the row that originally
# surfaced this bug -- a queued order that expired before ever filling.
UNFILLED_EXPIRY = {
    "stock_code": "PSAB", "status": "CLOSED", "exit_reason": "UNFILLED_EXPIRED",
    "entry_date": None, "filled_at": None, "total_lots": 0, "pnl": 0,
}

# A normal, real, filled-and-exited position.
FILLED_CLOSED = {
    "stock_code": "SEMA", "status": "CLOSED", "exit_reason": "TRAILING",
    "entry_date": "2026-09-14", "filled_at": "2026-09-14T09:29:05+07:00",
    "total_lots": 1767, "pnl": 41_815_282,
}

OPEN_POSITION = {
    "stock_code": "ABCD", "status": "OPEN", "exit_reason": None,
    "entry_date": "2026-09-30", "filled_at": "2026-09-30T09:15:00+07:00",
}

PENDING_ORDER = {
    "stock_code": "EFGH", "status": "PENDING", "exit_reason": None,
    "entry_date": None, "filled_at": None,
}


def test_unfilled_expiry_does_not_count():
    assert pc.is_filled_closed_position(UNFILLED_EXPIRY) is False
    print("[OK] UNFILLED_EXPIRED row (status=CLOSED, filled_at=NULL) does NOT count toward the bar")


def test_real_filled_closed_position_counts():
    assert pc.is_filled_closed_position(FILLED_CLOSED) is True
    print("[OK] a real filled-and-closed position (status=CLOSED, filled_at set) DOES count")


def test_open_and_pending_never_count():
    assert pc.is_filled_closed_position(OPEN_POSITION) is False
    assert pc.is_filled_closed_position(PENDING_ORDER) is False
    print("[OK] OPEN and PENDING rows never count toward a 'closed positions' bar regardless of filled_at")


def test_sql_filter_string_matches_the_python_rule():
    # The SQL side (paper_common.HOLDOUT_BAR_FILTER) is a string meant to be
    # pasted into a WHERE clause -- this just locks its exact wording so a
    # future edit to one side doesn't silently drift from the other without
    # a test failing.
    assert pc.HOLDOUT_BAR_FILTER == "status = 'CLOSED' and filled_at is not null"
    print("[OK] HOLDOUT_BAR_FILTER wording matches is_filled_closed_position()'s own rule")


if __name__ == "__main__":
    test_unfilled_expiry_does_not_count()
    test_real_filled_closed_position_counts()
    test_open_and_pending_never_count()
    test_sql_filter_string_matches_the_python_rule()
    print("\n[DONE] holdout-bar-filter self-check passed")
