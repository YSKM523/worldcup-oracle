"""Level 3: Monte Carlo tournament simulation for the 2026 FIFA World Cup."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

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

# ── Official Bracket Structures ─────────────────────────────────────────────
# 32-team format (2014/2018/2022): R16 pairings
# Each entry: ((position, group), (position, group))
# position "1" = group winner, "2" = group runner-up
_R16_BRACKET_32 = [
    (("1", "A"), ("2", "B")),   # R16-1
    (("1", "C"), ("2", "D")),   # R16-2
    (("1", "E"), ("2", "F")),   # R16-3
    (("1", "G"), ("2", "H")),   # R16-4
    (("1", "B"), ("2", "A")),   # R16-5
    (("1", "D"), ("2", "C")),   # R16-6
    (("1", "F"), ("2", "E")),   # R16-7
    (("1", "H"), ("2", "G")),   # R16-8
]
_QF_FROM_R16_32 = [(0, 1), (2, 3), (4, 5), (6, 7)]

# 48-team format (2026): R32 pairings (FIFA match 73-88)
# position "3" = third-place team assigned to a slot index
_R32_BRACKET_48 = [
    (("2", "A"), ("2", "B")),   # M73
    (("1", "E"), ("3", 0)),     # M74
    (("1", "F"), ("2", "C")),   # M75
    (("1", "C"), ("2", "F")),   # M76
    (("1", "I"), ("3", 1)),     # M77
    (("2", "E"), ("2", "I")),   # M78
    (("1", "A"), ("3", 2)),     # M79
    (("1", "L"), ("3", 3)),     # M80
    (("1", "D"), ("3", 4)),     # M81
    (("1", "G"), ("3", 5)),     # M82
    (("2", "K"), ("2", "L")),   # M83
    (("1", "H"), ("2", "J")),   # M84
    (("1", "B"), ("3", 6)),     # M85
    (("1", "J"), ("2", "H")),   # M86
    (("1", "K"), ("3", 7)),     # M87
    (("2", "D"), ("2", "G")),   # M88
]
# R16 from R32 winners (indices into _R32_BRACKET_48)
_R16_FROM_R32 = [
    (1, 4),    # M89: W(M74) vs W(M77)
    (0, 2),    # M90: W(M73) vs W(M75)
    (3, 5),    # M91: W(M76) vs W(M78)
    (6, 7),    # M92: W(M79) vs W(M80)
    (10, 11),  # M93: W(M83) vs W(M84)
    (8, 9),    # M94: W(M81) vs W(M82)
    (13, 15),  # M95: W(M86) vs W(M88)
    (12, 14),  # M96: W(M85) vs W(M87)
]
_QF_FROM_R16_48 = [(0, 1), (4, 5), (2, 3), (6, 7)]

# SF bracket is the same for both formats
_SF_FROM_QF = [(0, 1), (2, 3)]

# Third-place slot constraints: which groups can fill each R32 slot
_THIRD_PLACE_SLOT_GROUPS = [
    frozenset("ABCDF"),   # slot 0 (M74, vs 1E)
    frozenset("CDFGH"),   # slot 1 (M77, vs 1I)
    frozenset("CEFHI"),   # slot 2 (M79, vs 1A)
    frozenset("EHIJK"),   # slot 3 (M80, vs 1L)
    frozenset("BEFIJ"),   # slot 4 (M81, vs 1D)
    frozenset("AEHIJ"),   # slot 5 (M82, vs 1G)
    frozenset("EFGIJ"),   # slot 6 (M85, vs 1B)
    frozenset("DEIJL"),   # slot 7 (M87, vs 1K)
]

_third_place_cache: dict[frozenset[str], dict[int, str]] = {}


# ── Tournament State (live conditioning) ─────────────────────────────────────
@dataclass
class TournamentState:
    """Known real-world results to condition the simulation on.

    group_played : {group_letter: [(team_a, team_b, score_a, score_b), ...]}
    ko_winners   : {stage: {frozenset({a, b}): winner}} for completed knockouts
    ko_fixtures  : {stage: [frozenset({a, b}), ...]} actual pairings, including
                   scheduled-but-unplayed ones (used to pin third-place slots)
    """

    group_played: dict[str, list[tuple[str, str, int, int]]] = field(default_factory=dict)
    ko_winners: dict[str, dict[frozenset, str]] = field(default_factory=dict)
    ko_fixtures: dict[str, list[frozenset]] = field(default_factory=dict)

    @classmethod
    def from_results(cls, wc_df: pd.DataFrame, all_teams: set[str] | None = None) -> "TournamentState":
        """Build state from a fetcher_wc_results DataFrame (completed + scheduled)."""
        state = cls()
        if wc_df is None or wc_df.empty:
            return state

        for _, r in wc_df.iterrows():
            home, away = r["home_team"], r["away_team"]
            if all_teams is not None and (home not in all_teams or away not in all_teams):
                continue  # TBD placeholders before a round is determined
            stage = r["stage"]

            if stage == "group":
                if r["completed"]:
                    state.group_played.setdefault(r["group"], []).append(
                        (home, away, int(r["home_score"]), int(r["away_score"]))
                    )
            elif stage in ("r32", "r16", "qf", "sf", "final"):
                pair = frozenset((home, away))
                state.ko_fixtures.setdefault(stage, []).append(pair)
                if r["completed"] and r.get("winner"):
                    state.ko_winners.setdefault(stage, {})[pair] = r["winner"]
            # "third" place match does not affect highest-stage-reached

        return state

    def groups_complete(self, groups: dict[str, list[str]]) -> bool:
        """True when every group's 6 matches have been played."""
        return all(
            len(self.group_played.get(g, [])) >= 6 for g in groups
        )

# ── 2026 Knockout Venue Countries ────────────────────────────────────────────
# Only apply home advantage when the match venue is in a host team's country.
_R32_VENUE_COUNTRY = [
    "United States",   # M73: Inglewood
    "United States",   # M74: Foxborough
    "Mexico",          # M75: Guadalupe
    "United States",   # M76: Houston
    "United States",   # M77: East Rutherford
    "United States",   # M78: Arlington
    "Mexico",          # M79: Mexico City
    "United States",   # M80: Atlanta
    "United States",   # M81: Santa Clara
    "United States",   # M82: Seattle
    "Canada",          # M83: Toronto
    "United States",   # M84: Inglewood
    "Canada",          # M85: Vancouver
    "United States",   # M86: Miami Gardens
    "United States",   # M87: Kansas City
    "United States",   # M88: Arlington
]
_R16_VENUE_COUNTRY = [
    "United States",   # M89: Philadelphia
    "United States",   # M90: Houston
    "United States",   # M91: East Rutherford
    "Mexico",          # M92: Mexico City
    "United States",   # M93: Arlington
    "United States",   # M94: Seattle
    "United States",   # M95: Atlanta
    "Canada",          # M96: Vancouver
]
_QF_VENUE_COUNTRY = [
    "United States",   # M97: Foxborough
    "United States",   # M98: Inglewood
    "United States",   # M99: Miami Gardens
    "United States",   # M100: Kansas City
]
_SF_VENUE_COUNTRY = [
    "United States",   # M101: Arlington
    "United States",   # M102: Atlanta
]
_FINAL_VENUE_COUNTRY = "United States"  # M103: East Rutherford


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
    played: list[tuple[str, str, int, int]] | None = None,
) -> list[tuple[str, int, int, int]]:
    """Simulate a group of 4 teams (round-robin).

    Real results in *played* are applied as-is; only remaining fixtures
    are simulated.

    Returns sorted standings: [(team, points, goal_diff, goals_for), ...]
    """
    standings = {t: {"pts": 0, "gd": 0, "gf": 0} for t in teams}

    played_pairs: set[frozenset] = set()
    for a, b, score_a, score_b in (played or []):
        if a not in standings or b not in standings:
            continue
        played_pairs.add(frozenset((a, b)))
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

    # Round-robin: 6 matches (all pairs), minus already-played ones
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            a, b = teams[i], teams[j]
            if frozenset((a, b)) in played_pairs:
                continue
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
    venue_country: str | None = None,
    known_winners: dict[frozenset, str] | None = None,
) -> str:
    """Simulate a knockout match. Returns the winner.

    If the real result is already known (known_winners), it is used directly.
    Home advantage is only applied when venue_country matches a host team.
    """
    if known_winners:
        winner = known_winners.get(frozenset((team_a, team_b)))
        if winner is not None:
            return winner

    elo_a = elo_ratings.get(team_a, 1500)
    elo_b = elo_ratings.get(team_b, 1500)

    ha = get_home_advantage(team_a, team_b, venue_country)
    probs = knockout_probabilities(elo_a, elo_b, home_advantage=ha)

    if rng.random() < probs["win_a"]:
        return team_a
    return team_b


def _assign_third_place_to_slots(
    qualifying_groups: frozenset[str],
) -> dict[int, str]:
    """Assign qualifying third-place groups to R32 slots via constraint satisfaction.

    Uses backtracking with MRV heuristic. Results are cached (max 495 combos).
    Returns {slot_index: group_letter}.
    """
    cached = _third_place_cache.get(qualifying_groups)
    if cached is not None:
        return cached

    assignment: dict[int, str] = {}
    used: set[str] = set()

    def backtrack() -> bool:
        if len(assignment) == 8:
            return True
        slot = min(
            (s for s in range(8) if s not in assignment),
            key=lambda s: len(_THIRD_PLACE_SLOT_GROUPS[s] - used),
        )
        for group in sorted(_THIRD_PLACE_SLOT_GROUPS[slot] & qualifying_groups - used):
            assignment[slot] = group
            used.add(group)
            if backtrack():
                return True
            del assignment[slot]
            used.discard(group)
        return False

    if not backtrack():
        raise ValueError(
            f"No valid third-place assignment for groups {qualifying_groups}"
        )

    _third_place_cache[qualifying_groups] = dict(assignment)
    return _third_place_cache[qualifying_groups]


def _pin_third_slots_from_fixtures(
    winners: dict[str, str],
    third_by_group: dict[str, str],
    r32_fixtures: list[frozenset],
) -> dict[int, str] | None:
    """Derive the real third-place slot assignment from actual R32 pairings.

    Each third-place slot faces a known group winner (e.g. slot 0 plays 1E).
    Once real fixtures are out, find the winner's match — the opponent is the
    third-place team for that slot. Returns None if derivation fails.
    """
    team_to_slot_team: dict[int, str] = {}
    thirds = set(third_by_group.values())

    for src_a, src_b in _R32_BRACKET_48:
        for src, other in ((src_a, src_b), (src_b, src_a)):
            if src[0] != "3":
                continue
            slot = src[1]
            # The opposing side is always a "1X" group winner in the 2026 bracket
            if other[0] != "1":
                return None
            anchor = winners.get(other[1])
            if anchor is None:
                return None
            fixture = next((f for f in r32_fixtures if anchor in f), None)
            if fixture is None:
                return None
            opponent = next((t for t in fixture if t != anchor), None)
            if opponent is None or opponent not in thirds:
                return None
            team_to_slot_team[slot] = opponent

    return team_to_slot_team if len(team_to_slot_team) == 8 else None


def simulate_tournament(
    elo_ratings: dict[str, float],
    rng: np.random.Generator,
    groups: dict[str, list[str]] | None = None,
    state: TournamentState | None = None,
) -> dict[str, str]:
    """Simulate one complete tournament. Returns {team: highest_stage_reached}.

    Uses the official FIFA bracket structure:
    - 32-team (8 groups): 1A vs 2B, 1C vs 2D, etc.
    - 48-team (12 groups): FIFA 2026 R32 bracket with third-place assignment.

    Parameters
    ----------
    groups : optional override for tournament groups (default: 2026 config)
    state : known real results — played matches are applied, not simulated
    """
    if groups is None:
        groups = GROUPS
    team_stage: dict[str, str] = {t: "group_eliminated" for t in elo_ratings}
    n_groups = len(groups)
    is_48_team = n_groups == 12  # 2026 format

    # ── Group Stage ──────────────────────────────────────────────────────
    winners: dict[str, str] = {}   # group_letter -> team
    runners: dict[str, str] = {}   # group_letter -> team
    third_place: list[tuple[str, int, int, int, str]] = []

    for group_letter, teams in groups.items():
        played = state.group_played.get(group_letter) if state else None
        standings = _simulate_group(teams, elo_ratings, rng, played=played)
        winners[group_letter] = standings[0][0]
        runners[group_letter] = standings[1][0]

        for t, _, _, _ in standings[:2]:
            team_stage[t] = "group_advance"

        if is_48_team:
            t3 = standings[2]
            third_place.append((t3[0], t3[1], t3[2], t3[3], group_letter))
            team_stage[t3[0]] = "group_advance"  # tentative

    # ── Build Knockout Matchups from Official Bracket ────────────────────
    if is_48_team:
        # Select best 8 third-place teams
        best_thirds_names = _select_best_third_place(third_place, rng)
        best_thirds_set = set(best_thirds_names)

        # Reset non-advancing thirds
        for t_name, _, _, _, _ in third_place:
            if t_name not in best_thirds_set:
                team_stage[t_name] = "group_eliminated"

        # Map group -> third-place team (only qualifying ones)
        third_by_group = {
            g: t for t, _, _, _, g in third_place if t in best_thirds_set
        }

        # Assign third-place teams to R32 slots. When the real R32 fixtures
        # are out (groups complete), pin FIFA's actual assignment; otherwise
        # solve the constraint satisfaction problem.
        slot_to_team = None
        if state and state.ko_fixtures.get("r32") and state.groups_complete(groups):
            slot_to_team = _pin_third_slots_from_fixtures(
                winners, third_by_group, state.ko_fixtures["r32"]
            )
        if slot_to_team is None:
            slot_to_group = _assign_third_place_to_slots(
                frozenset(third_by_group.keys())
            )
            slot_to_team = {s: third_by_group[g] for s, g in slot_to_group.items()}

        def resolve_48(src: tuple) -> str:
            pos, key = src
            if pos == "1":
                return winners[key]
            elif pos == "2":
                return runners[key]
            return slot_to_team[key]  # "3"

        # R32: 16 matches following official bracket (with venue-based HA)
        r32_matchups = [
            (resolve_48(a), resolve_48(b)) for a, b in _R32_BRACKET_48
        ]
        for team_a, team_b in r32_matchups:
            team_stage[team_a] = "r32"
            team_stage[team_b] = "r32"

        known_r32 = state.ko_winners.get("r32") if state else None
        r32_winners = [
            _simulate_knockout_match(
                a, b, elo_ratings, rng, _R32_VENUE_COUNTRY[i], known_winners=known_r32
            )
            for i, (a, b) in enumerate(r32_matchups)
        ]

        # R16 from R32 winners (official bracket paths)
        r16_matchups = [
            (r32_winners[i], r32_winners[j]) for i, j in _R16_FROM_R32
        ]
        for team_a, team_b in r16_matchups:
            team_stage[team_a] = "r16"
            team_stage[team_b] = "r16"

        qf_bracket = _QF_FROM_R16_48
        r16_venues = _R16_VENUE_COUNTRY
        qf_venues = _QF_VENUE_COUNTRY
        sf_venues = _SF_VENUE_COUNTRY
        final_venue = _FINAL_VENUE_COUNTRY
    else:
        # 32-team format: R16 directly from official bracket (1A vs 2B, etc.)
        # Backtests use neutral venues (no host advantage)
        def resolve_32(src: tuple) -> str:
            pos, grp = src
            return winners[grp] if pos == "1" else runners[grp]

        r16_matchups = [
            (resolve_32(a), resolve_32(b)) for a, b in _R16_BRACKET_32
        ]
        for team_a, team_b in r16_matchups:
            team_stage[team_a] = "r16"
            team_stage[team_b] = "r16"

        qf_bracket = _QF_FROM_R16_32
        r16_venues = [None] * 8
        qf_venues = [None] * 4
        sf_venues = [None] * 2
        final_venue = None

    # ── R16 → QF → SF → Final ───────────────────────────────────────────
    known_r16 = state.ko_winners.get("r16") if state else None
    r16_winners = [
        _simulate_knockout_match(
            a, b, elo_ratings, rng, r16_venues[i], known_winners=known_r16
        )
        for i, (a, b) in enumerate(r16_matchups)
    ]

    qf_matchups = [(r16_winners[i], r16_winners[j]) for i, j in qf_bracket]
    for a, b in qf_matchups:
        team_stage[a] = "qf"
        team_stage[b] = "qf"

    known_qf = state.ko_winners.get("qf") if state else None
    qf_winners = [
        _simulate_knockout_match(
            a, b, elo_ratings, rng, qf_venues[i], known_winners=known_qf
        )
        for i, (a, b) in enumerate(qf_matchups)
    ]

    sf_matchups = [(qf_winners[i], qf_winners[j]) for i, j in _SF_FROM_QF]
    for a, b in sf_matchups:
        team_stage[a] = "sf"
        team_stage[b] = "sf"

    known_sf = state.ko_winners.get("sf") if state else None
    sf_winners = [
        _simulate_knockout_match(
            a, b, elo_ratings, rng, sf_venues[i], known_winners=known_sf
        )
        for i, (a, b) in enumerate(sf_matchups)
    ]

    team_stage[sf_winners[0]] = "final"
    team_stage[sf_winners[1]] = "final"

    known_final = state.ko_winners.get("final") if state else None
    champion = _simulate_knockout_match(
        sf_winners[0], sf_winners[1], elo_ratings, rng, final_venue,
        known_winners=known_final,
    )
    team_stage[champion] = "champion"

    return team_stage


def run_monte_carlo(
    elo_ratings: dict[str, float],
    n_simulations: int = MONTE_CARLO_SIMULATIONS,
    seed: int = 42,
    groups: dict[str, list[str]] | None = None,
    state: TournamentState | None = None,
) -> pd.DataFrame:
    """Run N tournament simulations and aggregate probabilities.

    Parameters
    ----------
    groups : optional override for tournament groups (default: 2026 config)
    state : known real results to condition on (live, mid-tournament)

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
        result = simulate_tournament(elo_ratings, rng, groups=groups, state=state)

        for team, stage in result.items():
            team_rank = stage_rank.get(stage, 0)
            for s in STAGES:
                if team_rank >= stage_rank.get(s, 0):
                    counters[team][s] += 1

        if (sim + 1) % 10000 == 0:
            log.info("  %d / %d simulations complete", sim + 1, n_simulations)

    # Convert to probabilities — include teams that never advanced (all zeros)
    rows = []
    for team in sorted(elo_ratings.keys()):
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
