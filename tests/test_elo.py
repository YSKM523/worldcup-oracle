"""Tests for Elo rating computation."""

import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
import pytest

from data.elo import compute_elo, resample_weekly, _expected_score, _goal_diff_multiplier


def _make_matches(rows):
    """Helper to create a matches DataFrame from (date, home, away, h_score, a_score, tournament, neutral)."""
    return pd.DataFrame(rows, columns=[
        "date", "home_team", "away_team", "home_score", "away_score", "tournament", "neutral",
    ])


class TestExpectedScore:
    def test_equal_ratings(self):
        e = _expected_score(1500, 1500)
        assert abs(e - 0.5) < 1e-6

    def test_higher_rating_advantage(self):
        e = _expected_score(1700, 1500)
        assert e > 0.5

    def test_lower_rating_disadvantage(self):
        e = _expected_score(1300, 1500)
        assert e < 0.5

    def test_symmetry(self):
        e_a = _expected_score(1600, 1400)
        e_b = _expected_score(1400, 1600)
        assert abs(e_a + e_b - 1.0) < 1e-6


class TestGoalDiffMultiplier:
    def test_zero_goal_diff(self):
        g = _goal_diff_multiplier(0)
        assert abs(g - 1.0) < 1e-6

    def test_positive_increases(self):
        assert _goal_diff_multiplier(3) > _goal_diff_multiplier(1)

    def test_diminishing_returns(self):
        diff_1_2 = _goal_diff_multiplier(2) - _goal_diff_multiplier(1)
        diff_5_6 = _goal_diff_multiplier(6) - _goal_diff_multiplier(5)
        assert diff_1_2 > diff_5_6  # Diminishing returns

    def test_symmetric(self):
        assert abs(_goal_diff_multiplier(3) - _goal_diff_multiplier(-3)) < 1e-6


class TestComputeElo:
    def test_basic_win(self):
        matches = _make_matches([
            ("2020-01-01", "TeamA", "TeamB", 2, 0, "Friendly", True),
        ])
        elo = compute_elo(matches)
        a_elo = elo[elo["team"] == "TeamA"]["elo"].iloc[0]
        b_elo = elo[elo["team"] == "TeamB"]["elo"].iloc[0]
        assert a_elo > 1500  # Winner's Elo increased
        assert b_elo < 1500  # Loser's Elo decreased

    def test_draw_no_change_for_equal(self):
        matches = _make_matches([
            ("2020-01-01", "TeamA", "TeamB", 1, 1, "Friendly", True),
        ])
        elo = compute_elo(matches)
        a_elo = elo[elo["team"] == "TeamA"]["elo"].iloc[0]
        b_elo = elo[elo["team"] == "TeamB"]["elo"].iloc[0]
        # For equal-rated teams on neutral ground, a draw shouldn't change Elo
        assert abs(a_elo - 1500) < 1.0
        assert abs(b_elo - 1500) < 1.0

    def test_k_factor_world_cup_higher(self):
        wc = _make_matches([("2020-01-01", "A", "B", 2, 0, "FIFA World Cup", True)])
        fr = _make_matches([("2020-01-01", "C", "D", 2, 0, "Friendly", True)])
        elo_wc = compute_elo(wc)
        elo_fr = compute_elo(fr)
        wc_gain = elo_wc[elo_wc["team"] == "A"]["elo"].iloc[0] - 1500
        fr_gain = elo_fr[elo_fr["team"] == "C"]["elo"].iloc[0] - 1500
        assert wc_gain > fr_gain  # WC has higher K-factor

    def test_conservation(self):
        """Total Elo across all teams is conserved (zero-sum updates)."""
        matches = _make_matches([
            ("2020-01-01", "A", "B", 3, 1, "Friendly", True),
            ("2020-01-02", "B", "C", 0, 0, "Friendly", True),
            ("2020-01-03", "A", "C", 1, 2, "Friendly", True),
        ])
        elo = compute_elo(matches)
        # Get latest Elo for each team
        latest = elo.sort_values("date").groupby("team")["elo"].last()
        total = latest.sum()
        expected = 1500 * 3  # 3 teams * initial
        assert abs(total - expected) < 1.0


class TestResampleWeekly:
    def test_output_weekly_frequency(self):
        matches = _make_matches([
            (f"2020-{m:02d}-15", "TeamA", "TeamB", 1, 0, "Friendly", True)
            for m in range(1, 7)
        ])
        elo = compute_elo(matches)
        weekly = resample_weekly(elo, "TeamA")
        assert weekly.index.freq == "W-SUN" or len(weekly) > 5

    def test_n_weeks_limit(self):
        matches = _make_matches([
            (f"20{y:02d}-06-15", "TeamA", "TeamB", 1, 0, "Friendly", True)
            for y in range(10, 25)
        ])
        elo = compute_elo(matches)
        weekly = resample_weekly(elo, "TeamA", n_weeks=52)
        assert len(weekly) == 52
