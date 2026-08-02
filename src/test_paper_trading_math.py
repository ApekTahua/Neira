"""Dry-run self-check for the shared functions the live paper-trading
engine calls (src/paper_signal_scan.py, src/paper_monitor.py) --
compute_entry_fill, evaluate_position_exit, score_candidates
(src/backtest_v3.py) and paper_common.total_buy_fee. No Supabase
connection needed -- this is the part of the plan's dry-run step that
doesn't require the new tables to exist yet (see docs/V3_FINDINGS_LOG.md
"Live paper trading" section for why full end-to-end testing is blocked
on that).

Expected values are computed independently in this file (not by calling
back into the functions under test), against the exact formulas
documented in backtest_v3.py's compute_entry_fill/evaluate_position_exit
docstrings.

Usage: python src/test_paper_trading_math.py
"""

import os
from datetime import date

os.environ.setdefault("V3_TEST_END", "2026-07-31")

import backtest_v3 as bt  # noqa: E402
import paper_common as pc  # noqa: E402
import config as cfg  # noqa: E402

TOL = 1.0  # Rupiah tolerance for money amounts (float rounding)
PCT_TOL = 0.001


def approx(a, b, tol=TOL):
    assert abs(a - b) <= tol, f"expected {b}, got {a} (diff {a - b})"


def test_total_buy_fee():
    # Below threshold: plain percentage only.
    approx(pc.total_buy_fee(5_000_000, cfg.BUY_FEE), 5_000_000 * cfg.BUY_FEE, tol=0.01)
    # Exactly at threshold: still no surcharge (rule is "over", not "at least").
    approx(pc.total_buy_fee(10_000_000, cfg.BUY_FEE), 10_000_000 * cfg.BUY_FEE, tol=0.01)
    # Over threshold: percentage + flat Rp10,000.
    approx(pc.total_buy_fee(20_000_000, cfg.BUY_FEE), 20_000_000 * cfg.BUY_FEE + 10_000, tol=0.01)
    print("[OK] test_total_buy_fee")


def test_compute_entry_fill_basic():
    entry_price = 1000.0
    log_adtv_p90 = 22.33  # ln(5_000_000_000) -- adtv_20 below set to match, so liq_mult == 1.0
    sig = {"atr": 20.0, "tp_target": 1200.0, "score": 1.0, "adtv_20": 5_000_000_000.0, "avg_vol_20": 100_000_000.0}
    cash = 100_000_000.0
    prev_equity = 100_000_000.0

    fill = bt.compute_entry_fill(sig, entry_price, cash, prev_equity, log_adtv_p90)
    assert fill is not None

    # tp1 = entry + atr*TP1_MULT, floored at entry*1.01; sl = entry - atr*1.5, capped at entry*0.99.
    approx(fill["tp1_price"], entry_price + 20.0 * cfg.TP1_MULT, tol=0.01)
    approx(fill["sl_price"], entry_price - 20.0 * 1.5, tol=0.01)

    # ALLOC_PCT * equity (score_mult/liq_mult/trend_mult all 1.0 here: SCORE_SIZING and
    # TREND_SIZING are off by default, and adtv_20 was chosen so liq_mult == 1.0 too).
    alloc = prev_equity * bt.ALLOC_PCT
    cost_per_share = entry_price * (1 + cfg.BUY_FEE)
    expected_lots = int(alloc / cost_per_share) // bt.LOT_SIZE
    assert fill["lots"] == expected_lots, f"expected {expected_lots} lots, got {fill['lots']}"
    approx(fill["cost_basis"], fill["lots"] * bt.LOT_SIZE * cost_per_share, tol=1.0)
    assert fill["checkpoint_day"] is None  # ADAPTIVE_HOLDTIME is off by default
    approx(fill["atr_at_entry"], 20.0, tol=0.001)
    print(f"[OK] test_compute_entry_fill_basic (lots={fill['lots']}, cost_basis={fill['cost_basis']:,.0f})")


def test_compute_entry_fill_below_min_lots():
    # Tiny allocation (cash floor) should return None once it can't clear ALLOC_MIN_LOTS.
    sig = {"atr": 20.0, "tp_target": 1200.0, "score": 1.0, "adtv_20": 5_000_000_000.0, "avg_vol_20": 100_000_000.0}
    fill = bt.compute_entry_fill(sig, 1000.0, cash=50.0, prev_equity=50.0, log_adtv_p90=22.33)
    assert fill is None
    print("[OK] test_compute_entry_fill_below_min_lots")


def _base_position(**overrides):
    pos = {
        "stock_code": "TEST", "entry_date": date(2026, 7, 20), "avg_price": 1000.0,
        "tp1_price": 1030.0, "sl_price": 970.0, "total_lots": 199, "remaining_lots": 199,
        "cost_basis": 199 * bt.LOT_SIZE * 1000.0 * (1 + cfg.BUY_FEE),
        "hold_days": 5, "tp1_hit": False, "tp2_hit": False, "highest_price": 1000.0,
        "trigger": "TEST", "checkpoint_day": None, "target_price": 1200.0,
        "entry_price_original": 1000.0, "atr_at_entry": 20.0,
    }
    pos.update(overrides)
    return pos


def test_evaluate_position_exit_sl():
    pos = _base_position()
    bar = (980.0, 965.0, 985.0, 960.0)  # low breaches sl_price=970
    trade, cash_delta = bt.evaluate_position_exit(pos, bar, "BULLISH", 0.02, date(2026, 7, 27), 100_000_000.0, 80_000_000.0)
    assert trade is not None and trade["exit_reason"] == "SL"
    approx(trade["exit_price"], 970.0, tol=0.01)  # open (980) doesn't gap below sl_price, so exit at sl_price
    assert trade["lots"] == 199  # full close

    sell_qty = 199 * bt.LOT_SIZE
    gross = 970.0 * sell_qty
    fee = gross * cfg.SELL_FEE
    cost_basis_orig = 199 * bt.LOT_SIZE * 1000.0 * (1 + cfg.BUY_FEE)
    expected_pnl = (gross - fee) - cost_basis_orig
    approx(trade["pnl"], expected_pnl, tol=1.0)
    approx(trade["pnl_pct"], (970.0 / 1000.0 - 1) * 100, tol=PCT_TOL)
    approx(cash_delta, gross - fee, tol=1.0)
    assert pos["remaining_lots"] == 0
    print(f"[OK] test_evaluate_position_exit_sl (pnl={trade['pnl']:,.0f})")


def test_evaluate_position_exit_tp1_and_pyramid():
    pos = _base_position()
    cost_basis_orig = pos["cost_basis"]
    cash = 80_000_000.0
    prev_equity = 100_000_000.0
    bar = (1000.0, 1035.0, 1040.0, 995.0)  # high clears tp1_price=1030, low stays above sl_price
    trade, cash_delta = bt.evaluate_position_exit(pos, bar, "BULLISH", 0.02, date(2026, 7, 27), prev_equity, cash)

    assert trade is not None and trade["exit_reason"] == "TP1"
    expected_sell_lots = max(1, int(199 * cfg.TP1_PCT))
    assert trade["lots"] == expected_sell_lots
    approx(trade["exit_price"], 1030.0, tol=0.01)  # open (1000) doesn't gap above tp1_price
    approx(trade["pnl_pct"], (1030.0 / 1000.0 - 1) * 100, tol=PCT_TOL)

    sell_cost_basis = cost_basis_orig * (expected_sell_lots / 199)
    gross = 1030.0 * expected_sell_lots * bt.LOT_SIZE
    fee = gross * cfg.SELL_FEE
    expected_pnl = (gross - fee) - sell_cost_basis
    approx(trade["pnl"], expected_pnl, tol=1.0)

    # Breakeven protection: sl_price snaps to the ORIGINAL avg_price (1000), not the
    # post-pyramid blended price computed below.
    assert pos["tp1_hit"] is True
    approx(pos["sl_price"], 1000.0, tol=0.001)

    # PYRAMID_ENABLED is on by default -- remaining_lots should have grown past the
    # post-sell base (199 - expected_sell_lots), not just shrunk.
    base_remaining = 199 - expected_sell_lots
    assert pos["remaining_lots"] > base_remaining, (
        f"expected pyramid add-on to grow the position past {base_remaining}, got {pos['remaining_lots']}"
    )
    # cash_delta must be negative overall: the small TP1 sell proceeds are dwarfed by the
    # fresh-cash pyramid buy-in (PYRAMID_ADD_PCT=20% of a Rp100M equity vs. a ~Rp2M sell).
    assert cash_delta < 0, f"expected net cash outflow from the pyramid add-on, got {cash_delta:+,.0f}"
    print(f"[OK] test_evaluate_position_exit_tp1_and_pyramid (pnl={trade['pnl']:,.0f}, "
          f"remaining_lots {199}->{expected_sell_lots}(sold)->{pos['remaining_lots']}(after pyramid), "
          f"cash_delta={cash_delta:+,.0f})")


def test_evaluate_position_exit_trailing():
    pos = _base_position(tp1_hit=True, sl_price=1000.0, highest_price=1100.0, avg_price=1015.0,
                          total_lots=373, remaining_lots=373,
                          cost_basis=373 * bt.LOT_SIZE * 1015.0 * (1 + cfg.BUY_FEE))
    bar = (1050.0, 1010.0, 1060.0, 1005.0)  # low stays above sl_price(1000); close breaches trailing stop
    trade, cash_delta = bt.evaluate_position_exit(pos, bar, "BULLISH", 0.02, date(2026, 7, 28), 100_000_000.0, 20_000_000.0)

    trailing_stop = 1100.0 * (1 - cfg.TRAILING_PCT)  # = 1012, above breakeven sl_price(1000) -- trailing dominates
    stop_eff = max(trailing_stop, pos["sl_price"])
    assert 1010.0 <= stop_eff, "test fixture assumption broken -- close_price(1010) should breach stop_eff here"
    assert trade is not None and trade["exit_reason"] == "TRAILING"
    approx(trade["exit_price"], 1010.0, tol=0.01)  # TRAILING always exits at close_price, no gap adjustment
    assert trade["lots"] == 373  # full close
    approx(trade["pnl_pct"], (1010.0 / 1015.0 - 1) * 100, tol=PCT_TOL)
    assert pos["remaining_lots"] == 0
    print(f"[OK] test_evaluate_position_exit_trailing (pnl={trade['pnl']:,.0f})")


def test_evaluate_position_exit_no_trigger():
    pos = _base_position()
    bar = (1000.0, 1005.0, 1010.0, 995.0)  # nowhere near sl_price(970) or tp1_price(1030)
    trade, cash_delta = bt.evaluate_position_exit(pos, bar, "BULLISH", 0.02, date(2026, 7, 27), 100_000_000.0, 80_000_000.0)
    assert trade is None
    assert cash_delta == 0.0
    assert pos["remaining_lots"] == 199  # untouched
    print("[OK] test_evaluate_position_exit_no_trigger")


def test_compute_drawdown_and_cvar():
    # Day 1: no history yet -- today IS the peak, drawdown 0, no CVaR (need 20+ returns).
    dd, cvar = pc.compute_drawdown_and_cvar([], 100_000_000.0)
    approx(dd, 0.0, tol=PCT_TOL)
    assert cvar is None

    # A real drawdown below a prior peak, still not enough history for CVaR.
    dd, cvar = pc.compute_drawdown_and_cvar([100.0, 110.0, 105.0], 95.0)
    approx(dd, (95.0 - 110.0) / 110.0 * 100, tol=PCT_TOL)  # peak was 110, not today or 100
    assert cvar is None

    # 20 daily returns: one -20% day, nineteen +1% days. At the 5% worst-day cutoff
    # (round(20*0.05)=1), CVaR should equal exactly that one bad day's return.
    returns = [-0.20] + [0.01] * 19
    series = [100.0]
    for r in returns:
        series.append(series[-1] * (1 + r))
    dd, cvar = pc.compute_drawdown_and_cvar(series[:-1], series[-1])
    approx(cvar, -20.0, tol=PCT_TOL)
    print(f"[OK] test_compute_drawdown_and_cvar (dd={dd:.2f}%, cvar_95={cvar:.2f}%)")


def test_score_candidates():
    import pandas as pd
    day_slice = pd.DataFrame([
        # Qualifies, highest score.
        {"stock_code": "AAA", "adtv_20": 5e9, "weekly_ma_spread": 10.0, "sector_rs_momentum": 0.05,
         "atr_14": 20.0, "close_price": 1000.0, "avg_vol_20": 1e7, "tp_target": 1200.0},
        # Qualifies, lower score.
        {"stock_code": "BBB", "adtv_20": 5e9, "weekly_ma_spread": 6.0, "sector_rs_momentum": 0.02,
         "atr_14": 15.0, "close_price": 500.0, "avg_vol_20": 1e7, "tp_target": 600.0},
        # Fails liquidity floor.
        {"stock_code": "CCC", "adtv_20": 1e8, "weekly_ma_spread": 20.0, "sector_rs_momentum": 0.10,
         "atr_14": 10.0, "close_price": 300.0, "avg_vol_20": 1e7, "tp_target": 400.0},
        # Fails weekly_ma_spread cutoff.
        {"stock_code": "DDD", "adtv_20": 5e9, "weekly_ma_spread": 1.0, "sector_rs_momentum": 0.05,
         "atr_14": 10.0, "close_price": 300.0, "avg_vol_20": 1e7, "tp_target": 400.0},
    ])
    result = bt.score_candidates(day_slice, weekly_cut=5.0, sector_cut=0.01, top_n=15)
    codes = [r["stock_code"] for r in result]
    assert codes == ["AAA", "BBB"], f"expected [AAA, BBB] ranked by score, got {codes}"
    assert result[0]["score"] > result[1]["score"]
    print(f"[OK] test_score_candidates (ranked: {codes})")


def test_score_full_universe():
    import pandas as pd
    # Same fixture as test_score_candidates: AAA/BBB pass the weekly+sector
    # gate, CCC fails liquidity, DDD has a high score (driven by
    # sector_rs_momentum alone) but fails the gate on weekly_ma_spread --
    # the key case proving label depends on BOTH cuts, not score alone.
    day_slice = pd.DataFrame([
        {"stock_code": "AAA", "adtv_20": 5e9, "weekly_ma_spread": 10.0, "sector_rs_momentum": 0.05,
         "atr_14": 20.0, "close_price": 1000.0, "avg_vol_20": 1e7, "tp_target": 1200.0},
        {"stock_code": "BBB", "adtv_20": 5e9, "weekly_ma_spread": 6.0, "sector_rs_momentum": 0.02,
         "atr_14": 15.0, "close_price": 500.0, "avg_vol_20": 1e7, "tp_target": 600.0},
        {"stock_code": "CCC", "adtv_20": 1e8, "weekly_ma_spread": 20.0, "sector_rs_momentum": 0.10,
         "atr_14": 10.0, "close_price": 300.0, "avg_vol_20": 1e7, "tp_target": 400.0},
        {"stock_code": "DDD", "adtv_20": 5e9, "weekly_ma_spread": 1.0, "sector_rs_momentum": 0.05,
         "atr_14": 10.0, "close_price": 300.0, "avg_vol_20": 1e7, "tp_target": 400.0},
    ])
    # AAA score=5.0, BBB score=1.2 (see score_candidates' own formula) -- score_p90=2.0
    # splits them across the STRONG_BUY/BUY boundary.
    result = {r["stock_code"]: r for r in bt.score_full_universe(day_slice, weekly_cut=5.0, sector_cut=0.01, score_p90=2.0, regime_ok=True)}
    assert "CCC" not in result, "illiquid ticker must never be scored, not even as WAIT/WATCH"
    assert result["AAA"]["label"] == "STRONG_BUY", result["AAA"]
    assert result["BBB"]["label"] == "BUY", result["BBB"]
    assert result["DDD"]["label"] == "WATCH", "high score from sector_rs_momentum alone must not overrule a failed weekly_ma_spread gate"
    approx(result["DDD"]["score"], 3.2, tol=PCT_TOL)
    # Percentile rank within today's 3 liquid tickers (CCC excluded): AAA
    # highest score -> 100th percentile, DDD middle -> ~66.7, BBB lowest -> ~33.3.
    approx(result["AAA"]["percentile"], 100.0, tol=PCT_TOL)
    approx(result["DDD"]["percentile"], 66.6667, tol=0.01)
    approx(result["BBB"]["percentile"], 33.3333, tol=0.01)

    # regime not confirmed bullish -- everything liquid is WAIT regardless of gate/score.
    result_wait = {r["stock_code"]: r for r in bt.score_full_universe(day_slice, weekly_cut=5.0, sector_cut=0.01, score_p90=2.0, regime_ok=False)}
    assert all(r["label"] == "WAIT" for r in result_wait.values())
    assert "CCC" not in result_wait
    print("[OK] test_score_full_universe")


def test_looks_like_unadjusted_corporate_action():
    # Real confirmed splits from ihsg_eod (2026-08-02 scan) -- must all trip.
    assert pc.looks_like_unadjusted_corporate_action(67000, 3120)   # DSSA, ~1:21
    assert pc.looks_like_unadjusted_corporate_action(10350, 1035)   # FISH, exactly 1:10
    assert pc.looks_like_unadjusted_corporate_action(16875, 1625)   # CUAN, ~1:10.4
    # A reverse split (price jumps) must also trip -- symmetric check.
    assert pc.looks_like_unadjusted_corporate_action(500, 2500)     # 1:5 reverse split
    # Ordinary trading days, including a rough one -- must NOT trip.
    assert not pc.looks_like_unadjusted_corporate_action(1000, 950)   # -5%, normal
    assert not pc.looks_like_unadjusted_corporate_action(1000, 750)   # -25%, a bad ARB day, still real
    assert not pc.looks_like_unadjusted_corporate_action(1000, 1000)  # flat
    # Missing/invalid prices -- never trip, never crash (caller has no reliable
    # prior price to compare against, but that's a different problem than a split).
    assert not pc.looks_like_unadjusted_corporate_action(None, 1000)
    assert not pc.looks_like_unadjusted_corporate_action(1000, None)
    assert not pc.looks_like_unadjusted_corporate_action(0, 1000)
    print("[OK] test_looks_like_unadjusted_corporate_action")


if __name__ == "__main__":
    test_total_buy_fee()
    test_compute_entry_fill_basic()
    test_compute_entry_fill_below_min_lots()
    test_evaluate_position_exit_sl()
    test_evaluate_position_exit_tp1_and_pyramid()
    test_evaluate_position_exit_trailing()
    test_evaluate_position_exit_no_trigger()
    test_compute_drawdown_and_cvar()
    test_score_candidates()
    test_score_full_universe()
    test_looks_like_unadjusted_corporate_action()
    print("\nAll paper-trading math checks passed.")
