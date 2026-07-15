"""risk.py — V2 backtest risk-management helpers: cooldown, min-hold, fees.

Pure functions only, no I/O. Consumed by backtest_v2.py's simulation loop.
"""


def is_in_cooldown(stock_code: str, day_idx: int, last_sl_idx: dict, cooldown_days: int) -> bool:
    """True if stock_code was stopped out (SL) within the last
    cooldown_days *trading days* (not calendar days) of day_idx.

    last_sl_idx maps stock_code -> trading-day index (into the
    simulation's trading_days list) of that stock's most recent SL exit.
    Trading-day counting matches how hold_days already counts in the
    existing backtest loop.
    """
    last_idx = last_sl_idx.get(stock_code)
    if last_idx is None:
        return False
    return (day_idx - last_idx) < cooldown_days


def min_hold_elapsed(hold_days: int, min_hold_days: int) -> bool:
    """True once a position has been held >= min_hold_days trading days."""
    return hold_days >= min_hold_days


def apply_fee(gross_amount: float, side: str, buy_fee: float, sell_fee: float) -> float:
    """Returns the fee (same currency unit as gross_amount) for a buy or
    sell. side must be 'buy' or 'sell'."""
    if side == "buy":
        return gross_amount * buy_fee
    if side == "sell":
        return gross_amount * sell_fee
    raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
