import math
import pytest
from prediction.calibration import Calibration, calibrate

P3 = {"win_a": 0.6, "draw": 0.15, "win_b": 0.25}

def test_none_is_identity():
    assert calibrate(P3, None) == P3

def test_identity_params_unchanged():
    assert calibrate(P3, Calibration(1.0, 0.0)) == P3

def test_rows_sum_to_one():
    out = calibrate(P3, Calibration(1.3, 0.4))
    assert abs(sum(out.values()) - 1.0) < 1e-9

def test_temperature_flattens():
    # T>1 moves the max prob down toward uniform
    out = calibrate(P3, Calibration(2.0, 0.0))
    assert out["win_a"] < P3["win_a"]
    assert out["win_a"] > 1/3  # still the favourite, just flatter

def test_delta_lifts_draw():
    out = calibrate(P3, Calibration(1.0, 0.6))
    assert out["draw"] > P3["draw"]
    assert out["win_a"] < P3["win_a"] and out["win_b"] < P3["win_b"]

def test_two_way_ignores_delta():
    p2 = {"win_a": 0.7, "win_b": 0.3}
    a = calibrate(p2, Calibration(1.0, 0.9))
    b = calibrate(p2, Calibration(1.0, 0.0))
    assert a == b  # no "draw" key -> delta has no effect

def test_two_way_temperature():
    p2 = {"win_a": 0.7, "win_b": 0.3}
    out = calibrate(p2, Calibration(2.0, 0.0))
    assert out["win_a"] < 0.7 and abs(sum(out.values()) - 1.0) < 1e-9
