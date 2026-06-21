"""Walk-forward calibration of match-outcome probabilities (temperature + draw bias).

calibrate() is a pure post-processing layer applied to a probability dict. With
calib=None or identity it returns the input unchanged (graceful degradation).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Calibration:
    """Temperature T (overconfidence) + draw-class logit bias delta (draw rate)."""

    T: float = 1.0
    delta: float = 0.0

    def is_identity(self) -> bool:
        return self.T == 1.0 and self.delta == 0.0


def calibrate(probs: dict[str, float], calib: Calibration | None) -> dict[str, float]:
    """Apply temperature + draw-bias calibration.

    probs : {"win_a","draw","win_b"} (3-way) or {"win_a","win_b"} (2-way).
            For 2-way, delta has no effect (no "draw" key).
    """
    if calib is None or calib.is_identity():
        return probs

    eps = 1e-12
    logits = {k: math.log(max(v, eps)) / calib.T for k, v in probs.items()}
    if "draw" in logits:
        logits["draw"] += calib.delta

    m = max(logits.values())
    exps = {k: math.exp(v - m) for k, v in logits.items()}
    z = sum(exps.values())
    return {k: e / z for k, e in exps.items()}


_OUTCOMES = ("win_a", "draw", "win_b")


def _brier3(p: dict[str, float], outcome: str) -> float:
    return sum((p[k] - (1.0 if k == outcome else 0.0)) ** 2 for k in _OUTCOMES)


def _mean_brier(records, calib: Calibration) -> float:
    if not records:
        return 0.0
    return sum(_brier3(calibrate(r["probs"], calib), r["outcome"]) for r in records) / len(records)


def fit_calibration(records, *, temp_prior: float, draw_prior: float):
    """Fit (T, delta) on WC group records minimising mean Brier + identity priors.

    records: [{"probs": {win_a,draw,win_b}, "outcome": one of them}]. Empty -> identity.
    Returns (Calibration, diagnostics).
    """
    n = len(records)
    if n == 0:
        return Calibration(), {
            "n_wc": 0, "T": 1.0, "delta": 0.0,
            "draw_rate_observed": None, "draw_rate_predicted_raw": None,
            "brier_before": None, "brier_after": None,
            "in_sample_fit_diagnostic": True,
        }

    from scipy.optimize import minimize

    def loss(x):
        T, delta = float(x[0]), float(x[1])
        if T <= 0.0:
            return 1e9
        c = Calibration(T=T, delta=delta)
        mean_brier = _mean_brier(records, c)
        reg = (temp_prior * (T - 1.0) ** 2 + draw_prior * delta ** 2) / n
        return mean_brier + reg

    res = minimize(loss, x0=[1.0, 0.0], method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 2000})
    calib = Calibration(T=float(res.x[0]), delta=float(res.x[1]))

    draw_obs = sum(1 for r in records if r["outcome"] == "draw") / n
    draw_pred = sum(r["probs"]["draw"] for r in records) / n
    diag = {
        "n_wc": n,
        "T": round(calib.T, 4),
        "delta": round(calib.delta, 4),
        "draw_rate_observed": round(draw_obs, 4),
        "draw_rate_predicted_raw": round(draw_pred, 4),
        "brier_before": round(_mean_brier(records, Calibration()), 4),
        "brier_after": round(_mean_brier(records, calib), 4),
        "in_sample_fit_diagnostic": True,
    }
    return calib, diag


def save_calibration(calib: Calibration, diagnostics: dict, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(diagnostics)
    payload["T"] = calib.T
    payload["delta"] = calib.delta
    path.write_text(json.dumps(payload, indent=2))


def load_calibration(path) -> Calibration:
    path = Path(path)
    if not path.exists():
        return Calibration()
    try:
        d = json.loads(path.read_text())
        return Calibration(T=float(d["T"]), delta=float(d["delta"]))
    except (ValueError, KeyError, OSError):
        return Calibration()
