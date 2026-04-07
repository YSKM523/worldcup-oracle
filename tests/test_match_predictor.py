"""Tests for match prediction (Bradley-Terry model)."""

import sys
sys.path.insert(0, ".")

import numpy as np
import pytest

from prediction.match_predictor import (
    match_probabilities,
    knockout_probabilities,
    get_home_advantage,
    predict_match_with_uncertainty,
)


class TestMatchProbabilities:
    def test_probabilities_sum_to_one(self):
        probs = match_probabilities(1800, 1600)
        total = probs["win_a"] + probs["draw"] + probs["win_b"]
        assert abs(total - 1.0) < 1e-6

    def test_equal_ratings_symmetric(self):
        probs = match_probabilities(1500, 1500)
        assert abs(probs["win_a"] - probs["win_b"]) < 1e-6

    def test_higher_elo_favored(self):
        probs = match_probabilities(1800, 1500)
        assert probs["win_a"] > probs["win_b"]

    def test_draw_probability_exists(self):
        probs = match_probabilities(1500, 1500)
        assert probs["draw"] > 0.1  # Should have meaningful draw probability

    def test_home_advantage_increases_win_prob(self):
        neutral = match_probabilities(1600, 1600, home_advantage=0)
        home = match_probabilities(1600, 1600, home_advantage=80)
        assert home["win_a"] > neutral["win_a"]

    def test_extreme_rating_diff(self):
        probs = match_probabilities(2200, 1200)
        assert probs["win_a"] > 0.8
        assert probs["win_b"] < 0.05


class TestKnockoutProbabilities:
    def test_no_draw(self):
        probs = knockout_probabilities(1600, 1500)
        assert "draw" not in probs
        assert abs(probs["win_a"] + probs["win_b"] - 1.0) < 1e-6

    def test_higher_rated_favored_in_penalties(self):
        probs = knockout_probabilities(1700, 1500)
        assert probs["win_a"] > probs["win_b"]

    def test_close_to_50_50_for_equal(self):
        probs = knockout_probabilities(1500, 1500)
        assert abs(probs["win_a"] - 0.5) < 0.05  # Close to 50/50


class TestHomeAdvantage:
    def test_host_at_home(self):
        ha = get_home_advantage("United States", "Brazil", "United States")
        assert ha > 0

    def test_opponent_at_home(self):
        ha = get_home_advantage("Brazil", "Mexico", "Mexico")
        assert ha < 0

    def test_neutral(self):
        ha = get_home_advantage("Brazil", "Germany", None)
        assert ha == 0.0

    def test_non_host_venue(self):
        ha = get_home_advantage("Brazil", "Germany", "Qatar")
        assert ha == 0.0


class TestPredictMatchWithUncertainty:
    def test_output_format(self):
        elo_a = {"point": 1700, "q10": 1650, "q90": 1750}
        elo_b = {"point": 1600, "q10": 1550, "q90": 1650}
        probs = predict_match_with_uncertainty("A", "B", elo_a, elo_b)
        assert "win_a" in probs
        assert "draw" in probs
        assert "win_b" in probs
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_wider_uncertainty_changes_probs(self):
        narrow = {"point": 1600, "q10": 1590, "q90": 1610}
        wide = {"point": 1600, "q10": 1400, "q90": 1800}
        fixed = {"point": 1500, "q10": 1490, "q90": 1510}

        p_narrow = predict_match_with_uncertainty("A", "B", narrow, fixed, n_samples=5000)
        p_wide = predict_match_with_uncertainty("A", "B", wide, fixed, n_samples=5000)
        # Both should still sum to ~1.0
        assert abs(sum(p_narrow.values()) - 1.0) < 0.02
        assert abs(sum(p_wide.values()) - 1.0) < 0.02
