"""Evaluation metrics for probabilistic predictions."""

from __future__ import annotations

import numpy as np


def brier_score(predicted_probs: np.ndarray, outcomes: np.ndarray) -> float:
    """Brier score: mean squared error of probability forecasts.

    Parameters
    ----------
    predicted_probs : Array of predicted probabilities (0 to 1)
    outcomes : Array of binary outcomes (0 or 1)

    Returns
    -------
    float in [0, 2]. Lower is better. 0 = perfect, 0.25 = random for binary.
    """
    return float(np.mean((predicted_probs - outcomes) ** 2))


def log_loss(predicted_probs: np.ndarray, outcomes: np.ndarray, eps: float = 1e-15) -> float:
    """Log loss (cross-entropy) for probabilistic predictions.

    More heavily penalizes confident wrong predictions.
    """
    p = np.clip(predicted_probs, eps, 1 - eps)
    return float(-np.mean(outcomes * np.log(p) + (1 - outcomes) * np.log(1 - p)))


def calibration_error(
    predicted_probs: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> tuple[float, list[dict]]:
    """Expected calibration error (ECE).

    Returns
    -------
    (ece, bins) where bins is a list of dicts with bin details.
    """
    bins_list = []
    bin_edges = np.linspace(0, 1, n_bins + 1)
    weighted_error = 0.0
    total = len(predicted_probs)

    for i in range(n_bins):
        mask = (predicted_probs >= bin_edges[i]) & (predicted_probs < bin_edges[i + 1])
        if i == n_bins - 1:  # Include right edge for last bin
            mask = (predicted_probs >= bin_edges[i]) & (predicted_probs <= bin_edges[i + 1])

        n = mask.sum()
        if n == 0:
            bins_list.append({
                "bin_start": bin_edges[i],
                "bin_end": bin_edges[i + 1],
                "n": 0,
                "avg_predicted": 0,
                "avg_actual": 0,
                "error": 0,
            })
            continue

        avg_pred = predicted_probs[mask].mean()
        avg_actual = outcomes[mask].mean()
        error = abs(avg_pred - avg_actual)
        weighted_error += (n / total) * error

        bins_list.append({
            "bin_start": float(bin_edges[i]),
            "bin_end": float(bin_edges[i + 1]),
            "n": int(n),
            "avg_predicted": float(avg_pred),
            "avg_actual": float(avg_actual),
            "error": float(error),
        })

    return float(weighted_error), bins_list


def multiclass_brier(
    predicted_probs: np.ndarray,
    outcome_index: int,
) -> float:
    """Brier score for a single multi-class prediction.

    Parameters
    ----------
    predicted_probs : Array of probabilities for each class (sums to 1)
    outcome_index : Index of the actual outcome class

    Returns
    -------
    float. Lower is better.
    """
    n_classes = len(predicted_probs)
    actual = np.zeros(n_classes)
    actual[outcome_index] = 1.0
    return float(np.sum((predicted_probs - actual) ** 2))


def ranked_probability_score(predicted_probs: np.ndarray, outcome_index: int) -> float:
    """Ranked Probability Score — good for ordinal outcomes (W/D/L).

    Parameters
    ----------
    predicted_probs : [P(home_win), P(draw), P(away_win)]
    outcome_index : 0, 1, or 2

    Returns
    -------
    float in [0, 1]. Lower is better.
    """
    n = len(predicted_probs)
    actual = np.zeros(n)
    actual[outcome_index] = 1.0

    cum_pred = np.cumsum(predicted_probs)
    cum_actual = np.cumsum(actual)

    return float(np.mean((cum_pred - cum_actual) ** 2))
