"""Ensemble methods for combining model predictions."""

from __future__ import annotations

import numpy as np


def live_model_elos(
    current_elo: dict[str, float],
    snapshot: dict | None,
    teams: list[str] | None = None,
    form_bumps: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    """Per-model live tournament Elo from a TSFM snapshot + realized movement.

    live = tsfm_forecast + (actual_now − actual_at_forecast). Falls back to a
    single "Actual-Elo" model when no usable snapshot exists.

    Returns {model_name: {team: live_elo}}.
    """
    if teams is None:
        teams = sorted(current_elo.keys())
    fb = form_bumps or {}

    if not snapshot or not snapshot.get("model_tournament_elo"):
        return {"Actual-Elo": {t: current_elo.get(t, 1500.0) + fb.get(t, 0.0) for t in teams}}

    asof_elo = snapshot.get("actual_elo", {})
    out: dict[str, dict[str, float]] = {}
    for model_name, tsfm_elo in snapshot["model_tournament_elo"].items():
        out[model_name] = {
            t: tsfm_elo.get(t, current_elo.get(t, 1500.0))
               + (current_elo.get(t, 1500.0) - asof_elo.get(t, current_elo.get(t, 1500.0)))
               + fb.get(t, 0.0)
            for t in teams
        }
    return out


def equal_weight_probs(
    model_probs: list[dict[str, float]],
) -> dict[str, float]:
    """Average probability vectors from multiple models.

    Parameters
    ----------
    model_probs : List of dicts, each {"win_a": float, "draw": float, "win_b": float}
                  (or without "draw" for knockout matches)

    Returns
    -------
    Averaged probability dict.
    """
    keys = model_probs[0].keys()
    return {k: np.mean([m[k] for m in model_probs]) for k in keys}


def dynamic_weighted_probs(
    model_probs: list[dict[str, float]],
    model_scores: list[float],
) -> dict[str, float]:
    """Weighted average where weights are inverse of each model's Brier score.

    Parameters
    ----------
    model_probs : List of probability dicts from each model
    model_scores : List of Brier scores (lower = better) for each model

    Returns
    -------
    Weighted probability dict.
    """
    scores = np.array(model_scores, dtype=np.float64)
    scores = np.clip(scores, 1e-8, None)
    inv = 1.0 / scores
    weights = inv / inv.sum()

    keys = model_probs[0].keys()
    return {
        k: float(np.average([m[k] for m in model_probs], weights=weights))
        for k in keys
    }


def ensemble_tournament_probs(
    model_tournament_probs: dict[str, dict[str, dict[str, float]]],
    method: str = "equal_weight",
    model_scores: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    """Ensemble tournament-level probabilities across models.

    Parameters
    ----------
    model_tournament_probs : {model_name: {team: {stage: probability}}}
    method : "equal_weight" or "dynamic_weighted"
    model_scores : {model_name: brier_score} — required for dynamic_weighted

    Returns
    -------
    {team: {stage: ensembled_probability}}
    """
    model_names = list(model_tournament_probs.keys())
    teams = list(model_tournament_probs[model_names[0]].keys())
    stages = list(model_tournament_probs[model_names[0]][teams[0]].keys())

    result = {}
    for team in teams:
        result[team] = {}
        for stage in stages:
            probs = [model_tournament_probs[mn][team][stage] for mn in model_names]

            if method == "dynamic_weighted" and model_scores is not None:
                scores = [model_scores[mn] for mn in model_names]
                scores_arr = np.array(scores, dtype=np.float64)
                scores_arr = np.clip(scores_arr, 1e-8, None)
                inv = 1.0 / scores_arr
                weights = inv / inv.sum()
                result[team][stage] = float(np.average(probs, weights=weights))
            else:
                result[team][stage] = float(np.mean(probs))

    return result
