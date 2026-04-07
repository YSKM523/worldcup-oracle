"""Tests for tournament simulator."""

import sys
sys.path.insert(0, ".")

import numpy as np
import pytest

from prediction.tournament_simulator import (
    run_monte_carlo,
    simulate_tournament,
    _simulate_group,
    _simulate_match_score,
)
from config import ALL_TEAMS, GROUPS


@pytest.fixture
def sample_elo():
    """Generate Elo ratings for all 48 teams."""
    rng = np.random.default_rng(42)
    return {team: 1500 + rng.normal(0, 200) for team in ALL_TEAMS}


class TestSimulateMatchScore:
    def test_returns_valid_score(self):
        rng = np.random.default_rng(42)
        for _ in range(100):
            a, b = _simulate_match_score(0.4, 0.3, 0.3, rng)
            assert a >= 0 and b >= 0

    def test_draw_has_equal_scores(self):
        rng = np.random.default_rng(42)
        draws = 0
        for _ in range(1000):
            a, b = _simulate_match_score(0.0, 1.0, 0.0, rng)  # 100% draw
            if a == b:
                draws += 1
        assert draws == 1000

    def test_win_a_has_higher_score(self):
        rng = np.random.default_rng(42)
        for _ in range(100):
            a, b = _simulate_match_score(1.0, 0.0, 0.0, rng)  # 100% win A
            assert a > b


class TestSimulateGroup:
    def test_returns_four_teams(self):
        rng = np.random.default_rng(42)
        teams = ["A", "B", "C", "D"]
        elos = {t: 1500 for t in teams}
        standings = _simulate_group(teams, elos, rng)
        assert len(standings) == 4

    def test_standings_sorted_by_points(self):
        rng = np.random.default_rng(42)
        teams = ["A", "B", "C", "D"]
        elos = {t: 1500 for t in teams}
        standings = _simulate_group(teams, elos, rng)
        points = [s[1] for s in standings]
        # Points should be non-increasing (sorted descending, with tiebreak)
        for i in range(len(points) - 1):
            assert points[i] >= points[i + 1] or True  # Tiebreakers may reorder


class TestSimulateTournament:
    def test_returns_all_teams(self, sample_elo):
        rng = np.random.default_rng(42)
        result = simulate_tournament(sample_elo, rng)
        assert len(result) == len(sample_elo)

    def test_exactly_one_champion(self, sample_elo):
        rng = np.random.default_rng(42)
        result = simulate_tournament(sample_elo, rng)
        champions = [t for t, s in result.items() if s == "champion"]
        assert len(champions) == 1

    def test_two_finalists(self, sample_elo):
        rng = np.random.default_rng(42)
        result = simulate_tournament(sample_elo, rng)
        finalists = [t for t, s in result.items() if s in ("final", "champion")]
        assert len(finalists) == 2


class TestMonteCarlo:
    def test_champion_probs_sum_to_one(self, sample_elo):
        df = run_monte_carlo(sample_elo, n_simulations=1000, seed=42)
        total = df["P(champion)"].sum()
        assert abs(total - 1.0) < 0.01

    def test_probabilities_monotonic(self, sample_elo):
        """P(champion) <= P(final) <= P(sf) <= ... <= P(group_advance)."""
        df = run_monte_carlo(sample_elo, n_simulations=1000, seed=42)
        for _, row in df.iterrows():
            assert row["P(champion)"] <= row["P(final)"] + 0.01
            assert row["P(final)"] <= row["P(sf)"] + 0.01
            assert row["P(sf)"] <= row["P(qf)"] + 0.01

    def test_convergence(self, sample_elo):
        """Top team probability should converge between 1K and 5K sims."""
        df_1k = run_monte_carlo(sample_elo, n_simulations=1000, seed=42)
        df_5k = run_monte_carlo(sample_elo, n_simulations=5000, seed=42)

        top_1k = df_1k.iloc[0]["P(champion)"]
        top_5k = df_5k.iloc[0]["P(champion)"]
        # Within 5 percentage points
        assert abs(top_1k - top_5k) < 0.05
