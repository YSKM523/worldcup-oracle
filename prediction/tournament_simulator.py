"""Level 3: Monte Carlo tournament simulation for the 2026 FIFA World Cup."""

from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np
import pandas as pd

from config import (
    GROUPS,
    HOST_TEAMS,
    MONTE_CARLO_SIMULATIONS,
    POISSON_AVG_GOALS,
    VENUE_COUNTRY,
)
from prediction.match_predictor import (
    get_home_advantage,
    knockout_probabilities,
    match_probabilities,
)

log = logging.getLogger(__name__)

# Stage labels in advancement order
STAGES = [
    "group_advance",  # Top 2 or best 3rd
    "r32",            # Reached Round of 32 (= advanced from group)
    "r16",            # Reached Round of 16
    "qf",             # Reached Quarter-finals
    "sf",             # Reached Semi-finals
    "final",          # Reached Final
    "champion",       # Won tournament
]


def _simulate_match_score(
    p_win_a: float,
    p_draw: float,
    p_win_b: float,
    rng: np.random.Generator,
    avg_goals: float = POISSON_AVG_GOALS,
) -> tuple[int, int]:
    """Sample a scoreline given outcome probabilities."""
    outcome = rng.choice(["win_a", "draw", "win_b"], p=[p_win_a, p_draw, p_win_b])
    total = max(int(rng.poisson(avg_goals)), 0 if outcome == "draw" else 1)

    if outcome == "draw":
        g = total // 2
        return (g, g)
    elif outcome == "win_a":
        loser_goals = rng.integers(0, max(1, total))
        winner_goals = max(loser_goals + 1, total - loser_goals)
        return (int(winner_goals), int(loser_goals))
    else:
        loser_goals = rng.integers(0, max(1, total))
        winner_goals = max(loser_goals + 1, total - loser_goals)
        return (int(loser_goals), int(winner_goals))


def _simulate_group(
    teams: list[str],
    elo_ratings: dict[str, float],
    rng: np.random.Generator,
) -> list[tuple[str, int, int, int]]:
    """Simulate a group of 4 teams (round-robin).

    Returns sorted standings: [(team, points, goal_diff, goals_for), ...]
    """
    standings = {t: {"pts": 0, "gd": 0, "gf": 0} for t in teams}

    # Round-robin: 6 matches (all pairs)
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            a, b = teams[i], teams[j]
            elo_a, elo_b = elo_ratings.get(a, 1500), elo_ratings.get(b, 1500)

            # Determine home advantage (host nations get bonus in their group)
            ha = 0.0
            if a in HOST_TEAMS:
                ha = 80.0  # WC_HOST_HOME_ADVANTAGE_ELO
            elif b in HOST_TEAMS:
                ha = -80.0

            probs = match_probabilities(elo_a, elo_b, home_advantage=ha)
            score_a, score_b = _simulate_match_score(
                probs["win_a"], probs["draw"], probs["win_b"], rng
            )

            # Update standings
            standings[a]["gf"] += score_a
            standings[a]["gd"] += score_a - score_b
            standings[b]["gf"] += score_b
            standings[b]["gd"] += score_b - score_a

            if score_a > score_b:
                standings[a]["pts"] += 3
            elif score_a == score_b:
                standings[a]["pts"] += 1
                standings[b]["pts"] += 1
            else:
                standings[b]["pts"] += 3

    # Sort: points → goal difference → goals scored → random tiebreak
    ranked = sorted(
        standings.items(),
        key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"], rng.random()),
        reverse=True,
    )

    return [(t, s["pts"], s["gd"], s["gf"]) for t, s in ranked]


def _select_best_third_place(
    third_place_teams: list[tuple[str, int, int, int, str]],
    rng: np.random.Generator,
) -> list[str]:
    """Select the 8 best third-place teams from 12 groups.

    Parameters
    ----------
    third_place_teams : [(team, points, gd, gf, group_letter), ...]

    Returns
    -------
    List of 8 team names that advance.
    """
    ranked = sorted(
        third_place_teams,
        key=lambda x: (x[1], x[2], x[3], rng.random()),
        reverse=True,
    )
    return [t[0] for t in ranked[:8]]


def _simulate_knockout_match(
    team_a: str,
    team_b: str,
    elo_ratings: dict[str, float],
    rng: np.random.Generator,
) -> str:
    """Simulate a knockout match. Returns the winner."""
    elo_a = elo_ratings.get(team_a, 1500)
    elo_b = elo_ratings.get(team_b, 1500)

    # Home advantage for host nations in knockout rounds
    ha = 0.0
    if team_a in HOST_TEAMS:
        ha = 80.0
    elif team_b in HOST_TEAMS:
        ha = -80.0

    probs = knockout_probabilities(elo_a, elo_b, home_advantage=ha)

    if rng.random() < probs["win_a"]:
        return team_a
    return team_b


def simulate_tournament(
    elo_ratings: dict[str, float],
    rng: np.random.Generator,
) -> dict[str, str]:
    """Simulate one complete tournament. Returns {team: highest_stage_reached}.

    Automatically detects 32-team (8 groups, 2014/2018 format) vs
    48-team (12 groups, 2026 format) based on GROUPS config.
    """
    team_stage: dict[str, str] = {t: "group_eliminated" for t in elo_ratings}
    n_groups = len(GROUPS)
    is_48_team = n_groups == 12  # 2026 format

    # ── Group Stage ──────────────────────────────────────────────────────
    group_winners = []   # (team, group_letter)
    group_runners = []   # (team, group_letter)
    third_place = []     # (team, pts, gd, gf, group_letter)

    for group_letter, teams in GROUPS.items():
        standings = _simulate_group(teams, elo_ratings, rng)

        # Top 2 advance directly
        group_winners.append((standings[0][0], group_letter))
        group_runners.append((standings[1][0], group_letter))

        for t, _, _, _ in standings[:2]:
            team_stage[t] = "group_advance"

        if is_48_team:
            # 3rd place is a candidate for best-third in 48-team format
            t3 = standings[2]
            third_place.append((t3[0], t3[1], t3[2], t3[3], group_letter))
            team_stage[standings[2][0]] = "group_advance"  # tentative

    if is_48_team:
        # Best 8 third-place teams advance (48-team format)
        best_thirds = _select_best_third_place(third_place, rng)
        # Reset non-advancing 3rd place teams
        all_thirds = {t[0] for t in third_place}
        advancing_thirds = set(best_thirds)
        for t in all_thirds - advancing_thirds:
            team_stage[t] = "group_eliminated"

        r32_teams = (
            [t for t, _ in group_winners]
            + [t for t, _ in group_runners]
            + best_thirds
        )
        for t in r32_teams:
            team_stage[t] = "r32"
        assert len(r32_teams) == 32, f"Expected 32 in R32, got {len(r32_teams)}"

        # R32 → R16
        rng.shuffle(r32_teams)
        r16_teams = []
        for i in range(0, 32, 2):
            winner = _simulate_knockout_match(
                r32_teams[i], r32_teams[i + 1], elo_ratings, rng
            )
            r16_teams.append(winner)
        for t in r16_teams:
            team_stage[t] = "r16"
    else:
        # 32-team format: top 2 per group → R16 directly
        r16_teams = (
            [t for t, _ in group_winners]
            + [t for t, _ in group_runners]
        )
        for t in r16_teams:
            team_stage[t] = "r16"
        assert len(r16_teams) == 16, f"Expected 16 in R16, got {len(r16_teams)}"
        rng.shuffle(r16_teams)

    # R16: 8 matches → 8 winners
    qf_teams = []
    for i in range(0, 16, 2):
        winner = _simulate_knockout_match(
            r16_teams[i], r16_teams[i + 1], elo_ratings, rng
        )
        qf_teams.append(winner)

    for t in qf_teams:
        team_stage[t] = "qf"

    # QF: 4 matches → 4 winners
    sf_teams = []
    for i in range(0, 8, 2):
        winner = _simulate_knockout_match(
            qf_teams[i], qf_teams[i + 1], elo_ratings, rng
        )
        sf_teams.append(winner)

    for t in sf_teams:
        team_stage[t] = "sf"

    # SF: 2 matches → 2 finalists
    finalists = []
    for i in range(0, 4, 2):
        winner = _simulate_knockout_match(
            sf_teams[i], sf_teams[i + 1], elo_ratings, rng
        )
        finalists.append(winner)

    for t in finalists:
        team_stage[t] = "final"

    # Final
    champion = _simulate_knockout_match(
        finalists[0], finalists[1], elo_ratings, rng
    )
    team_stage[champion] = "champion"

    return team_stage


def run_monte_carlo(
    elo_ratings: dict[str, float],
    n_simulations: int = MONTE_CARLO_SIMULATIONS,
    seed: int = 42,
) -> pd.DataFrame:
    """Run N tournament simulations and aggregate probabilities.

    Returns
    -------
    DataFrame with columns: team, P(group_advance), P(r32), ..., P(champion)
    sorted by P(champion) descending.
    """
    rng = np.random.default_rng(seed)

    # Stage index for comparison
    stage_rank = {s: i for i, s in enumerate(
        ["group_eliminated", "group_advance", "r32", "r16", "qf", "sf", "final", "champion"]
    )}

    counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {s: 0 for s in STAGES}
    )

    log.info("Running %d Monte Carlo simulations …", n_simulations)
    for sim in range(n_simulations):
        result = simulate_tournament(elo_ratings, rng)

        for team, stage in result.items():
            team_rank = stage_rank.get(stage, 0)
            for s in STAGES:
                if team_rank >= stage_rank.get(s, 0):
                    counters[team][s] += 1

        if (sim + 1) % 10000 == 0:
            log.info("  %d / %d simulations complete", sim + 1, n_simulations)

    # Convert to probabilities
    rows = []
    for team in sorted(counters.keys()):
        row = {"team": team}
        for stage in STAGES:
            row[f"P({stage})"] = counters[team][stage] / n_simulations
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("P(champion)", ascending=False)
    return df.reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    import sys
    sys.path.insert(0, ".")

    from data.elo import build_elo_history, get_latest_elo
    from data.fetcher_matches import fetch_matches

    matches = fetch_matches()
    elo = build_elo_history(matches)
    latest_elo = get_latest_elo(elo)

    results = run_monte_carlo(latest_elo, n_simulations=50_000)

    print("\n2026 World Cup Predictions (50K simulations, Elo-only baseline):")
    print(f"{'Team':25s} {'Group%':>7} {'R32%':>6} {'R16%':>6} {'QF%':>6} {'SF%':>6} {'Final%':>7} {'Win%':>6}")
    print("-" * 82)
    for _, row in results.head(20).iterrows():
        print(
            f"{row['team']:25s} "
            f"{row['P(group_advance)']:6.1%} "
            f"{row['P(r32)']:5.1%} "
            f"{row['P(r16)']:5.1%} "
            f"{row['P(qf)']:5.1%} "
            f"{row['P(sf)']:5.1%} "
            f"{row['P(final)']:6.1%} "
            f"{row['P(champion)']:5.1%}"
        )

    # Sanity check
    total_champion = results["P(champion)"].sum()
    print(f"\nP(champion) sum: {total_champion:.4f} (should be ~1.0)")
