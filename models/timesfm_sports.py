"""TimesFM 2.5 forecaster adapted for sports Elo time series."""

from __future__ import annotations

import gc
import time

import numpy as np

from models.base import SportForecaster


class TimesFMSportsForecaster(SportForecaster):
    name = "TimesFM-2.5"

    def __init__(self):
        from huggingface_hub import hf_hub_download
        from timesfm import ForecastConfig, TimesFM_2p5_200M_torch

        weights = hf_hub_download(
            "google/timesfm-2.5-200m-pytorch", "model.safetensors"
        )
        self._model = TimesFM_2p5_200M_torch(torch_compile=False)
        self._model.model.load_checkpoint(weights, torch_compile=False)

        fc = ForecastConfig(max_context=512, max_horizon=128)
        self._model.compile(fc)

    def predict(self, history: np.ndarray, horizon: int) -> dict:
        arr = history.astype(np.float64)

        t0 = time.perf_counter()
        points, quantiles = self._model.forecast(horizon, [arr])
        elapsed = time.perf_counter() - t0

        point = points[0]  # shape (horizon,)
        q10 = quantiles[0, :, 0]   # 1st quantile ≈ 0.1
        q90 = quantiles[0, :, -1]  # last quantile ≈ 0.9

        return {
            "point_forecast": point,
            "quantile_10": q10,
            "quantile_90": q90,
            "inference_time_seconds": elapsed,
        }

    def cleanup(self):
        del self._model
        gc.collect()
