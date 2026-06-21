"""Evidence run: walk-forward form backtest on 2014/2018/2022, applying the
go/no-go gate. Prints the per-(variant,lam) OOS match Brier table and the
across-WC averages. Sets nothing automatically — the operator reads the table
and updates config.FORM_LAMBDA/FORM_VARIANT only if a lam>0 beats lam=0 on ALL
three WCs (see spec section 7)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.backtester import run_form_backtest_and_save

df, out_path = run_form_backtest_and_save()
print(f"Wrote {out_path}")
# Per-year table
pivot = df.pivot_table(index=["variant", "lam"], columns="year", values="mean_brier")
pivot["avg"] = pivot.mean(axis=1)
print(pivot.to_string())

# Go/no-go: a candidate must beat its variant's lam=0 baseline on EVERY year.
print("\n=== go/no-go (must beat lam=0 on all three WCs) ===")
for variant in df["variant"].unique():
    sub = df[df["variant"] == variant]
    base = sub[sub["lam"] == 0.0].set_index("year")["mean_brier"]
    for lam in sorted(sub["lam"].unique()):
        if lam == 0.0:
            continue
        cand = sub[sub["lam"] == lam].set_index("year")["mean_brier"]
        beats_all = bool((cand < base).all())
        avg_impr = float((base - cand).mean())
        print(f"{variant} lam={lam}: beats_all={beats_all} avg_brier_improvement={avg_impr:+.4f}")
