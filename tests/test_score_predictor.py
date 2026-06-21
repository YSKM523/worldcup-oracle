"""Tests for the Poisson scoreline model."""

import numpy as np
import pytest

from prediction.match_predictor import match_probabilities
from prediction.score_predictor import (
    condition_grid,
    ensemble_match_prediction,
    expected_goals,
    predict_scoreline,
    score_grid,
    top_scorelines,
)


class TestGrid:
    def test_grid_sums_to_one(self):
        grid = score_grid(1.6, 0.9)
        assert grid.sum() == pytest.approx(1.0)

    def test_conditioned_blocks_match_targets(self):
        grid = score_grid(1.4, 1.1)
        out = condition_grid(grid, 0.55, 0.25, 0.20)
        n = grid.shape[0]
        i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        assert out[i > j].sum() == pytest.approx(0.55, abs=1e-9)
        assert out[i == j].sum() == pytest.approx(0.25, abs=1e-9)
        assert out[i < j].sum() == pytest.approx(0.20, abs=1e-9)

    def test_top_scorelines_sorted(self):
        grid = score_grid(1.5, 1.0)
        top = top_scorelines(grid, n=5)
        probs = [p for _, _, p in top]
        assert probs == sorted(probs, reverse=True)


class TestExpectedGoals:
    def test_favorite_gets_more_goals(self):
        lam_a, lam_b = expected_goals(1900, 1500)
        assert lam_a > lam_b
        assert lam_b >= 0.2

    def test_blowout_capped(self):
        lam_a, lam_b = expected_goals(2200, 1300)
        assert lam_a - lam_b <= 2.4 + 1e-9

    def test_home_advantage_shifts_split(self):
        neutral = expected_goals(1700, 1700)
        with_ha = expected_goals(1700, 1700, home_advantage=80)
        assert with_ha[0] > neutral[0]


class TestPredictScoreline:
    def test_favorite_most_likely_score_is_a_win(self):
        pred = predict_scoreline(1950, 1500)
        h, a = map(int, pred["most_likely"].split("-"))
        assert h > a

    def test_equal_teams_symmetric(self):
        # Davidson nu=0.28 gives ~12% draws at equal Elo, so a 1-0/0-1 most
        # likely score is fine — but the distribution must be symmetric.
        pred = predict_scoreline(1700, 1700)
        by_score = {s["score"]: s["p"] for s in pred["top_scores"]}
        for score, p in by_score.items():
            h, a = score.split("-")
            mirrored = by_score.get(f"{a}-{h}")
            if mirrored is not None:
                assert p == pytest.approx(mirrored, abs=1e-4)

    def test_score_probs_consistent_with_davidson(self):
        # Sum of home-win scorelines must equal Davidson p(win_a)
        pred = predict_scoreline(1800, 1600)
        probs = match_probabilities(1800, 1600)
        win_mass = sum(
            s["p"] for s in pred["top_scores"]
            if int(s["score"].split("-")[0]) > int(s["score"].split("-")[1])
        )
        assert win_mass <= probs["win_a"] + 1e-6


class TestEnsemble:
    PAIRS = [(1850, 1600), (1820, 1640), (1880, 1580)]

    def test_outcome_probs_sum_to_one(self):
        pred = ensemble_match_prediction(self.PAIRS)
        assert pred["p_home"] + pred["p_draw"] + pred["p_away"] == pytest.approx(1.0, abs=1e-3)
        assert len(pred["per_model"]) == 3

    def test_knockout_advance_probs(self):
        pred = ensemble_match_prediction(self.PAIRS, knockout=True)
        assert pred["p_adv_home"] + pred["p_adv_away"] == pytest.approx(1.0, abs=1e-3)
        assert pred["p_adv_home"] > pred["p_home"]  # draws redistributed

    def test_ensemble_is_mean_of_models(self):
        pred = ensemble_match_prediction(self.PAIRS)
        mean_home = np.mean([m["p_home"] for m in pred["per_model"]])
        assert pred["p_home"] == pytest.approx(mean_home, abs=1e-3)


# ── Task 4: calibration tests ────────────────────────────────────────────────
from prediction.calibration import Calibration  # noqa: E402

PAIRS = [(1700, 1500), (1680, 1520), (1720, 1490)]


def test_ensemble_calib_none_byte_identical():
    a = ensemble_match_prediction(PAIRS)
    b = ensemble_match_prediction(PAIRS, calib=None)
    # ignore the new *_raw keys when comparing to the legacy shape
    for k in ("p_home", "p_draw", "p_away", "scoreline"):
        assert a[k] == b[k]


def test_ensemble_exposes_raw_equal_to_calibrated_at_identity():
    out = ensemble_match_prediction(PAIRS)
    assert out["p_home_raw"] == out["p_home"]
    assert out["p_draw_raw"] == out["p_draw"]


def test_ensemble_calibration_lifts_draw_and_conditions_scoreline():
    raw = ensemble_match_prediction(PAIRS)
    cal = ensemble_match_prediction(PAIRS, calib=Calibration(1.3, 0.6))
    assert cal["p_draw"] > raw["p_draw"]
    assert cal["p_draw_raw"] == raw["p_draw"]  # raw is unchanged
    # scoreline conditioned on calibrated probs -> 1-1/0-0 mass shifts up
    assert cal["scoreline"]["most_likely"] is not None
    assert abs(cal["p_home"] + cal["p_draw"] + cal["p_away"] - 1.0) < 1e-9
