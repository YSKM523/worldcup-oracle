"""Team Elo trajectory + TSFM forecast fan charts."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import PLOTS_DIR

log = logging.getLogger(__name__)


def plot_team_elo_forecast(
    team: str,
    elo_history: pd.Series,
    forecasts: dict[str, dict],
    save_path: Path | None = None,
) -> None:
    """Plot historical Elo + TSFM forecasts with uncertainty bands.

    Parameters
    ----------
    team : Team name
    elo_history : Weekly Elo Series with DatetimeIndex
    forecasts : {model_name: {"point_forecast": array, "quantile_10": array, "quantile_90": array}}
    """
    fig, ax = plt.subplots(figsize=(14, 6))

    # Historical Elo
    ax.plot(elo_history.index, elo_history.values, "k-", linewidth=1.5, label="Historical Elo")

    # Forecast period
    last_date = elo_history.index[-1]
    colors = {"Chronos-2": "#e74c3c", "TimesFM-2.5": "#3498db", "FlowState": "#2ecc71"}

    for model_name, pred in forecasts.items():
        horizon = len(pred["point_forecast"])
        forecast_dates = pd.date_range(
            last_date + pd.Timedelta(weeks=1), periods=horizon, freq="W"
        )

        color = colors.get(model_name, "#999999")
        ax.plot(
            forecast_dates,
            pred["point_forecast"],
            color=color,
            linewidth=1.5,
            label=f"{model_name} forecast",
        )
        ax.fill_between(
            forecast_dates,
            pred["quantile_10"],
            pred["quantile_90"],
            color=color,
            alpha=0.15,
        )

    # Tournament window
    ax.axvspan(
        pd.Timestamp("2026-06-11"),
        pd.Timestamp("2026-07-19"),
        alpha=0.08,
        color="gold",
        label="Tournament window",
    )

    ax.set_xlabel("Date", fontsize=11)
    ax.set_ylabel("Elo Rating", fontsize=11)
    ax.set_title(f"{team} — Elo Trajectory + TSFM Forecasts", fontsize=14)
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, alpha=0.2)

    plt.tight_layout()

    if save_path is None:
        save_path = PLOTS_DIR / f"elo_forecast_{team.replace(' ', '_')}.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_multi_team_form(
    teams: list[str],
    elo_histories: dict[str, pd.Series],
    save_path: Path | None = None,
) -> None:
    """Plot Elo trajectories for multiple teams on one chart."""
    fig, ax = plt.subplots(figsize=(14, 8))

    for team in teams:
        if team in elo_histories:
            series = elo_histories[team]
            # Only plot last 2 years for readability
            recent = series.iloc[-104:]
            ax.plot(recent.index, recent.values, linewidth=1.5, label=team)

    ax.set_xlabel("Date", fontsize=11)
    ax.set_ylabel("Elo Rating", fontsize=11)
    ax.set_title("Team Elo Trajectories — Last 2 Years", fontsize=14)
    ax.legend(fontsize=9, ncol=2)
    ax.grid(True, alpha=0.2)

    plt.tight_layout()

    if save_path is None:
        save_path = PLOTS_DIR / "multi_team_elo.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Multi-team Elo chart saved to %s", save_path)
