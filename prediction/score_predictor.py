"""Scoreline prediction: Elo → Poisson goal grid, conditioned on Davidson probs.

The grid supplies the scoreline distribution *within* each outcome (win/draw/
loss); the outcome masses themselves come from the same Bradley-Terry-Davidson
model the rest of the pipeline uses, so P(any home-win score) == p_home exactly.
"""

from __future__ import annotations

import math

import numpy as np

from config import POISSON_AVG_GOALS
from prediction.calibration import Calibration, calibrate
from prediction.match_predictor import knockout_probabilities, match_probabilities

# Elo points of (effective) rating difference per expected goal of superiority.
# elo_diff=180 → xG split ~1.75 vs 0.75, in line with historical WC scorelines.
GOAL_DIFF_ELO_SCALE = 180.0
MAX_XG_DIFF = 2.4          # cap blowout expectation
MIN_LAMBDA = 0.2           # even huge underdogs create the odd chance
MAX_GOALS = 8              # grid covers 0..8 goals per team


def expected_goals(
    elo_a: float,
    elo_b: float,
    home_advantage: float = 0.0,
    total_goals: float = POISSON_AVG_GOALS,
) -> tuple[float, float]:
    """Split the average total goals into per-team Poisson means via Elo diff.

    Mismatches produce more total goals (blowouts), so the total scales up
    mildly with the strength gap.
    """
    diff = (elo_a + home_advantage - elo_b) / GOAL_DIFF_ELO_SCALE
    diff = max(-MAX_XG_DIFF, min(MAX_XG_DIFF, diff))
    total = total_goals + 0.3 * abs(diff)
    lam_a = max((total + diff) / 2.0, MIN_LAMBDA)
    lam_b = max((total - diff) / 2.0, MIN_LAMBDA)
    return lam_a, lam_b


def score_grid(lam_a: float, lam_b: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    """Independent-Poisson score grid, grid[i, j] = P(A scores i, B scores j)."""
    goals = np.arange(max_goals + 1)
    pa = np.exp(-lam_a) * lam_a ** goals / np.array([math.factorial(g) for g in goals])
    pb = np.exp(-lam_b) * lam_b ** goals / np.array([math.factorial(g) for g in goals])
    grid = np.outer(pa, pb)
    return grid / grid.sum()


def condition_grid(
    grid: np.ndarray,
    p_win_a: float,
    p_draw: float,
    p_win_b: float,
) -> np.ndarray:
    """Rescale the win/draw/loss blocks of the grid to the given outcome probs."""
    n = grid.shape[0]
    i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    out = grid.copy()
    for mask, target in (
        (i > j, p_win_a),
        (i == j, p_draw),
        (i < j, p_win_b),
    ):
        block = grid[mask].sum()
        if block > 0:
            out[mask] = grid[mask] * (target / block)
    return out / out.sum()


def top_scorelines(grid: np.ndarray, n: int = 5) -> list[tuple[int, int, float]]:
    """The n most likely scorelines: [(goals_a, goals_b, probability), ...]."""
    flat = [
        (i, j, float(grid[i, j]))
        for i in range(grid.shape[0])
        for j in range(grid.shape[1])
    ]
    flat.sort(key=lambda x: -x[2])
    return flat[:n]


def predict_scoreline(
    elo_a: float,
    elo_b: float,
    home_advantage: float = 0.0,
    outcome_probs: dict[str, float] | None = None,
) -> dict:
    """Full scoreline prediction for one match.

    outcome_probs : optional {"win_a", "draw", "win_b"} to condition on
        (e.g. an ensemble average); defaults to the Davidson model on the
        same Elo inputs.
    """
    if outcome_probs is None:
        outcome_probs = match_probabilities(elo_a, elo_b, home_advantage)

    lam_a, lam_b = expected_goals(elo_a, elo_b, home_advantage)
    grid = condition_grid(
        score_grid(lam_a, lam_b),
        outcome_probs["win_a"], outcome_probs["draw"], outcome_probs["win_b"],
    )
    top = top_scorelines(grid)
    return {
        "xg_a": round(lam_a, 2),
        "xg_b": round(lam_b, 2),
        "top_scores": [
            {"score": f"{a}-{b}", "p": round(p, 4)} for a, b, p in top
        ],
        "most_likely": f"{top[0][0]}-{top[0][1]}",
        "most_likely_p": round(top[0][2], 4),
    }


def ensemble_match_prediction(
    elo_pairs: list[tuple[float, float]],
    home_advantage: float = 0.0,
    knockout: bool = False,
    calib: "Calibration | None" = None,
) -> dict:
    """One match, several models: average outcome probs + a shared scoreline.

    elo_pairs : per-model (elo_home, elo_away) live ratings.

    Outcome probs are the mean of the per-model Davidson probs (kept RAW per
    model); the ensemble average is then calibrated. The scoreline grid is the
    mean of the per-model Poisson grids, conditioned on the CALIBRATED ensemble
    90-minute probs. Knockout matches additionally get a 2-way advance
    probability (draws split via ET/penalty model, calibrated per model).

    The output always includes the uncalibrated ensemble as
    p_home_raw/p_draw_raw/p_away_raw alongside the calibrated p_home/p_draw/p_away.
    """
    per_model = []
    grids = []
    lams = []
    for elo_h, elo_a in elo_pairs:
        probs = match_probabilities(elo_h, elo_a, home_advantage)   # RAW per model
        m = {
            "p_home": round(probs["win_a"], 4),
            "p_draw": round(probs["draw"], 4),
            "p_away": round(probs["win_b"], 4),
        }
        if knockout:
            adv = knockout_probabilities(elo_h, elo_a, home_advantage, calib=calib)
            m["p_adv_home"] = round(adv["win_a"], 4)
        per_model.append(m)
        lam = expected_goals(elo_h, elo_a, home_advantage)
        lams.append(lam)
        grids.append(score_grid(*lam))

    # Ensemble RAW 3-way
    p_home_raw = float(np.mean([m["p_home"] for m in per_model]))
    p_draw_raw = float(np.mean([m["p_draw"] for m in per_model]))
    p_away_raw = float(np.mean([m["p_away"] for m in per_model]))

    # Calibrate the ensemble (the object the honest match-Brier is computed on)
    cal3 = calibrate(
        {"win_a": p_home_raw, "draw": p_draw_raw, "win_b": p_away_raw}, calib
    )
    p_home, p_draw, p_away = cal3["win_a"], cal3["draw"], cal3["win_b"]

    grid = condition_grid(np.mean(grids, axis=0), p_home, p_draw, p_away)
    top = top_scorelines(grid, n=6)

    n = grid.shape[0]
    gi, gj = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    out = {
        "p_home": round(p_home, 4),
        "p_draw": round(p_draw, 4),
        "p_away": round(p_away, 4),
        "p_home_raw": round(p_home_raw, 4),
        "p_draw_raw": round(p_draw_raw, 4),
        "p_away_raw": round(p_away_raw, 4),
        "scoreline": {
            "top_scores": [
                {"score": f"{a}-{b}", "p": round(p, 4)} for a, b, p in top
            ],
            "most_likely": f"{top[0][0]}-{top[0][1]}",
            "most_likely_p": round(top[0][2], 4),
            "xg_home": round(float(np.mean([l[0] for l in lams])), 2),
            "xg_away": round(float(np.mean([l[1] for l in lams])), 2),
            "p_over25": round(float(grid[gi + gj >= 3].sum()), 4),
            "p_btts": round(float(grid[1:, 1:].sum()), 4),
        },
        "per_model": per_model,
    }
    if knockout:
        adv_home = float(np.mean([m["p_adv_home"] for m in per_model]))
        out["p_adv_home"] = round(adv_home, 4)
        out["p_adv_away"] = round(1.0 - adv_home, 4)
    return out
