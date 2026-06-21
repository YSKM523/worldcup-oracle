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
        """Primary sort key (points) should be non-increasing across many seeds."""
        teams = ["A", "B", "C", "D"]
        elos = {t: 1500 for t in teams}
        for seed in range(50):
            rng = np.random.default_rng(seed)
            standings = _simulate_group(teams, elos, rng)
            points = [s[1] for s in standings]
            for i in range(len(points) - 1):
                # Tiebreakers (gd, gf, random) can reorder equal-point teams,
                # but a higher-ranked team must never have fewer points.
                assert points[i] >= points[i + 1], (
                    f"seed={seed}: points not sorted: {points}"
                )


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

    def test_32_team_format_via_groups_param(self):
        """Passing 8 groups of 4 should run the 32-team format (no R32 round)."""
        groups_32 = {
            "A": ["T_A1", "T_A2", "T_A3", "T_A4"],
            "B": ["T_B1", "T_B2", "T_B3", "T_B4"],
            "C": ["T_C1", "T_C2", "T_C3", "T_C4"],
            "D": ["T_D1", "T_D2", "T_D3", "T_D4"],
            "E": ["T_E1", "T_E2", "T_E3", "T_E4"],
            "F": ["T_F1", "T_F2", "T_F3", "T_F4"],
            "G": ["T_G1", "T_G2", "T_G3", "T_G4"],
            "H": ["T_H1", "T_H2", "T_H3", "T_H4"],
        }
        all_teams = [t for g in groups_32.values() for t in g]
        elos = {t: 1500 for t in all_teams}
        rng = np.random.default_rng(42)

        result = simulate_tournament(elos, rng, groups=groups_32)

        assert len(result) == 32
        champions = [t for t, s in result.items() if s == "champion"]
        assert len(champions) == 1
        # In 32-team format there should be no R32 stage
        r32_teams = [t for t, s in result.items() if s == "r32"]
        assert len(r32_teams) == 0


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

    def test_monte_carlo_calib_none_matches_default(self, sample_elo):
        a = run_monte_carlo(sample_elo, n_simulations=2000, seed=7)
        b = run_monte_carlo(sample_elo, n_simulations=2000, seed=7, calib=None)
        assert a.equals(b)

    def test_monte_carlo_calib_changes_distribution(self, sample_elo):
        from prediction.calibration import Calibration
        base = run_monte_carlo(sample_elo, n_simulations=4000, seed=7)
        flat = run_monte_carlo(sample_elo, n_simulations=4000, seed=7,
                               calib=Calibration(2.0, 0.5))
        # flattening should reduce the top team's champion prob (more parity)
        top_base = base.sort_values("P(champion)", ascending=False).iloc[0]["P(champion)"]
        top_flat = flat.set_index("team").loc[
            base.sort_values("P(champion)", ascending=False).iloc[0]["team"], "P(champion)"]
        assert top_flat <= top_base + 1e-9
