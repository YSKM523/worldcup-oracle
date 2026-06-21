import pytest
from prediction.form import points_residual, gd_residual, team_form_bump

# A perfectly-even match (equal Elo, neutral): E[points] ~1.0-1.3; a win over-performs.
EVEN_WIN = {"own_elo": 1500, "opp_elo": 1500, "home_adv": 0.0, "gf": 2, "ga": 0}
EVEN_LOSS = {"own_elo": 1500, "opp_elo": 1500, "home_adv": 0.0, "gf": 0, "ga": 2}

def test_empty_residual_is_zero():
    assert points_residual([]) == 0.0
    assert gd_residual([]) == 0.0

def test_points_residual_positive_when_overperforming():
    # Winning an even match beats the ~1.0-1.3 expected points -> residual > 0
    assert points_residual([EVEN_WIN]) > 0.0

def test_points_residual_negative_when_underperforming():
    assert points_residual([EVEN_LOSS]) < 0.0

def test_gd_residual_sign():
    assert gd_residual([EVEN_WIN]) > 0.0      # +2 GD vs ~0 expected
    assert gd_residual([EVEN_LOSS]) < 0.0

def test_residual_near_zero_when_result_matches_expectation():
    # A heavy favourite (high Elo) winning by a little ~ matches expectation
    strong_draw = {"own_elo": 1500, "opp_elo": 1500, "home_adv": 0.0, "gf": 1, "ga": 1}
    # an even draw: expected points ~ p_win*3+p_draw*1; a draw yields 1 -> small residual
    assert abs(points_residual([strong_draw])) < 1.0

def test_form_bump_zero_when_lambda_zero():
    assert team_form_bump([EVEN_WIN], lam=0.0, cap=100.0, variant="points") == 0.0

def test_form_bump_clamped():
    big = [EVEN_WIN] * 1
    bump = team_form_bump(big, lam=10_000.0, cap=80.0, variant="points")
    assert bump == 80.0  # clamped to +cap

def test_form_bump_variant_gd():
    b = team_form_bump([EVEN_WIN], lam=50.0, cap=500.0, variant="gd")
    assert b > 0.0

def test_form_bump_unknown_variant_raises():
    with pytest.raises(ValueError):
        team_form_bump([EVEN_WIN], lam=50.0, cap=100.0, variant="bogus")


def test_form_bump_unknown_variant_raises_even_when_lambda_zero():
    """Fix 4: variant is validated before lam==0 short-circuit (no silent misconfiguration)."""
    with pytest.raises(ValueError):
        team_form_bump([EVEN_WIN], lam=0.0, cap=100.0, variant="bogus")


import pandas as pd
from prediction.form import live_form_bumps

def test_live_form_bumps_empty_when_lambda_zero():
    wc = pd.DataFrame([{"completed": True, "home_team": "A", "away_team": "B",
                        "home_score": 2, "away_score": 0, "kickoff_utc": "2026-06-12T18:00:00+00:00",
                        "date": "2026-06-12"}])
    hist = pd.DataFrame([{"date": pd.Timestamp("2026-06-01"), "team": "A", "elo": 1600.0},
                         {"date": pd.Timestamp("2026-06-01"), "team": "B", "elo": 1500.0}])
    assert live_form_bumps(wc, hist, lam=0.0, cap=100.0, variant="points") == {}

def test_live_form_bumps_nonzero_for_overperformer():
    wc = pd.DataFrame([{"completed": True, "home_team": "A", "away_team": "B",
                        "home_score": 3, "away_score": 0, "kickoff_utc": "2026-06-12T18:00:00+00:00",
                        "date": "2026-06-12"}])
    hist = pd.DataFrame([{"date": pd.Timestamp("2026-06-01"), "team": "A", "elo": 1500.0},
                         {"date": pd.Timestamp("2026-06-01"), "team": "B", "elo": 1500.0}])
    bumps = live_form_bumps(wc, hist, lam=50.0, cap=100.0, variant="points")
    assert bumps["A"] > 0.0 and bumps["B"] < 0.0


def test_live_form_bumps_uses_prematch_elo_not_postmatch():
    """Fix 1: live_form_bumps must use pre-match Elo, not post-match (no same-day lookahead).

    Setup: team A played on 2026-06-12.  Elo history has:
      - pre-match row:  date=2026-06-11  elo=1500  (what the residual should use)
      - post-match row: date=2026-06-12  elo=1600  (same day as the match — must NOT be read)

    Using the post-match elo (1600) would inflate own_elo and reduce the residual.
    Using the pre-match elo (1500) correctly computes the residual from the true
    pre-match expectation.
    """
    from prediction.form import points_residual, match_probabilities

    # Construct elo history with both a pre-match and a post-match row on the match day
    hist = pd.DataFrame([
        {"date": pd.Timestamp("2026-06-11"), "team": "A", "elo": 1500.0},  # pre-match
        {"date": pd.Timestamp("2026-06-12"), "team": "A", "elo": 1600.0},  # post-match (same day as match)
        {"date": pd.Timestamp("2026-06-11"), "team": "B", "elo": 1500.0},
        {"date": pd.Timestamp("2026-06-12"), "team": "B", "elo": 1400.0},
    ])

    wc = pd.DataFrame([{
        "completed": True,
        "home_team": "A",
        "away_team": "B",
        "home_score": 3,
        "away_score": 0,
        "kickoff_utc": "2026-06-12T18:00:00+00:00",
        "date": pd.Timestamp("2026-06-12"),
    }])

    bumps = live_form_bumps(wc, hist, lam=50.0, cap=200.0, variant="points")

    # Compute what the bump SHOULD be using pre-match Elo (1500 vs 1500)
    expected_bump = team_form_bump(
        [{"own_elo": 1500.0, "opp_elo": 1500.0, "home_adv": 0.0, "gf": 3, "ga": 0}],
        lam=50.0, cap=200.0, variant="points"
    )

    # If the buggy kickoff_utc path were used, own_elo would be 1600 (post-match row),
    # yielding a different (smaller) bump because a strong favourite winning is less surprising.
    wrong_bump = team_form_bump(
        [{"own_elo": 1600.0, "opp_elo": 1500.0, "home_adv": 0.0, "gf": 3, "ga": 0}],
        lam=50.0, cap=200.0, variant="points"
    )

    # The correct and wrong bumps differ (this proves the fixture is meaningful)
    assert expected_bump != wrong_bump, "Fixture not discriminating — pre/post Elo must yield different bumps"
    # live_form_bumps must yield the pre-match bump
    assert abs(bumps["A"] - expected_bump) < 1e-6, (
        f"Expected pre-match bump {expected_bump:.4f} but got {bumps['A']:.4f} "
        f"(post-match wrong bump would be {wrong_bump:.4f})"
    )
