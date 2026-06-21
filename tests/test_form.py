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
