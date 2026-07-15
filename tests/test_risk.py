import pytest

import risk


def test_is_in_cooldown_no_prior_sl():
    assert risk.is_in_cooldown("BBCA", day_idx=10, last_sl_idx={}, cooldown_days=10) is False


def test_is_in_cooldown_within_window():
    last_sl_idx = {"BBCA": 5}
    assert risk.is_in_cooldown("BBCA", day_idx=10, last_sl_idx=last_sl_idx, cooldown_days=10) is True


def test_is_in_cooldown_after_window():
    last_sl_idx = {"BBCA": 5}
    assert risk.is_in_cooldown("BBCA", day_idx=16, last_sl_idx=last_sl_idx, cooldown_days=10) is False


def test_is_in_cooldown_different_stock_unaffected():
    last_sl_idx = {"BBCA": 5}
    assert risk.is_in_cooldown("TLKM", day_idx=6, last_sl_idx=last_sl_idx, cooldown_days=10) is False


def test_min_hold_elapsed_false_before():
    assert risk.min_hold_elapsed(hold_days=1, min_hold_days=3) is False


def test_min_hold_elapsed_true_at_boundary():
    assert risk.min_hold_elapsed(hold_days=3, min_hold_days=3) is True


def test_apply_fee_buy():
    assert risk.apply_fee(1_000_000, "buy", buy_fee=0.0018, sell_fee=0.0028) == pytest.approx(1800.0)


def test_apply_fee_sell():
    assert risk.apply_fee(1_000_000, "sell", buy_fee=0.0018, sell_fee=0.0028) == pytest.approx(2800.0)


def test_apply_fee_invalid_side():
    with pytest.raises(ValueError):
        risk.apply_fee(1_000_000, "hold", buy_fee=0.0018, sell_fee=0.0028)
