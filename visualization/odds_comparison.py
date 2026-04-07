"""Visualizations comparing AI predictions vs Polymarket odds."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import PLOTS_DIR

log = logging.getLogger(__name__)


def plot_scatter(
    ai_probs: dict[str, float],
    market_probs: dict[str, float],
    title: str = "AI vs Polymarket — 2026 World Cup Winner",
    save_path: Path | None = None,
) -> None:
    """Scatter plot: AI probability (Y) vs Polymarket probability (X).

    Points above the diagonal = AI thinks undervalued by market.
    """
    teams = sorted(set(ai_probs.keys()) & set(market_probs.keys()))

    x = [market_probs[t] for t in teams]
    y = [ai_probs[t] for t in teams]
    edges = [ai_probs[t] - market_probs[t] for t in teams]

    fig, ax = plt.subplots(figsize=(10, 10))

    # 45-degree agreement line
    max_val = max(max(x), max(y)) * 1.1
    ax.plot([0, max_val], [0, max_val], "k--", alpha=0.3, label="Perfect agreement")

    # Color by edge magnitude
    scatter = ax.scatter(
        x, y,
        c=edges,
        cmap="RdYlGn",
        s=80,
        alpha=0.8,
        edgecolors="black",
        linewidths=0.5,
        vmin=-0.1,
        vmax=0.1,
    )

    # Label top teams
    for team, xi, yi in zip(teams, x, y):
        if xi > 0.02 or yi > 0.02 or abs(yi - xi) > 0.03:
            ax.annotate(
                team,
                (xi, yi),
                fontsize=7,
                ha="left",
                va="bottom",
                xytext=(4, 4),
                textcoords="offset points",
            )

    plt.colorbar(scatter, label="Edge (AI − Market)", shrink=0.8)

    ax.set_xlabel("Polymarket Implied Probability", fontsize=12)
    ax.set_ylabel("AI Model Probability", fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.set_xlim(-0.005, max_val)
    ax.set_ylim(-0.005, max_val)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)

    plt.tight_layout()

    if save_path is None:
        save_path = PLOTS_DIR / "ai_vs_polymarket_scatter.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Scatter plot saved to %s", save_path)


def plot_top_edges_bar(
    edges_df: pd.DataFrame,
    n_teams: int = 15,
    save_path: Path | None = None,
) -> None:
    """Horizontal bar chart of top edges by absolute magnitude."""
    if edges_df.empty:
        return

    top = edges_df.head(n_teams).copy()
    top = top.iloc[::-1]  # Reverse for bottom-up display

    fig, ax = plt.subplots(figsize=(10, 8))

    colors = ["#2ecc71" if d == "BUY" else "#e74c3c" for d in top["direction"]]

    bars = ax.barh(top["team"], top["edge_pct"], color=colors, edgecolor="black", linewidth=0.5)

    # Add value labels
    for bar, val in zip(bars, top["edge_pct"]):
        x_pos = bar.get_width()
        ha = "left" if x_pos >= 0 else "right"
        ax.text(
            x_pos + (0.2 if x_pos >= 0 else -0.2),
            bar.get_y() + bar.get_height() / 2,
            f"{val:+.1f}%",
            va="center",
            ha=ha,
            fontsize=9,
            fontweight="bold",
        )

    ax.set_xlabel("Edge (AI − Polymarket) in percentage points", fontsize=12)
    ax.set_title("Biggest Disagreements: AI Model vs Polymarket", fontsize=14)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.grid(True, axis="x", alpha=0.2)

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#2ecc71", label="BUY (AI > Market)"),
        Patch(facecolor="#e74c3c", label="SELL (AI < Market)"),
    ]
    ax.legend(handles=legend_elements, loc="lower right")

    plt.tight_layout()

    if save_path is None:
        save_path = PLOTS_DIR / "top_edges_bar.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Edge bar chart saved to %s", save_path)


def plot_side_by_side(
    ai_probs: dict[str, float],
    market_probs: dict[str, float],
    n_teams: int = 15,
    save_path: Path | None = None,
) -> None:
    """Side-by-side bar chart: AI vs Polymarket for top N teams."""
    # Sort by AI probability
    sorted_teams = sorted(ai_probs.items(), key=lambda x: x[1], reverse=True)[:n_teams]
    teams = [t for t, _ in sorted_teams]

    ai_vals = [ai_probs[t] * 100 for t in teams]
    mkt_vals = [market_probs.get(t, 0) * 100 for t in teams]

    fig, ax = plt.subplots(figsize=(12, 8))

    x = np.arange(len(teams))
    width = 0.35

    bars1 = ax.bar(x - width / 2, ai_vals, width, label="AI Model", color="#3498db", edgecolor="black", linewidth=0.5)
    bars2 = ax.bar(x + width / 2, mkt_vals, width, label="Polymarket", color="#e67e22", edgecolor="black", linewidth=0.5)

    ax.set_xlabel("Team", fontsize=12)
    ax.set_ylabel("Win Probability (%)", fontsize=12)
    ax.set_title("AI Model vs Polymarket — Top 15 Teams", fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(teams, rotation=45, ha="right", fontsize=9)
    ax.legend()
    ax.grid(True, axis="y", alpha=0.2)

    plt.tight_layout()

    if save_path is None:
        save_path = PLOTS_DIR / "ai_vs_polymarket_side_by_side.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Side-by-side chart saved to %s", save_path)
