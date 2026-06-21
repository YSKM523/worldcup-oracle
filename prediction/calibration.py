"""Walk-forward calibration of match-outcome probabilities (temperature + draw bias).

calibrate() is a pure post-processing layer applied to a probability dict. With
calib=None or identity it returns the input unchanged (graceful degradation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Calibration:
    """Temperature T (overconfidence) + draw-class logit bias delta (draw rate)."""

    T: float = 1.0
    delta: float = 0.0

    def is_identity(self) -> bool:
        return self.T == 1.0 and self.delta == 0.0


def calibrate(probs: dict[str, float], calib: "Calibration | None") -> dict[str, float]:
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
