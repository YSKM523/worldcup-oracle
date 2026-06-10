"""Fetch live 2026 World Cup match results from ESPN's public scoreboard API.

The martj42 dataset (our Elo source) is community-maintained and can lag days
behind during the tournament. ESPN's scoreboard is keyless, updates within
minutes of full time, and includes penalty-shootout winners.

Endpoint:
  https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from config import (
    ALL_TEAMS,
    CACHE_DIR,
    GROUPS,
    HOST_TEAMS,
    TEAM_NAME_ALIASES,
    TOURNAMENT_END,
    TOURNAMENT_START,
)

log = logging.getLogger(__name__)

WC_RESULTS_PARQUET = CACHE_DIR / "wc2026_results.parquet"

ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
)

# ESPN display names → our canonical names (on top of the shared aliases)
ESPN_ALIASES = {
    **TEAM_NAME_ALIASES,
    "Czechia": "Czech Republic",
    "South Korea": "South Korea",
    "Ivory Coast": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Cape Verde Islands": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
}

TEAM_TO_GROUP = {t: g for g, teams in GROUPS.items() for t in teams}

# 2026 stage date windows in *venue-local* dates. All 16 venues sit in
# UTC−4…−7, so late kickoffs spill into the next UTC date (e.g. the last
# group-stage games kick off 02:00Z on June 28 — local evening June 27).
# We classify on kickoff_utc − 6h, which lands every match in its window.
_LOCAL_SHIFT = timedelta(hours=6)
_STAGE_WINDOWS = [
    ("group", date(2026, 6, 11), date(2026, 6, 27)),
    ("r32", date(2026, 6, 28), date(2026, 7, 3)),
    ("r16", date(2026, 7, 4), date(2026, 7, 7)),
    ("qf", date(2026, 7, 9), date(2026, 7, 11)),
    ("sf", date(2026, 7, 14), date(2026, 7, 15)),
    ("third", date(2026, 7, 18), date(2026, 7, 18)),
    ("final", date(2026, 7, 19), date(2026, 7, 19)),
]


def _normalize(name: str) -> str:
    return ESPN_ALIASES.get(name, name)


def _classify_stage(kickoff_utc: datetime, home: str, away: str) -> str:
    local_date = (kickoff_utc - _LOCAL_SHIFT).date()
    for stage, start, end in _STAGE_WINDOWS:
        if start <= local_date <= end:
            return stage
    log.warning("Could not classify stage for %s vs %s at %s", home, away, kickoff_utc)
    return "unknown"


def _parse_event(event: dict) -> dict | None:
    """Parse one ESPN scoreboard event into a result row."""
    comp = event["competitions"][0]
    competitors = comp["competitors"]
    if len(competitors) != 2:
        return None

    home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    home = _normalize(home_c["team"]["displayName"])
    away = _normalize(away_c["team"]["displayName"])

    status = event["status"]["type"]["name"]
    completed = bool(event["status"]["type"].get("completed", False))

    kickoff_utc = datetime.strptime(event["date"], "%Y-%m-%dT%H:%MZ").replace(
        tzinfo=timezone.utc
    )
    kickoff_date = kickoff_utc.date()

    home_score = int(home_c.get("score", 0) or 0)
    away_score = int(away_c.get("score", 0) or 0)

    venue = comp.get("venue") or {}
    venue_name = venue.get("fullName")
    venue_city = (venue.get("address") or {}).get("city")

    # Winner flag covers ET + penalty shootouts (advancing team)
    winner = None
    if completed:
        if home_c.get("winner"):
            winner = home
        elif away_c.get("winner"):
            winner = away
        # Group-stage draws have no winner flag — that's fine.

    stage = _classify_stage(kickoff_utc, home, away)

    return {
        "espn_id": str(event.get("id", "")),
        "date": pd.Timestamp(kickoff_date),
        "kickoff_utc": kickoff_utc.isoformat(),
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "winner": winner,
        "completed": completed,
        "status": status,
        "stage": stage,
        "group": TEAM_TO_GROUP.get(home) if stage == "group" else None,
        "venue": venue_name,
        "venue_city": venue_city,
    }


def fetch_wc_results(force: bool = True) -> pd.DataFrame:
    """Fetch the full 2026 WC schedule + results (start → tournament end).

    Past dates carry final scores; future dates are scheduled fixtures
    (knockout slots appear as placeholder names like "Group C Winner" until
    determined — those rows fail the ALL_TEAMS check and are display-only).
    Cached to parquet. Only completed matches have meaningful scores.
    """
    if not force and WC_RESULTS_PARQUET.exists():
        return pd.read_parquet(WC_RESULTS_PARQUET)

    start = datetime.strptime(TOURNAMENT_START, "%Y-%m-%d").date()
    fetch_end = datetime.strptime(TOURNAMENT_END, "%Y-%m-%d").date()

    rows: list[dict] = []
    day = start
    while day <= fetch_end:
        try:
            resp = requests.get(
                ESPN_SCOREBOARD_URL,
                params={"dates": day.strftime("%Y%m%d")},
                timeout=30,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])
        except Exception as exc:  # noqa: BLE001 — keep pipeline alive on one bad day
            log.warning("ESPN fetch failed for %s: %s", day, exc)
            day += timedelta(days=1)
            continue

        for event in events:
            try:
                row = _parse_event(event)
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to parse event on %s: %s", day, exc)
                continue
            if row is not None:
                rows.append(row)

        day += timedelta(days=1)

    df = pd.DataFrame(rows)
    if df.empty:
        log.info("No WC events returned yet.")
        return df

    # The same event can appear under two dates (late UTC kickoff) — dedupe
    df = df.drop_duplicates(subset=["kickoff_utc", "home_team", "away_team"])
    df = df.sort_values("kickoff_utc").reset_index(drop=True)

    # Placeholder names on future knockout fixtures are expected — only a
    # *completed* match with an unknown team means we're missing an alias.
    done = df[df["completed"]]
    unknown = (set(done["home_team"]) | set(done["away_team"])) - set(ALL_TEAMS)
    if unknown:
        log.warning("Unrecognized team names from ESPN (alias needed): %s", unknown)

    df.to_parquet(WC_RESULTS_PARQUET)
    log.info(
        "WC results: %d matches fetched, %d completed",
        len(df), int(df["completed"].sum()),
    )
    return df


def completed_results(wc_df: pd.DataFrame) -> pd.DataFrame:
    """Only completed matches with both teams recognized."""
    if wc_df.empty:
        return wc_df
    mask = (
        wc_df["completed"]
        & wc_df["home_team"].isin(ALL_TEAMS)
        & wc_df["away_team"].isin(ALL_TEAMS)
    )
    return wc_df[mask].copy()


def merge_into_matches(matches: pd.DataFrame, wc_df: pd.DataFrame) -> pd.DataFrame:
    """Append completed WC results not already present in the matches frame.

    martj42 may eventually include the same matches — dedupe on
    (date, home_team, away_team).
    """
    done = completed_results(wc_df)
    if done.empty:
        return matches

    existing = set(
        zip(matches["date"].dt.date, matches["home_team"], matches["away_team"])
    )
    new_rows = []
    for _, r in done.iterrows():
        key = (r["date"].date(), r["home_team"], r["away_team"])
        key_rev = (r["date"].date(), r["away_team"], r["home_team"])
        if key in existing or key_rev in existing:
            continue
        home, away = r["home_team"], r["away_team"]
        # Hosts play at home; everyone else is on neutral ground
        neutral = not (home in HOST_TEAMS or away in HOST_TEAMS)
        new_rows.append({
            "date": pd.Timestamp(r["date"]),
            "home_team": home,
            "away_team": away,
            "home_score": int(r["home_score"]),
            "away_score": int(r["away_score"]),
            "tournament": "FIFA World Cup",
            "city": None,
            "country": None,
            "neutral": neutral,
            "goal_diff": int(r["home_score"]) - int(r["away_score"]),
            "result": "H" if r["home_score"] > r["away_score"]
                      else ("D" if r["home_score"] == r["away_score"] else "A"),
            "is_competitive": True,
        })

    if not new_rows:
        log.info("All completed WC matches already in matches frame.")
        return matches

    merged = pd.concat([matches, pd.DataFrame(new_rows)], ignore_index=True)
    merged = merged.sort_values("date").reset_index(drop=True)
    log.info("Merged %d new WC results into matches frame.", len(new_rows))
    return merged


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    df = fetch_wc_results(force=True)
    if not df.empty:
        print(df[["date", "home_team", "away_team", "home_score",
                  "away_score", "completed", "stage", "group"]].to_string())
