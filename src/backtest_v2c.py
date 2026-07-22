"""
backtest_v2c.py — V2c: keep the ADTV liquidity floor, HMM as exit-side risk
management only (not an entry gate).

Follow-up to backtest_v2b.py's result: ungating BOTH ADTV and HMM produced
a +611.90% headline number that turned out to be ~97% concentrated in 5
extreme sub-Rp250 microcap "pump" trades (RMKO alone = 63% of net profit)
— exactly the "obscure illiquid stock with erratic price action" pattern
Directive 1 (ADTV >= Rp1B) exists to exclude. Stripped of those 5 trades,
the remaining 185 trades still beat the benchmark by ~47% alpha, which is
the more trustworthy signal.

This variant re-instates the ADTV>=Rp1B entry filter (honoring Directive 1)
but keeps HMM state as exit-side risk management only, unchanged from v2b:
pre-TP1 BEARISH forces an immediate exit; post-TP1 BEARISH halves the
trailing-stop width. Only line changed from v2b: get_signals() now passes
adtv_min=cfg.ADTV_MIN (hmm_gate remains unpassed/False).

Single, pre-registered run: executed once against the same test window,
result recorded and not iterated on afterward. If it needs revisiting,
that is a new, separately-labeled experiment.
"""

import os
import sys
from datetime import date

import pandas as pd
from supabase import create_client

import config as cfg
import data_fetch
import hmm_model
import risk
from strategy import add_features, get_regime, get_regime_params, get_signals

BACKTEST_START = date.fromisoformat(os.environ.get("BACKTEST_START", "2021-01-01"))
BACKTEST_END = date.fromisoformat(os.environ.get("BACKTEST_END", "2026-06-30"))
INITIAL_CAPITAL = 100_000_000
LOT_SIZE = 100
SL_PCT = 0.02

BACKTEST_VERSION = os.environ.get("BACKTEST_VERSION", "v2c-dev")
BACKTEST_PUBLISH = os.environ.get("BACKTEST_PUBLISH", "false").lower() == "true"


def run_backtest_v2c():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 70)
    print("BACKTEST V2c - ADTV liquidity floor kept, HMM as exit-side risk mgmt")
    print(f"Periode: {BACKTEST_START} - {BACKTEST_END}")
    print("=" * 70)

    print("[FETCH] Downloading data ...")
    df, idx_df = data_fetch.fetch_data(supabase, BACKTEST_START, BACKTEST_END)

    print("[HMM] Loading frozen artifacts ...")
    artifacts = hmm_model.load_all_artifacts(supabase, cfg.HMM_BUCKET, cfg.HMM_VERSION)
    print(f"[HMM] Loaded {len(artifacts)} stock models (version {cfg.HMM_VERSION})")

    print("[FEATURE] Computing indicators + HMM states ...")
    stock_codes = df["stock_code"].unique()
    frames = []
    for sc in stock_codes:
        group = add_features(df[df["stock_code"] == sc].copy())
        group["hmm_state"] = hmm_model.infer_hmm_state(group, artifacts.get(sc))
        frames.append(group)
    df = pd.concat(frames, ignore_index=True)

    close_lookup = df.set_index(["stock_code", "trade_date"])["close_price"]
    hmm_lookup = df.set_index(["stock_code", "trade_date"])["hmm_state"]
    bar_lookup = {
        (r.stock_code, r.trade_date): (r.open_price, r.close_price, r.high, r.low)
        for r in df.itertuples()
    }

    def get_bar(stock_code, d):
        try:
            o, c, h, l = bar_lookup[(stock_code, d)]
        except KeyError:
            return None
        if pd.isna(c) or c <= 0:
            return None
        h = c if (pd.isna(h) or h <= 0) else max(h, c)
        l = c if (pd.isna(l) or l <= 0) else min(l, c)
        if pd.isna(o) or o <= 0 or o > h or o < l:
            o = None
        return o, c, h, l

    def get_hmm_state(stock_code, d):
        try:
            v = hmm_lookup.loc[(stock_code, d)]
            if hasattr(v, "iloc"):
                v = v.iloc[0]
            return v
        except KeyError:
            return "NO_MODEL"

    all_trading_days = sorted(
        d for d in df[df["trade_date"] >= BACKTEST_START]["trade_date"].unique()
        if d <= BACKTEST_END
    )
    split_date = hmm_model.compute_train_test_split(all_trading_days, cfg.HMM_TRAIN_SPLIT_PCT)
    trading_days = [d for d in all_trading_days if d > split_date]
    n_train_days = sum(1 for d in all_trading_days if d <= split_date)
    print(f"[SPLIT] Train: {all_trading_days[0]} .. {split_date} "
          f"({n_train_days} days, used only to freeze HMM models in train_hmm.py)")
    print(f"[SPLIT] Test (out-of-sample simulation): {trading_days[0]} .. {trading_days[-1]} "
          f"({len(trading_days)} days)\n")

    positions = []
    cash = float(INITIAL_CAPITAL)
    trades = []
    equity_curve = []
    pending_entries = []
    last_sl_idx = {}

    for day_idx, trade_date in enumerate(trading_days):
        regime = get_regime(idx_df, trade_date)
        regime_params = get_regime_params(regime)
        prev_equity = equity_curve[-1]["total"] if equity_curve else float(INITIAL_CAPITAL)

        # ---- Execute pending entries at today's OPEN ----
        for sig in pending_entries:
            if any(p["stock_code"] == sig["stock_code"] for p in positions):
                continue
            if len(positions) >= sig["max_positions"]:
                break
            if risk.is_in_cooldown(sig["stock_code"], day_idx, last_sl_idx, cfg.COOLDOWN_DAYS):
                continue

            bar = get_bar(sig["stock_code"], trade_date)
            if bar is None:
                continue
            o, c, h, l = bar
            entry_price = o if o is not None else c
            sc_price = sig["signal_close"]
            tick = 1 if sc_price < 200 else 2 if sc_price < 500 else 5 if sc_price < 2000 else 10 if sc_price < 5000 else 25
            gap_limit = max(cfg.GAP_MAX, 2 * tick / sc_price)
            if abs(entry_price / sc_price - 1) > gap_limit:
                continue

            atr_val = sig["atr"]
            if pd.isna(atr_val) or atr_val <= 0:
                tp1_price = entry_price * 1.02
                sl_price = entry_price * (1 - SL_PCT)
            else:
                tp1_price = entry_price + atr_val * cfg.TP1_MULT
                sl_price = entry_price - atr_val * sig["sl_mult"]
                tp1_price = max(tp1_price, entry_price * 1.01)
                sl_price = min(sl_price, entry_price * 0.99)

            alloc = min(prev_equity * sig["alloc_pct"], cash)
            cost_per_share = entry_price * (1 + cfg.BUY_FEE)
            lots = int(alloc / cost_per_share) // LOT_SIZE
            risk_per_share = entry_price - sl_price
            if risk_per_share > 0:
                lots_risk = int(prev_equity * cfg.RISK_PCT / risk_per_share) // LOT_SIZE
                lots = min(lots, lots_risk)
            liq_lots = int(sig["avg_vol_20"] * cfg.LIQ_CAP_PCT) // LOT_SIZE
            lots = min(lots, liq_lots)
            if lots < cfg.ALLOC_MIN_LOTS:
                continue

            quantity = lots * LOT_SIZE
            cost_basis = quantity * cost_per_share
            if cost_basis > cash:
                lots = int(cash / cost_per_share) // LOT_SIZE
                if lots < 1:
                    continue
                quantity = lots * LOT_SIZE
                cost_basis = quantity * cost_per_share

            cash -= cost_basis
            positions.append({
                "stock_code": sig["stock_code"],
                "entry_date": trade_date,
                "avg_price": entry_price,
                "tp1_price": tp1_price,
                "sl_price": sl_price,
                "total_lots": lots,
                "remaining_lots": lots,
                "quantity": quantity,
                "cost_basis": cost_basis,
                "hold_days": 0,
                "tp1_hit": False,
                "highest_price": entry_price,
                "trigger": sig["trigger"],
            })
        pending_entries = []

        # ---- Exit check ----
        remaining_positions = []
        for pos in positions:
            if pos["entry_date"] == trade_date:
                remaining_positions.append(pos)
                continue

            bar = get_bar(pos["stock_code"], trade_date)
            if bar is None:
                pos["hold_days"] += 1
                remaining_positions.append(pos)
                continue
            o, close_price, high_price, low_price = bar
            hmm_state = get_hmm_state(pos["stock_code"], trade_date)

            exit_reason = None
            exit_price = None
            sell_lots = 0
            hold_ok = risk.min_hold_elapsed(pos["hold_days"], cfg.MIN_HOLD_DAYS)

            if close_price > pos["highest_price"]:
                pos["highest_price"] = close_price

            # SL always active from day 1 — capital protection is never
            # suppressed, regardless of hold_ok, TP1 state, or HMM state.
            if not pos["tp1_hit"]:
                if low_price <= pos["sl_price"]:
                    exit_reason = "SL"
                    exit_price = o if (o is not None and o < pos["sl_price"]) else pos["sl_price"]
                    sell_lots = pos["remaining_lots"]
                elif hmm_state == "BEARISH":
                    # HMM turning bearish on a held, not-yet-TP1'd
                    # position is treated as a risk-management exit signal,
                    # not an entry-time rejection.
                    exit_reason = "HMM_BEARISH"
                    exit_price = close_price
                    sell_lots = pos["remaining_lots"]
                elif hold_ok and high_price >= pos["tp1_price"]:
                    exit_reason = "TP1"
                    exit_price = o if (o is not None and o > pos["tp1_price"]) else pos["tp1_price"]
                    sell_lots = max(1, int(pos["remaining_lots"] * cfg.TP1_PCT))
                elif pos["hold_days"] >= cfg.MAX_HOLD_DAYS - 1:
                    pnl_check = (close_price / pos["avg_price"] - 1) * 100
                    if pnl_check > 0 and regime == "BULLISH":
                        pass
                    else:
                        exit_reason = "TIME"
                        exit_price = close_price
                        sell_lots = pos["remaining_lots"]
            else:
                if low_price <= pos["sl_price"]:
                    exit_reason = "SL"
                    exit_price = o if (o is not None and o < pos["sl_price"]) else pos["sl_price"]
                    sell_lots = pos["remaining_lots"]
                elif hold_ok:
                    trailing_pct = (
                        cfg.TRAILING_PCT * cfg.HMM_BEARISH_RISK_CUT
                        if hmm_state == "BEARISH"
                        else cfg.TRAILING_PCT
                    )
                    trailing_stop = pos["highest_price"] * (1 - trailing_pct)
                    stop_eff = max(trailing_stop, pos["sl_price"])
                    if close_price <= stop_eff:
                        exit_reason = "TRAILING"
                        exit_price = close_price
                        sell_lots = pos["remaining_lots"]

            if exit_reason is not None and sell_lots > 0:
                sell_qty = sell_lots * LOT_SIZE
                sell_cost_basis = pos["cost_basis"] * (sell_lots / pos["total_lots"])
                gross_return = exit_price * sell_qty
                fee = risk.apply_fee(gross_return, "sell", cfg.BUY_FEE, cfg.SELL_FEE)
                net_return = gross_return - fee
                pnl = net_return - sell_cost_basis
                pnl_pct = (exit_price / pos["avg_price"] - 1) * 100

                cash += net_return
                pos["remaining_lots"] -= sell_lots

                if exit_reason == "SL":
                    last_sl_idx[pos["stock_code"]] = day_idx

                trades.append({
                    "stock_code": pos["stock_code"],
                    "entry_date": pos["entry_date"],
                    "exit_date": trade_date,
                    "entry_price": pos["avg_price"],
                    "exit_price": exit_price,
                    "quantity": sell_qty,
                    "lots": sell_lots,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                    "trigger": pos["trigger"],
                    "hold_days": pos["hold_days"],
                })

                if exit_reason == "TP1":
                    pos["tp1_hit"] = True
                    pos["sl_price"] = pos["avg_price"]
                    pos["cost_basis"] = pos["cost_basis"] - sell_cost_basis
                    pos["total_lots"] = pos["remaining_lots"]
                    remaining_positions.append(pos)

            if exit_reason is None or sell_lots == 0:
                pos["hold_days"] += 1
                remaining_positions.append(pos)

        positions = remaining_positions

        # ---- New signals: ADTV liquidity floor kept, HMM not an entry gate ----
        day_data = df[df["trade_date"] == trade_date].copy()
        if regime == "BULLISH":
            min_cond = cfg.BULLISH_MIN_CONDITIONS
        elif regime == "BEARISH":
            min_cond = cfg.BEARISH_MIN_CONDITIONS
        else:
            min_cond = cfg.NEUTRAL_MIN_CONDITIONS

        signals = get_signals(day_data, regime_params["confidence_min"], min_cond, adtv_min=cfg.ADTV_MIN)

        if not signals.empty:
            if regime == "BULLISH":
                alloc_pct = cfg.ALLOC_BULLISH
            elif regime == "BEARISH":
                alloc_pct = cfg.ALLOC_BEARISH
            else:
                alloc_pct = cfg.ALLOC_NEUTRAL

            for _, sig in signals.nlargest(15, "confidence").iterrows():
                pending_entries.append({
                    "stock_code": sig["stock_code"],
                    "confidence": float(sig["confidence"]),
                    "signal_close": float(sig["close_price"]),
                    "atr": sig["atr_14"],
                    "avg_vol_20": float(sig["avg_vol_20"]),
                    "sl_mult": regime_params["sl_mult"],
                    "alloc_pct": alloc_pct,
                    "max_positions": regime_params["max_positions"],
                    "trigger": sig["trigger"],
                })

        pos_market_value = 0.0
        for pos in positions:
            try:
                cp = close_lookup.loc[(pos["stock_code"], trade_date)]
                if hasattr(cp, "iloc"):
                    cp = cp.iloc[0]
                pos_market_value += (cp if not pd.isna(cp) else pos["avg_price"]) * pos["remaining_lots"] * LOT_SIZE
            except KeyError:
                pos_market_value += pos["avg_price"] * pos["remaining_lots"] * LOT_SIZE

        portfolio_value = cash + pos_market_value
        equity_curve.append({"date": trade_date, "cash": cash, "market_value": pos_market_value, "total": portfolio_value})

    # ---- Close remaining positions at end of test window ----
    final_date = trading_days[-1]
    for pos in positions:
        if pos["remaining_lots"] <= 0:
            continue
        try:
            exit_price = close_lookup.loc[(pos["stock_code"], final_date)]
            if hasattr(exit_price, "iloc"):
                exit_price = exit_price.iloc[0]
            if pd.isna(exit_price):
                exit_price = pos["avg_price"]
        except KeyError:
            exit_price = pos["avg_price"]

        exit_qty = pos["remaining_lots"] * LOT_SIZE
        exit_cost_basis = pos["cost_basis"] * (pos["remaining_lots"] / pos["total_lots"])
        gross_return = exit_price * exit_qty
        fee = risk.apply_fee(gross_return, "sell", cfg.BUY_FEE, cfg.SELL_FEE)
        net_return = gross_return - fee
        pnl = net_return - exit_cost_basis
        pnl_pct = (exit_price / pos["avg_price"] - 1) * 100
        cash += net_return

        trades.append({
            "stock_code": pos["stock_code"], "entry_date": pos["entry_date"], "exit_date": final_date,
            "entry_price": pos["avg_price"], "exit_price": exit_price, "quantity": exit_qty,
            "lots": pos["remaining_lots"], "pnl": pnl, "pnl_pct": pnl_pct,
            "exit_reason": "END", "trigger": pos["trigger"], "hold_days": pos["hold_days"],
        })

    total_trades = len(trades)
    if total_trades == 0:
        print("\n[BACKTEST V2c] No trades executed in test window.")
        return

    df_trades = pd.DataFrame(trades)
    df_equity = pd.DataFrame(equity_curve)

    winning = df_trades[df_trades["pnl"] > 0]
    losing = df_trades[df_trades["pnl"] <= 0]
    win_rate = len(winning) / total_trades * 100
    total_profit = winning["pnl"].sum() if not winning.empty else 0.0
    total_loss = losing["pnl"].sum() if not losing.empty else 0.0
    net_profit = total_profit + total_loss
    final_capital = cash
    profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float("inf")

    df_equity["peak"] = df_equity["total"].cummax()
    df_equity["drawdown"] = (df_equity["total"] - df_equity["peak"]) / df_equity["peak"] * 100
    max_drawdown = df_equity["drawdown"].min()
    total_return_pct = (final_capital / INITIAL_CAPITAL - 1) * 100

    bench = idx_df[(idx_df["trade_date"] >= trading_days[0]) & (idx_df["trade_date"] <= trading_days[-1])]
    bench_ret = (bench["close"].iloc[-1] / bench["close"].iloc[0] - 1) * 100 if len(bench) >= 2 else float("nan")

    print("\n" + "=" * 70)
    print("BACKTEST V2c RESULTS (out-of-sample test window only)")
    print("=" * 70)
    print(f"  Test window     : {trading_days[0]} .. {trading_days[-1]}")
    print(f"  Net Profit      : Rp {net_profit:,.0f} ({total_return_pct:+.2f}%)")
    print(f"  Benchmark IHSG  : {bench_ret:+.2f}% (alpha {total_return_pct - bench_ret:+.2f}%)")
    print(f"  Total Trades    : {total_trades}")
    print(f"  Win Rate        : {win_rate:.1f}%")
    print(f"  Profit Factor   : {profit_factor:.2f}")
    print(f"  Max Drawdown    : {max_drawdown:.2f}%")
    print("=" * 70)

    print("\n--- Breakdown by Exit Reason ---")
    for reason in ["TP1", "TRAILING", "SL", "HMM_BEARISH", "TIME", "END"]:
        subset = df_trades[df_trades["exit_reason"] == reason]
        if not subset.empty:
            r_win = (subset["pnl"] > 0).sum()
            r_total = len(subset)
            r_pnl = subset["pnl"].sum()
            print(f"  {reason:12s}: {r_total:3d} trades ({r_win:3d} win), total PnL Rp {r_pnl:>14,.0f}")

    # Concentration check -- v2b's headline number turned out to be ~97%
    # dependent on 5 extreme outlier trades. Report this every run so an
    # inflated-looking result can never be read at face value again.
    if net_profit > 0:
        top = df_trades.sort_values("pnl", ascending=False)
        top1_pct = top.iloc[0]["pnl"] / net_profit * 100
        top3_pct = top["pnl"].head(3).sum() / net_profit * 100
        top5_pct = top["pnl"].head(5).sum() / net_profit * 100
        print(f"\n--- Concentration ---")
        print(f"  Top-1 trade ({top.iloc[0]['stock_code']}): {top1_pct:.1f}% of net profit")
        print(f"  Top-3 trades: {top3_pct:.1f}% of net profit")
        print(f"  Top-5 trades: {top5_pct:.1f}% of net profit")

    notes = (
        f"V2c: ADTV>=Rp{cfg.ADTV_MIN:,.0f} liquidity floor kept at entry (Directive 1), "
        f"HMM state used as exit-side risk management only (immediate exit on BEARISH pre-TP1, "
        f"{cfg.HMM_BEARISH_RISK_CUT}x trailing width post-TP1) instead of an entry gate. "
        f"Single pre-registered run, not iterated on this result."
    )

    try:
        run_res = supabase.table("backtest_runs").insert({
            "version": BACKTEST_VERSION,
            "period_start": trading_days[0].isoformat(),
            "period_end": trading_days[-1].isoformat(),
            "initial_capital": INITIAL_CAPITAL,
            "final_capital": final_capital,
            "net_profit_pct": total_return_pct,
            "benchmark_pct": bench_ret,
            "alpha_pct": total_return_pct - bench_ret,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": None if profit_factor == float("inf") else profit_factor,
            "max_drawdown": max_drawdown,
            "notes": notes,
            "strategy_summary": notes,
            "is_published": BACKTEST_PUBLISH,
        }).execute()
        run_id = run_res.data[0]["id"]

        trade_rows = [{
            "run_id": run_id, "stock_code": tr["stock_code"],
            "entry_date": tr["entry_date"].isoformat(), "exit_date": tr["exit_date"].isoformat(),
            "entry_price": float(tr["entry_price"]), "exit_price": float(tr["exit_price"]),
            "lots": int(tr["lots"]), "pnl": float(tr["pnl"]), "pnl_pct": float(tr["pnl_pct"]),
            "exit_reason": tr["exit_reason"], "trigger": tr.get("trigger"),
            "hold_days": int(tr["hold_days"]) if pd.notna(tr.get("hold_days")) else None,
        } for _, tr in df_trades.iterrows()]
        equity_rows = [{
            "run_id": run_id, "date": row["date"].isoformat(), "portfolio_value": float(row["total"]),
            "drawdown_pct": float(row["drawdown"]), "regime": get_regime(idx_df, row["date"]),
        } for _, row in df_equity.iterrows()]

        for i in range(0, len(trade_rows), 500):
            supabase.table("backtest_trades").insert(trade_rows[i:i + 500]).execute()
        for i in range(0, len(equity_rows), 500):
            supabase.table("backtest_equity").insert(equity_rows[i:i + 500]).execute()

        print(f"\n[OK] Saved to Supabase: backtest_runs id={run_id} "
              f"(version={BACKTEST_VERSION}, published={BACKTEST_PUBLISH})")
    except Exception as e:
        print(f"WARNING: Failed to save to Supabase: {e}")


if __name__ == "__main__":
    run_backtest_v2c()
