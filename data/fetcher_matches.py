"""Download and cache international match results."""

from __future__ import annotations

import logging

import pandas as pd
import requests

from config import (
    ALL_TEAMS,
    CACHE_DIR,
    ELO_HISTORY_START,
    MATCHES_CSV_URL,
    TEAM_NAME_ALIASES,
)

log = logging.getLogger(__name__)

MATCHES_PARQUET = CACHE_DIR / "matches.parquet"


def _normalize_team(name: str) -> str:
    return TEAM_NAME_ALIASES.get(name, name)


def fetch_matches(force: bool = False) -> pd.DataFrame:
    """Download international results CSV and return processed DataFrame.

    Caches to parquet. Pass *force=True* to re-download.
    """
    if MATCHES_PARQUET.exists() and not force:
        log.info("Loading cached matches from %s", MATCHES_PARQUET)
        return pd.read_parquet(MATCHES_PARQUET)

    log.info("Downloading matches from %s …", MATCHES_CSV_URL)
    resp = requests.get(MATCHES_CSV_URL, timeout=60)
    resp.raise_for_status()

    # Write to temp file then read with pandas
    tmp = CACHE_DIR / "raw_results.csv"
    tmp.write_bytes(resp.content)
    df = pd.read_csv(tmp)
    tmp.unlink()

    df["date"] = pd.to_datetime(df["date"])

    # Normalize team names
    df["home_team"] = df["home_team"].map(_normalize_team)
    df["away_team"] = df["away_team"].map(_normalize_team)

    # Filter to post-1990 for relevance
    df = df[df["date"] >= ELO_HISTORY_START].copy()

    # Drop future matches with no scores
    df = df.dropna(subset=["home_score", "away_score"]).copy()
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)

    # Computed columns
    df["goal_diff"] = df["home_score"] - df["away_score"]
    df["result"] = df["goal_diff"].map(
        lambda d: "H" if d > 0 else ("D" if d == 0 else "A")
    )

    # Flag competitive matches (non-friendly)
    df["is_competitive"] = ~df["tournament"].str.contains(
        "Friendly", case=False, na=False
    )

    # Neutral venue flag (dataset already has this column)
    if "neutral" not in df.columns:
        df["neutral"] = False
    df["neutral"] = df["neutral"].fillna(False).astype(bool)

    df = df.sort_values("date").reset_index(drop=True)

    log.info(
        "Processed %d matches (%s to %s)",
        len(df),
        df["date"].min().date(),
        df["date"].max().date(),
    )

    df.to_parquet(MATCHES_PARQUET)
    return df


def get_team_matches(df: pd.DataFrame, team: str) -> pd.DataFrame:
    """Extract all matches involving *team*, with result from team's perspective."""
    home = df[df["home_team"] == team].copy()
    home["team_goals"] = home["home_score"]
    home["opp_goals"] = home["away_score"]
    home["opponent"] = home["away_team"]
    home["is_home"] = True
    home["team_result"] = home["result"].map({"H": "W", "D": "D", "A": "L"})

    away = df[df["away_team"] == team].copy()
    away["team_goals"] = away["away_score"]
    away["opp_goals"] = away["home_score"]
    away["opponent"] = away["home_team"]
    away["is_home"] = False
    away["team_result"] = away["result"].map({"H": "L", "D": "D", "A": "W"})

    cols = [
        "date", "opponent", "team_goals", "opp_goals", "team_result",
        "is_home", "tournament", "is_competitive", "neutral",
    ]
    combined = pd.concat([home[cols], away[cols]]).sort_values("date").reset_index(drop=True)
    return combined


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    df = fetch_matches(force=True)
    print(f"\nTotal matches: {len(df)}")

    # Quick check: how many of our 48 teams appear
    all_teams_in_data = set(df["home_team"]) | set(df["away_team"])
    missing = set(ALL_TEAMS) - all_teams_in_data
    if missing:
        print(f"WARNING: Teams not found in data: {missing}")
    else:
        print("All 48 World Cup teams found in dataset.")
