"""FlowState (IBM Granite) forecaster adapted for sports Elo time series."""

from __future__ import annotations

import gc
import time

import numpy as np
import torch

from models.base import SportForecaster


class FlowStateSportsForecaster(SportForecaster):
    name = "FlowState"

    def __init__(self):
        from tsfm_public import FlowStateForPrediction

        self._model = FlowStateForPrediction.from_pretrained(
            "ibm-granite/granite-timeseries-flowstate-r1"
        ).to("cpu")

    def predict(self, history: np.ndarray, horizon: int) -> dict:
        ts = (
            torch.tensor(history, dtype=torch.float32)
            .unsqueeze(-1)   # (context, 1)
            .unsqueeze(1)    # (context, 1, 1) — batch_first=False expects (T, B, C)
        )

        t0 = time.perf_counter()
        out = self._model(
            ts, scale_factor=1.0, prediction_length=horizon, batch_first=False
        )
        elapsed = time.perf_counter() - t0

        # out.prediction_outputs: (batch, horizon, channels)
        point = out.prediction_outputs[0, :, 0].detach().numpy()

        # out.quantile_outputs: (batch, n_quantiles, horizon, channels)
        # 9 quantiles: 0.1, 0.2, ..., 0.9
        q10 = out.quantile_outputs[0, 0, :, 0].detach().numpy()  # 0.1
        q90 = out.quantile_outputs[0, -1, :, 0].detach().numpy()  # 0.9

        return {
            "point_forecast": point,
            "quantile_10": q10,
            "quantile_90": q90,
            "inference_time_seconds": elapsed,
        }

    def cleanup(self):
        del self._model
        gc.collect()
