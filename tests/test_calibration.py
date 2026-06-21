import math
import pytest
from prediction.calibration import Calibration, calibrate, fit_calibration, save_calibration, load_calibration

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


def _records(n_each):
    # synthetic: outcomes drawn to match a known frequency
    recs = []
    base = {"win_a": 0.55, "draw": 0.20, "win_b": 0.25}
    for outcome, n in n_each.items():
        for _ in range(n):
            recs.append({"probs": dict(base), "outcome": outcome})
    return recs


def test_fit_empty_is_identity():
    calib, diag = fit_calibration([], temp_prior=1.5, draw_prior=1.5)
    assert calib.is_identity()
    assert diag["n_wc"] == 0


def test_fit_lifts_delta_when_draws_underpredicted():
    # draws happen 40% but model says 20% -> delta should rise
    recs = _records({"win_a": 30, "draw": 40, "win_b": 30})
    calib, diag = fit_calibration(recs, temp_prior=1.5, draw_prior=1.5)
    assert calib.delta > 0.0
    assert diag["draw_rate_observed"] == pytest.approx(0.40, abs=0.01)
    assert diag["brier_after"] <= diag["brier_before"] + 1e-9


def test_fit_shrinks_toward_identity_with_tiny_n():
    recs = _records({"win_a": 1, "draw": 1, "win_b": 0})
    calib, _ = fit_calibration(recs, temp_prior=50.0, draw_prior=50.0)
    assert abs(calib.T - 1.0) < 0.25 and abs(calib.delta) < 0.25


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "calib.json"
    save_calibration(Calibration(1.2, 0.3), {"n_wc": 5}, p)
    got = load_calibration(p)
    assert got.T == pytest.approx(1.2) and got.delta == pytest.approx(0.3)


def test_load_missing_is_identity(tmp_path):
    assert load_calibration(tmp_path / "nope.json").is_identity()
