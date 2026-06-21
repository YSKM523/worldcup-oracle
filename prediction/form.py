"""Residual recent-form signal: performance vs Elo expectation -> clamped Elo bump.

Pure module. A team's residual is the mean over its played matches of
(actual outcome - Elo-expected outcome); residual=0 means "exactly as Elo
predicted", so the bump only nudges what Elo has not already priced in.
Evidence-gated: with lam=0 the bump is always 0.
"""

from __future__ import annotations

import pandas as pd

from data.elo import elo_as_of
from prediction.match_predictor import match_probabilities
from prediction.score_predictor import expected_goals


def _actual_points(gf: int, ga: int) -> float:
    if gf > ga:
        return 3.0
    if gf == ga:
        return 1.0
    return 0.0


def points_residual(matches: list[dict]) -> float:
    """Mean (actual points - Elo-expected points) over the team's matches."""
    if not matches:
        return 0.0
    total = 0.0
    for m in matches:
        p = match_probabilities(m["own_elo"], m["opp_elo"], m["home_adv"])
        exp = 3.0 * p["win_a"] + 1.0 * p["draw"]
        total += _actual_points(m["gf"], m["ga"]) - exp
    return total / len(matches)


def gd_residual(matches: list[dict]) -> float:
    """Mean (actual goal diff - Elo-expected goal diff) over the team's matches."""
    if not matches:
        return 0.0
    total = 0.0
    for m in matches:
        lam_own, lam_opp = expected_goals(m["own_elo"], m["opp_elo"], m["home_adv"])
        exp_gd = lam_own - lam_opp
        total += (m["gf"] - m["ga"]) - exp_gd
    return total / len(matches)


def team_form_bump(matches: list[dict], lam: float, cap: float, variant: str) -> float:
    """Clamped Elo bump from a team's form residual. lam=0 -> 0 (feature off)."""
    if lam == 0.0 or not matches:
        return 0.0
    if variant == "points":
        residual = points_residual(matches)
    elif variant == "gd":
        residual = gd_residual(matches)
    else:
        raise ValueError(f"unknown form variant: {variant!r}")
    return max(-cap, min(cap, lam * residual))


def _host_home_adv(home: str, away: str) -> float:
    from config import HOST_TEAMS, WC_HOST_HOME_ADVANTAGE_ELO
    if home in HOST_TEAMS:
        return float(WC_HOST_HOME_ADVANTAGE_ELO)
    if away in HOST_TEAMS:
        return -float(WC_HOST_HOME_ADVANTAGE_ELO)
    return 0.0


def live_form_bumps(wc_df, elo_history, lam: float, cap: float, variant: str) -> dict[str, float]:
    """Per-team Elo bump from completed WC matches (pre-match Elo via elo_as_of)."""
    if lam == 0.0 or wc_df is None or wc_df.empty:
        return {}
    done = wc_df[wc_df["completed"]]
    prior: dict[str, list] = {}
    for _, r in done.iterrows():
        home, away = r["home_team"], r["away_team"]
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        d = r["kickoff_utc"]
        eh = elo_as_of(elo_history, home, d)
        ea = elo_as_of(elo_history, away, d)
        ha = _host_home_adv(home, away)
        prior.setdefault(home, []).append({"own_elo": eh, "opp_elo": ea, "home_adv": ha, "gf": hs, "ga": as_})
        prior.setdefault(away, []).append({"own_elo": ea, "opp_elo": eh, "home_adv": -ha, "gf": as_, "ga": hs})
    return {t: team_form_bump(ms, lam, cap, variant) for t, ms in prior.items()}
