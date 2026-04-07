"""Abstract base class for sports forecasters."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class SportForecaster(ABC):
    """Base class for time series foundation model wrappers.

    Each model predicts a team's Elo trajectory forward in time.
    Interface mirrors fin-forecast-arena for consistency.

    Returns
    -------
    dict with keys:
        point_forecast : np.ndarray of shape (horizon,)
        quantile_10    : np.ndarray of shape (horizon,)
        quantile_90    : np.ndarray of shape (horizon,)
        inference_time_seconds : float
    """

    name: str

    @abstractmethod
    def predict(self, history: np.ndarray, horizon: int) -> dict:
        ...

    @abstractmethod
    def cleanup(self) -> None:
        ...
