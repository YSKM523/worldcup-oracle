"""Calibrate the Elo→probability mapping (Davidson model) by MLE.

The Elo *update* rule (data/elo.py) is untouched — ratings keep their scale.
This fits only the prediction map in prediction/match_predictor.py:

    x_a = 10^((elo_a + ha) / s),  x_b = 10^(elo_b / s)
    P(win_a), P(draw), P(win_b) ~ Davidson(x_a, x_b, nu)

Free parameters: s (logistic scale), nu (draw), ha (home-advantage Elo for
non-neutral venues). The previous hardcoded values (s=400, nu=0.28) were
overconfident at both tails and halved the real draw rate — see the
calibration tables this script prints.

Train: 2010-01-01 .. 2023-12-31.  Validation: 2024-01-01 onward.

Usage:  PYTHONPATH=. venv/bin/python scripts/calibrate_probability_map.py
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ELO_HOME_ADVANTAGE, ELO_K_DEFAULT, ELO_K_FACTORS

TRAIN_START = "2010-01-01"
VAL_START = "2024-01-01"


def _k_factor(tournament: str) -> float:
    for key, k in ELO_K_FACTORS.items():
        if key.lower() in tournament.lower():
            return k
    return ELO_K_DEFAULT


def build_samples() -> pd.DataFrame:
    """Sequential Elo replay → pre-match ratings + outcome per match."""
    matches = pd.read_parquet("data/cache/matches.parquet").sort_values("date")
    ratings: dict[str, float] = defaultdict(lambda: 1500.0)
    rows = []
    for r in matches.itertuples():
        h, a = r.home_team, r.away_team
        gd = int(r.home_score) - int(r.away_score)
        neutral = bool(r.neutral)
        # outcome: 0 = home win, 1 = draw, 2 = away win
        outcome = 0 if gd > 0 else (1 if gd == 0 else 2)
        if r.date >= pd.Timestamp(TRAIN_START):
            rows.append((r.date, ratings[h], ratings[a], neutral, outcome))
        # rating update — identical to data/elo.py
        ha = 0.0 if neutral else ELO_HOME_ADVANTAGE
        e = 1.0 / (1.0 + 10.0 ** ((ratings[a] - ratings[h] - ha) / 400.0))
        s = 1.0 if gd > 0 else (0.5 if gd == 0 else 0.0)
        g = 1.0 + math.log1p(abs(gd))
        k = _k_factor(r.tournament)
        ratings[h] += k * g * (s - e)
        ratings[a] += k * g * (e - s)
    return pd.DataFrame(rows, columns=["date", "elo_h", "elo_a", "neutral", "outcome"])


def davidson_probs(elo_h, elo_a, ha_vec, s, nu):
    """Vectorized Davidson W/D/L probabilities. Returns (n, 3) array."""
    xa = 10.0 ** ((elo_h + ha_vec) / s)
    xb = 10.0 ** (elo_a / s)
    sq = nu * np.sqrt(xa * xb)
    denom = xa + xb + sq
    return np.stack([xa / denom, sq / denom, xb / denom], axis=1)


def neg_log_likelihood(theta, df):
    log_s, log_nu, ha = theta
    s, nu = math.exp(log_s), math.exp(log_nu)
    ha_vec = np.where(df["neutral"].values, 0.0, ha)
    p = davidson_probs(df["elo_h"].values, df["elo_a"].values, ha_vec, s, nu)
    picked = p[np.arange(len(df)), df["outcome"].values]
    return -np.log(np.clip(picked, 1e-12, None)).sum()


def metrics(df, s, nu, ha):
    ha_vec = np.where(df["neutral"].values, 0.0, ha)
    p = davidson_probs(df["elo_h"].values, df["elo_a"].values, ha_vec, s, nu)
    onehot = np.eye(3)[df["outcome"].values]
    brier = ((p - onehot) ** 2).sum(axis=1).mean()
    picked = p[np.arange(len(df)), df["outcome"].values]
    logloss = -np.log(np.clip(picked, 1e-12, None)).mean()
    return brier, logloss, p


def calibration_table(df, p, label):
    print(f"\n  Calibration ({label}): P(home win) buckets")
    exp_w = p[:, 0]
    actual = (df["outcome"].values == 0).astype(float)
    is_draw = (df["outcome"].values == 1).astype(float)
    buckets = pd.cut(exp_w, np.arange(0, 1.05, 0.1))
    t = pd.DataFrame({"exp": exp_w, "act": actual, "draw": is_draw, "b": buckets})
    g = t.groupby("b", observed=True).agg(n=("act", "size"), exp=("exp", "mean"),
                                          act=("act", "mean"), draw=("draw", "mean"))
    print(g.round(3).to_string())


def main():
    df = build_samples()
    train = df[df["date"] < pd.Timestamp(VAL_START)]
    val = df[df["date"] >= pd.Timestamp(VAL_START)]
    print(f"train: {len(train)} matches ({TRAIN_START}..{VAL_START}), val: {len(val)}")

    x0 = np.array([math.log(400.0), math.log(0.28), 100.0])
    res = minimize(neg_log_likelihood, x0, args=(train,), method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-4, "maxiter": 2000})
    s, nu, ha = math.exp(res.x[0]), math.exp(res.x[1]), float(res.x[2])
    print(f"\nfitted: scale s = {s:.1f}   nu = {nu:.4f}   home_adv = {ha:.1f} Elo")
    eq_draw = nu / (2.0 + nu)
    print(f"equal-teams draw prob: {eq_draw:.1%} (was {0.28/2.28:.1%})")

    for name, part in (("TRAIN", train), ("VALIDATION", val)):
        b_old, ll_old, p_old = metrics(part, 400.0, 0.28, 100.0)
        b_new, ll_new, p_new = metrics(part, s, nu, ha)
        print(f"\n{name}:  Brier {b_old:.4f} → {b_new:.4f}   "
              f"log-loss {ll_old:.4f} → {ll_new:.4f}")
        if name == "VALIDATION":
            calibration_table(part, p_old, "old s=400 nu=0.28")
            calibration_table(part, p_new, f"new s={s:.0f} nu={nu:.2f}")

    print("\nconfig.py values:")
    print(f"BRADLEY_TERRY_SCALE = {round(s)}")
    print(f"BRADLEY_TERRY_DRAW_NU = {round(nu, 3)}")
    print(f"# fitted true-home advantage (reference for WC_HOST_HOME_ADVANTAGE_ELO): {round(ha)}")


if __name__ == "__main__":
    main()
