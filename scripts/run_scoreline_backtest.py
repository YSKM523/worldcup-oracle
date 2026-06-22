# scripts/run_scoreline_backtest.py
"""Evidence run: walk-forward scoreline backtest on 2014/2018/2022, applying the
go/no-go gate. Prints the per-(rho,blend) per-year NLL + exact-hit table. The
DECIDING metric is mean NLL improving on ALL THREE WCs vs the (0,0) baseline;
exact-hit% is the intuitive headline only. Sets nothing automatically — the
operator updates config.DC_RHO / GOAL_RATE_BLEND only if a candidate passes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.backtester import run_scoreline_backtest_and_save

df, out_path = run_scoreline_backtest_and_save()
print(f"Wrote {out_path}")
nll = df.pivot_table(index=["rho", "blend"], columns="year", values="mean_nll")
nll["avg"] = nll.mean(axis=1)
print("=== mean NLL (lower=better) ===")
print(nll.to_string())
hit = df.pivot_table(index=["rho", "blend"], columns="year", values="hit_rate")
print("\n=== exact-hit rate (headline only) ===")
print(hit.to_string())

base = df[(df["rho"] == 0.0) & (df["blend"] == 0.0)].set_index("year")["mean_nll"]
print("\n=== go/no-go (must beat (0,0) NLL on all three WCs) ===")
for (rho, blend), grp in df.groupby(["rho", "blend"]):
    if rho == 0.0 and blend == 0.0:
        continue
    cand = grp.set_index("year")["mean_nll"]
    beats_all = bool((cand < base).all())
    avg_impr = float((base - cand).mean())
    print(f"rho={rho} blend={blend}: beats_all={beats_all} avg_nll_improvement={avg_impr:+.4f}")
