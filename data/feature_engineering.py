"""Build per-team time series features for TSFM input."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import (
    ALL_TEAMS,
    CACHE_DIR,
    ROLLING_WINDOW_MATCHES,
    TEAM_FEATURES_DIR,
    TSFM_CONTEXT_WEEKS,
)

log = logging.getLogger(__name__)


def _rolling_stats(team_matches: pd.DataFrame, window: int) -> pd.DataFrame:
    """Compute rolling match-based statistics for a team.

    Parameters
    ----------
    team_matches : Output of fetcher_matches.get_team_matches()
    window : Number of recent matches for rolling calculations

    Returns
    -------
    DataFrame indexed by match date with rolling features.
    """
    df = team_matches.copy()

    # Win/draw/loss indicators
    df["win"] = (df["team_result"] == "W").astype(float)
    df["draw"] = (df["team_result"] == "D").astype(float)
    df["loss"] = (df["team_result"] == "L").astype(float)
    df["gd"] = df["team_goals"] - df["opp_goals"]

    # Rolling statistics over last N matches
    df["rolling_win_rate"] = df["win"].rolling(window, min_periods=1).mean()
    df["rolling_goal_diff"] = df["gd"].rolling(window, min_periods=1).mean()
    df["avg_goals_scored"] = (
        df["team_goals"].rolling(window, min_periods=1).mean()
    )
    df["avg_goals_conceded"] = (
        df["opp_goals"].rolling(window, min_periods=1).mean()
    )

    # Competitive-only win rate
    comp = df[df["is_competitive"]].copy()
    comp["comp_win_rate"] = comp["win"].rolling(window, min_periods=1).mean()
    df = df.merge(
        comp[["date", "comp_win_rate"]], on="date", how="left", suffixes=("", "_comp")
    )
    df["comp_win_rate"] = df["comp_win_rate"].ffill()

    df = df.set_index("date")
    return df[
        [
            "rolling_win_rate",
            "rolling_goal_diff",
            "avg_goals_scored",
            "avg_goals_conceded",
            "comp_win_rate",
        ]
    ]


def build_team_features(
    team: str,
    matches_df: pd.DataFrame,
    elo_history: pd.DataFrame,
    team_matches_fn,
    n_weeks: int = TSFM_CONTEXT_WEEKS,
) -> pd.DataFrame:
    """Build weekly feature time series for a single team.

    Parameters
    ----------
    team : Team name
    matches_df : Full matches DataFrame
    elo_history : Full Elo history DataFrame
    team_matches_fn : Callable(matches_df, team) → team matches DataFrame
    n_weeks : Number of weeks of history to return

    Returns
    -------
    DataFrame with weekly DatetimeIndex and feature columns.
    """
    from data.elo import resample_weekly

    # 1. Weekly Elo time series (primary TSFM input)
    elo_weekly = resample_weekly(elo_history, team, n_weeks=n_weeks)

    # 2. Match-based rolling features
    tm = team_matches_fn(matches_df, team)
    if tm.empty:
        log.warning("No matches found for %s", team)
        features = pd.DataFrame(index=elo_weekly.index)
        features["elo_rating"] = elo_weekly
        return features

    rolling = _rolling_stats(tm, ROLLING_WINDOW_MATCHES)

    # Resample rolling stats to weekly (forward-fill between matches)
    rolling.index = pd.to_datetime(rolling.index)
    rolling_weekly = rolling.resample("W").last().ffill()

    # 3. Matches played in last 90 days (activity proxy)
    tm_dated = tm.set_index("date").copy()
    tm_dated.index = pd.to_datetime(tm_dated.index)
    tm_dated["count"] = 1
    match_count = tm_dated["count"].resample("W").sum().fillna(0)
    matches_90d = match_count.rolling(13, min_periods=1).sum()  # 13 weeks ≈ 90 days
    matches_90d.name = "matches_played_90d"

    # 4. Combine all features on weekly grid
    features = pd.DataFrame(index=elo_weekly.index)
    features["elo_rating"] = elo_weekly

    for col in rolling_weekly.columns:
        features[col] = rolling_weekly.reindex(features.index, method="ffill")[col]

    features["matches_played_90d"] = matches_90d.reindex(
        features.index, method="ffill"
    ).fillna(0)

    # Fill any remaining NaN with sensible defaults
    features = features.ffill().bfill()

    return features


def build_all_team_features(
    matches_df: pd.DataFrame,
    elo_history: pd.DataFrame,
    team_matches_fn,
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    """Build and cache features for all 48 World Cup teams."""
    result = {}

    for team in ALL_TEAMS:
        parquet_path = TEAM_FEATURES_DIR / f"{team.replace(' ', '_')}.parquet"

        if parquet_path.exists() and not force:
            result[team] = pd.read_parquet(parquet_path)
            continue

        log.info("Building features for %s …", team)
        features = build_team_features(
            team, matches_df, elo_history, team_matches_fn
        )
        features.to_parquet(parquet_path)
        result[team] = features

    log.info("Built features for %d teams", len(result))
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    from data.elo import build_elo_history
    from data.fetcher_matches import fetch_matches, get_team_matches

    matches = fetch_matches()
    elo = build_elo_history(matches)
    features = build_all_team_features(matches, elo, get_team_matches, force=True)

    # Show sample
    for team in ["Brazil", "Argentina", "France", "United States", "Japan"]:
        df = features[team]
        print(f"\n{team}: {len(df)} weeks, Elo range {df['elo_rating'].min():.0f}–{df['elo_rating'].max():.0f}")
        print(df.tail(3).to_string())
