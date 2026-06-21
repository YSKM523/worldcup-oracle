"""Compute Elo ratings from international match history."""

from __future__ import annotations

import logging
import math
from collections import defaultdict

import numpy as np
import pandas as pd

from config import (
    ALL_TEAMS,
    CACHE_DIR,
    ELO_HOME_ADVANTAGE,
    ELO_INITIAL,
    ELO_K_DEFAULT,
    ELO_K_FACTORS,
    TSFM_CONTEXT_WEEKS,
)

log = logging.getLogger(__name__)

ELO_PARQUET = CACHE_DIR / "elo_history.parquet"


def _k_factor(tournament: str) -> float:
    """Return K-factor for a given tournament name."""
    for key, k in ELO_K_FACTORS.items():
        if key.lower() in tournament.lower():
            return k
    return ELO_K_DEFAULT


def _goal_diff_multiplier(goal_diff: int) -> float:
    """Diminishing returns for blowouts: G = 1 + ln(1 + |gd|)."""
    return 1.0 + math.log1p(abs(goal_diff))


def _expected_score(rating_a: float, rating_b: float) -> float:
    """Standard Elo expected score for player A."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def compute_elo(matches: pd.DataFrame) -> pd.DataFrame:
    """Compute Elo ratings for all teams from chronological match data.

    Parameters
    ----------
    matches : DataFrame with columns: date, home_team, away_team,
              home_score, away_score, tournament, neutral

    Returns
    -------
    DataFrame with columns: date, team, elo
    One row per team per match (the team's Elo AFTER that match).
    """
    ratings: dict[str, float] = defaultdict(lambda: ELO_INITIAL)
    records: list[dict] = []

    for _, row in matches.iterrows():
        home = row["home_team"]
        away = row["away_team"]
        date = row["date"]
        tournament = row["tournament"]
        neutral = bool(row.get("neutral", False))

        h_score = int(row["home_score"])
        a_score = int(row["away_score"])
        gd = h_score - a_score

        k = _k_factor(tournament)
        g = _goal_diff_multiplier(gd)

        # Home advantage
        ha = 0.0 if neutral else ELO_HOME_ADVANTAGE

        r_home = ratings[home]
        r_away = ratings[away]

        e_home = _expected_score(r_home + ha, r_away)
        e_away = 1.0 - e_home

        # Actual scores
        if gd > 0:
            s_home, s_away = 1.0, 0.0
        elif gd == 0:
            s_home, s_away = 0.5, 0.5
        else:
            s_home, s_away = 0.0, 1.0

        # Update ratings
        ratings[home] = r_home + k * g * (s_home - e_home)
        ratings[away] = r_away + k * g * (s_away - e_away)

        records.append({"date": date, "team": home, "elo": ratings[home]})
        records.append({"date": date, "team": away, "elo": ratings[away]})

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_latest_elo(elo_history: pd.DataFrame) -> dict[str, float]:
    """Get the most recent Elo rating for each team."""
    latest = elo_history.sort_values("date").groupby("team").last()
    return latest["elo"].to_dict()


def elo_as_of(elo_history: pd.DataFrame, team: str, date) -> float:
    """Team's Elo from the latest history row STRICTLY BEFORE `date`.

    Returns ELO_INITIAL when the team has no prior row. Used to get a match's
    pre-match Elo without lookahead.
    """
    from config import ELO_INITIAL

    d = pd.Timestamp(date)
    rows = elo_history[(elo_history["team"] == team) & (pd.to_datetime(elo_history["date"]) < d)]
    if rows.empty:
        return float(ELO_INITIAL)
    return float(rows.sort_values("date")["elo"].iloc[-1])


def resample_weekly(
    elo_history: pd.DataFrame, team: str, n_weeks: int | None = None
) -> pd.Series:
    """Resample a team's Elo history to weekly frequency via forward-fill.

    Parameters
    ----------
    elo_history : Full Elo history DataFrame
    team : Team name
    n_weeks : If set, return only the last *n_weeks* data points

    Returns
    -------
    pd.Series with weekly DatetimeIndex and Elo values.
    """
    team_df = elo_history[elo_history["team"] == team].copy()
    if team_df.empty:
        raise ValueError(f"No Elo history for team: {team}")

    # Keep only the last Elo per day (a team might play twice on same day)
    team_df = team_df.sort_values("date").groupby("date").last().reset_index()
    team_df = team_df.set_index("date")["elo"]

    # Resample to weekly (Sunday-ending) and forward-fill
    weekly = team_df.resample("W").last().ffill()

    if n_weeks is not None:
        weekly = weekly.iloc[-n_weeks:]

    return weekly


def build_elo_history(matches: pd.DataFrame, force: bool = False) -> pd.DataFrame:
    """Compute and cache Elo history."""
    if ELO_PARQUET.exists() and not force:
        log.info("Loading cached Elo history from %s", ELO_PARQUET)
        return pd.read_parquet(ELO_PARQUET)

    log.info("Computing Elo ratings for %d matches …", len(matches))
    elo_df = compute_elo(matches)
    elo_df.to_parquet(ELO_PARQUET)
    log.info("Elo history saved: %d records", len(elo_df))
    return elo_df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    from data.fetcher_matches import fetch_matches

    matches = fetch_matches()
    elo = build_elo_history(matches, force=True)

    latest = get_latest_elo(elo)
    wc_teams = {t: latest.get(t, ELO_INITIAL) for t in ALL_TEAMS}
    ranked = sorted(wc_teams.items(), key=lambda x: x[1], reverse=True)

    print("\n2026 World Cup Teams by Elo Rating:")
    print(f"{'Rank':>4}  {'Team':25s}  {'Elo':>7}")
    print("-" * 42)
    for i, (team, elo_val) in enumerate(ranked, 1):
        print(f"{i:4d}  {team:25s}  {elo_val:7.1f}")
