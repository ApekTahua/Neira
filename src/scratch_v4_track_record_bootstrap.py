"""Read-only analysis, no simulation re-run: bootstraps N-trades-until-confidence
and checks capital-deployed-in-winners-vs-losers, both from the already-computed
.cache/exit_diagnostic_trades.csv (380 legs / 258 positions, 10 windows, see
docs/V3_FINDINGS_LOG.md 2026-09-01 "exit-asymmetry diagnostic" entry for how that
CSV was produced). Does not touch backtest_v4.py, adds no flags, sweeps nothing.

Usage: python src/scratch_v4_track_record_bootstrap.py
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(20260901)
CSV = "d:/Neira/Neira/.claude/worktrees/v2-hmm-screener/.cache/exit_diagnostic_trades.csv"
N_ITER = 20000

df = pd.read_csv(CSV)
df["capital"] = df["quantity"] * df["entry_price"]

# ---- position-level rollup: a TP1 partial-sale leg and its position's later
# full-exit leg are the SAME trading decision, not two independent trades. A
# TP1 leg is positive by construction (it only fires once price already hit
# the target) and mechanically tiny (10% partial sale) -- pooling it with
# full-exit legs as if it were an independent draw biases both the win-rate
# and the bootstrap loss-probability estimate. Roll up to one row per
# position (window, stock_code, entry_date) before treating anything as "one
# trade": net_pnl = sum of pnl across that position's legs, total_capital =
# sum of quantity*entry_price across its legs (captures pyramid top-ups).
pos = df.groupby(["window", "stock_code", "entry_date"]).agg(
    net_pnl=("pnl", "sum"), total_capital=("capital", "sum"), n_legs=("pnl", "size"),
).reset_index()
pos["pnl_pct"] = pos["net_pnl"] / pos["total_capital"] * 100
pos["is_win"] = pos["net_pnl"] > 0

print("=" * 70)
print("Leg-level vs position-level win rate (n=380 legs vs n=258 positions)")
print("=" * 70)
print(f"leg-level win rate:      {(df['pnl'] > 0).mean()*100:.1f}%  (n={len(df)})")
print(f"position-level win rate: {pos['is_win'].mean()*100:.1f}%  (n={len(pos)})")
print(f"  1-leg positions (never hit TP1): n={( pos.n_legs==1).sum()}, win rate {pos.loc[pos.n_legs==1,'is_win'].mean()*100:.1f}%")
print(f"  2-leg positions (hit TP1, pyramid-eligible): n={(pos.n_legs==2).sum()}, win rate {pos.loc[pos.n_legs==2,'is_win'].mean()*100:.1f}%")

window_order = ["W1","W2","W3","W4","W5","W6","W7","W8","W9","HOLDOUT"]
wr = pos.groupby("window")["is_win"].mean().reindex(window_order) * 100
n = pos.groupby("window").size().reindex(window_order)
print("\nper-window position-level win rate:")
print(pd.DataFrame({"n_positions": n, "win_rate_pct": wr.round(1)}).to_string())

# ---------------------------------------------------------------
# Q1: bootstrap cumulative outcome for N positions, additive sum of
# per-position pnl_pct (equal-weight -- explicit simplification, see write-up).
# ---------------------------------------------------------------
returns = pos["pnl_pct"].to_numpy() / 100.0

print()
print("=" * 70)
print("Q1: bootstrap cumulative outcome by N (positions), additive sum")
print("=" * 70)
rows = []
for N in [25, 50, 100, 200, 400]:
    draws = rng.choice(returns, size=(N_ITER, N), replace=True)
    cum = draws.sum(axis=1) * 100
    rows.append({"N": N, "p5": np.percentile(cum, 5), "p25": np.percentile(cum, 25),
                 "median": np.percentile(cum, 50), "p75": np.percentile(cum, 75),
                 "p95": np.percentile(cum, 95), "p(net loss)%": (cum < 0).mean() * 100})
print(pd.DataFrame(rows).set_index("N").round(1).to_string())

print("\nfine grid, minimal N crossing 20%/10% loss-probability:")
fine_grid = list(range(5, 60, 5)) + list(range(60, 200, 10)) + list(range(200, 620, 20))
fine = []
for N in fine_grid:
    draws = rng.choice(returns, size=(N_ITER, N), replace=True)
    fine.append((N, (draws.sum(axis=1) < 0).mean()))
fine_df = pd.DataFrame(fine, columns=["N", "p_loss"])
c20 = fine_df[fine_df.p_loss < 0.20]
c10 = fine_df[fine_df.p_loss < 0.10]
print(f"  first N <20% loss prob: {c20.N.iloc[0] if len(c20) else None}")
print(f"  first N <10% loss prob: {c10.N.iloc[0] if len(c10) else None}")

for N in [8, 10, 13]:
    draws = rng.choice(returns, size=(N_ITER, N), replace=True)
    print(f"  context: at N={N} (actual holdout/live sample sizes), p(net loss) = {(draws.sum(axis=1) < 0).mean()*100:.1f}%")

# ---------------------------------------------------------------
# Q2: capital deployed in winners vs losers, position-level (not leg-level --
# leg-level double-counts the guaranteed-positive, mechanically-tiny TP1 leg).
# ---------------------------------------------------------------
print()
print("=" * 70)
print("Q2: capital deployed, position-level (net-pnl-per-position basis)")
print("=" * 70)
wc = pos.loc[pos.is_win, "total_capital"].mean()
lc = pos.loc[~pos.is_win, "total_capital"].mean()
print(f"avg capital in winning positions: Rp{wc:,.0f}")
print(f"avg capital in losing positions:  Rp{lc:,.0f}")
print(f"ratio loser/winner capital: {lc/wc:.2f}x  (>1 = losers get more capital)")

pw = pos.groupby(["window", "is_win"])["total_capital"].mean().unstack("is_win")
pw.columns = ["loss_cap", "win_cap"]
pw["ratio"] = pw["loss_cap"] / pw["win_cap"]
print("\nper-window ratio (loser capital / winner capital):")
print(pw.reindex(window_order).round(2).to_string())

if __name__ == "__main__":
    pass
