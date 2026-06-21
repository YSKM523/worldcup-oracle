"""Level 2: Convert Elo forecasts into match outcome probabilities."""

from __future__ import annotations

import math

import numpy as np

from config import (
    BRADLEY_TERRY_DRAW_NU,
    BRADLEY_TERRY_SCALE,
    HOST_TEAMS,
    KNOCKOUT_PENALTY_ADVANTAGE,
    WC_HOST_HOME_ADVANTAGE_ELO,
)
from prediction.calibration import Calibration, calibrate


def match_probabilities(
    elo_a: float,
    elo_b: float,
    home_advantage: float = 0.0,
    nu: float = BRADLEY_TERRY_DRAW_NU,
    calib: "Calibration | None" = None,
) -> dict[str, float]:
    """Bradley-Terry model with draws (Davidson 1970).

    Parameters
    ----------
    elo_a : Elo rating for team A
    elo_b : Elo rating for team B
    home_advantage : Elo bonus for team A (e.g., 80 for host nation)
    nu : Draw parameter (higher = more draws)
    calib : Optional calibration (temperature + draw bias). None = identity.

    Returns
    -------
    {"win_a": float, "draw": float, "win_b": float} summing to 1.0
    """
    exp_a = 10.0 ** ((elo_a + home_advantage) / BRADLEY_TERRY_SCALE)
    exp_b = 10.0 ** (elo_b / BRADLEY_TERRY_SCALE)

    denom = exp_a + exp_b + nu * math.sqrt(exp_a * exp_b)

    raw = {
        "win_a": exp_a / denom,
        "draw": nu * math.sqrt(exp_a * exp_b) / denom,
        "win_b": exp_b / denom,
    }
    return calibrate(raw, calib)


def knockout_probabilities(
    elo_a: float,
    elo_b: float,
    home_advantage: float = 0.0,
    nu: float = BRADLEY_TERRY_DRAW_NU,
    penalty_adv: float = KNOCKOUT_PENALTY_ADVANTAGE,
    calib: "Calibration | None" = None,
) -> dict[str, float]:
    """Match probabilities for knockout rounds (no draws — ET/penalties decide).

    Draws are redistributed: the higher-rated team gets a slight edge
    in extra time/penalties. Calibration is applied to the 90-min 3-way
    probabilities before ET/penalty redistribution.
    """
    base = match_probabilities(elo_a, elo_b, home_advantage, nu, calib=calib)

    if elo_a + home_advantage >= elo_b:
        extra_a = base["draw"] * penalty_adv
        extra_b = base["draw"] * (1.0 - penalty_adv)
    else:
        extra_a = base["draw"] * (1.0 - penalty_adv)
        extra_b = base["draw"] * penalty_adv

    return {
        "win_a": base["win_a"] + extra_a,
        "win_b": base["win_b"] + extra_b,
    }


def get_home_advantage(team_a: str, team_b: str, venue_country: str | None = None) -> float:
    """Determine home advantage Elo bonus for team_a.

    Parameters
    ----------
    team_a : First team (typically "home" in the fixture)
    team_b : Second team
    venue_country : Country where the match is played (None = neutral)

    Returns
    -------
    Elo bonus for team_a. Can be 0 (neutral) or negative if team_b is at home.
    """
    if venue_country is None:
        return 0.0

    # Map country name to team name for host nations
    country_to_team = {
        "United States": "United States",
        "Canada": "Canada",
        "Mexico": "Mexico",
    }

    host_team = country_to_team.get(venue_country)
    if host_team is None:
        return 0.0

    if team_a == host_team:
        return WC_HOST_HOME_ADVANTAGE_ELO
    elif team_b == host_team:
        return -WC_HOST_HOME_ADVANTAGE_ELO

    return 0.0


def predict_match(
    team_a: str,
    team_b: str,
    elo_a: float,
    elo_b: float,
    is_knockout: bool = False,
    venue_country: str | None = None,
) -> dict[str, float]:
    """Predict match outcome with automatic home advantage detection.

    Returns
    -------
    {"win_a": float, ["draw": float,] "win_b": float}
    """
    ha = get_home_advantage(team_a, team_b, venue_country)

    if is_knockout:
        return knockout_probabilities(elo_a, elo_b, home_advantage=ha)
    else:
        return match_probabilities(elo_a, elo_b, home_advantage=ha)


def predict_match_with_uncertainty(
    team_a: str,
    team_b: str,
    elo_a_stats: dict[str, float],
    elo_b_stats: dict[str, float],
    is_knockout: bool = False,
    venue_country: str | None = None,
    n_samples: int = 1000,
    rng: np.random.Generator | None = None,
) -> dict[str, float]:
    """Predict match outcome propagating TSFM Elo uncertainty.

    Parameters
    ----------
    elo_a_stats : {"point": float, "q10": float, "q90": float}
    elo_b_stats : same
    n_samples : Number of Monte Carlo samples for uncertainty propagation

    Returns
    -------
    Averaged probabilities across sampled Elo pairs.
    """
    if rng is None:
        rng = np.random.default_rng()

    ha = get_home_advantage(team_a, team_b, venue_country)

    # Approximate normal distribution from quantiles
    # q10 and q90 span ~2.56 sigma
    sigma_a = max((elo_a_stats["q90"] - elo_a_stats["q10"]) / 2.56, 1.0)
    sigma_b = max((elo_b_stats["q90"] - elo_b_stats["q10"]) / 2.56, 1.0)

    samples_a = rng.normal(elo_a_stats["point"], sigma_a, size=n_samples)
    samples_b = rng.normal(elo_b_stats["point"], sigma_b, size=n_samples)

    # Accumulate probabilities
    accum = {}
    for ea, eb in zip(samples_a, samples_b):
        if is_knockout:
            probs = knockout_probabilities(ea, eb, home_advantage=ha)
        else:
            probs = match_probabilities(ea, eb, home_advantage=ha)

        for key, val in probs.items():
            accum[key] = accum.get(key, 0.0) + val

    return {k: v / n_samples for k, v in accum.items()}
