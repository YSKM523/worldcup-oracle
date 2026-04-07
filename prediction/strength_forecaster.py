"""Level 1: Forecast team Elo trajectories using TSFM models."""

from __future__ import annotations

import gc
import importlib
import logging
import time

import numpy as np

from config import ALL_TEAMS, FOUNDATION_MODELS, TSFM_FORECAST_HORIZON

log = logging.getLogger(__name__)


def forecast_all_teams(
    team_elo_series: dict[str, np.ndarray],
    horizon: int = TSFM_FORECAST_HORIZON,
) -> dict[str, dict[str, dict]]:
    """Run all TSFM models on all 48 teams' Elo histories.

    Memory pattern: load one model → iterate all teams → cleanup → gc.collect.

    Parameters
    ----------
    team_elo_series : {team_name: np.ndarray of weekly Elo values}
    horizon : Number of weeks to forecast forward

    Returns
    -------
    {model_name: {team_name: predict_result_dict}}
    where predict_result_dict has keys: point_forecast, quantile_10, quantile_90
    """
    all_forecasts: dict[str, dict[str, dict]] = {}

    for mod_path, cls_name in FOUNDATION_MODELS:
        log.info("Loading %s …", cls_name)
        module = importlib.import_module(mod_path)
        cls = getattr(module, cls_name)
        model = cls()

        model_name = model.name
        all_forecasts[model_name] = {}

        t_start = time.perf_counter()
        for team in sorted(team_elo_series.keys()):
            history = team_elo_series[team]
            result = model.predict(history, horizon)
            all_forecasts[model_name][team] = result

        elapsed = time.perf_counter() - t_start
        log.info(
            "%s: forecasted %d teams in %.1fs (%.2fs/team)",
            model_name, len(team_elo_series), elapsed,
            elapsed / max(len(team_elo_series), 1),
        )

        model.cleanup()
        del model
        gc.collect()

    return all_forecasts


def get_tournament_elo_forecasts(
    forecasts: dict[str, dict[str, dict]],
    tournament_week_index: int = 10,
) -> dict[str, dict[str, float]]:
    """Extract forecasted Elo at tournament time for each model and team.

    Parameters
    ----------
    forecasts : Output of forecast_all_teams
    tournament_week_index : Which forecast week corresponds to mid-tournament
        (0 = first week of forecast, default 10 = ~10 weeks into forecast)

    Returns
    -------
    {model_name: {team: forecasted_elo_at_tournament}}
    """
    result = {}
    for model_name, team_forecasts in forecasts.items():
        result[model_name] = {}
        for team, pred in team_forecasts.items():
            idx = min(tournament_week_index, len(pred["point_forecast"]) - 1)
            result[model_name][team] = float(pred["point_forecast"][idx])
    return result


def get_tournament_elo_with_uncertainty(
    forecasts: dict[str, dict[str, dict]],
    tournament_week_index: int = 10,
) -> dict[str, dict[str, dict[str, float]]]:
    """Like get_tournament_elo_forecasts but includes uncertainty bounds.

    Returns
    -------
    {model_name: {team: {"point": float, "q10": float, "q90": float}}}
    """
    result = {}
    for model_name, team_forecasts in forecasts.items():
        result[model_name] = {}
        for team, pred in team_forecasts.items():
            idx = min(tournament_week_index, len(pred["point_forecast"]) - 1)
            result[model_name][team] = {
                "point": float(pred["point_forecast"][idx]),
                "q10": float(pred["quantile_10"][idx]),
                "q90": float(pred["quantile_90"][idx]),
            }
    return result
