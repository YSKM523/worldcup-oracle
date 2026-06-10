"""Compare AI predictions against Polymarket odds to find edges."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import MIN_EDGE_PCT, STRONG_EDGE_PCT, STRONG_EDGE_MIN_MODELS

log = logging.getLogger(__name__)


def kelly_fraction(ai_prob: float, market_prob: float) -> float:
    """Compute half-Kelly bet fraction.

    Parameters
    ----------
    ai_prob : Our model's estimated probability
    market_prob : Implied probability from the market

    Returns
    -------
    Half-Kelly fraction (0 if no edge or negative edge).
    """
    if market_prob <= 0 or market_prob >= 1 or ai_prob <= 0:
        return 0.0

    # b = decimal odds - 1 = (1/market_prob) - 1
    b = (1.0 / market_prob) - 1.0
    if b <= 0:
        return 0.0

    # Full Kelly: f* = (b*p - q) / b where p = ai_prob, q = 1-ai_prob
    full_kelly = (b * ai_prob - (1.0 - ai_prob)) / b

    # Half-Kelly for safety, floored at 0
    return max(full_kelly / 2.0, 0.0)


def detect_edges(
    ai_probs: dict[str, float],
    market_probs: dict[str, float],
    model_probs: dict[str, dict[str, float]] | None = None,
    min_edge_pct: float = MIN_EDGE_PCT,
    strong_edge_pct: float = STRONG_EDGE_PCT,
    min_models_agree: int = STRONG_EDGE_MIN_MODELS,
) -> pd.DataFrame:
    """Find mispriced markets by comparing AI vs Polymarket probabilities.

    Parameters
    ----------
    ai_probs : {team: P(win)} from our ensemble model
    market_probs : {team: implied_prob} from Polymarket
    model_probs : {model_name: {team: P(win)}} — individual model predictions
        for computing agreement score
    min_edge_pct : Minimum edge (percentage points) to flag
    strong_edge_pct : Threshold for STRONG EDGE flag
    min_models_agree : Minimum models agreeing for STRONG EDGE

    Returns
    -------
    DataFrame of detected edges, sorted by absolute edge descending.
    """
    rows = []

    for team in ai_probs:
        ai_p = ai_probs[team]
        mkt_p = market_probs.get(team, 0.0)

        if mkt_p == 0.0:
            continue  # Team not found in Polymarket

        edge = ai_p - mkt_p
        edge_pct = edge * 100.0

        if abs(edge_pct) < min_edge_pct:
            continue

        # Model agreement: how many individual models agree with the direction
        models_agree = 0
        if model_probs:
            for model_name, mp in model_probs.items():
                model_p = mp.get(team, 0.0)
                if edge > 0 and model_p > mkt_p:
                    models_agree += 1
                elif edge < 0 and model_p < mkt_p:
                    models_agree += 1

        # Kelly sizing
        half_kelly = kelly_fraction(ai_p, mkt_p) if edge > 0 else 0.0

        # Strength classification
        is_strong = (
            abs(edge_pct) >= strong_edge_pct
            and models_agree >= min_models_agree
        )

        rows.append({
            "team": team,
            "ai_prob": round(ai_p, 4),
            "market_prob": round(mkt_p, 4),
            "edge": round(edge, 4),
            "edge_pct": round(edge_pct, 2),
            "direction": "BUY" if edge > 0 else "SELL",
            "half_kelly": round(half_kelly, 4),
            "models_agree": models_agree,
            "strength": "STRONG EDGE" if is_strong else "edge",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("edge_pct", key=abs, ascending=False).reset_index(drop=True)

    return df


def format_edge_report(edges_df: pd.DataFrame, n_models: int = 3) -> str:
    """Format edges as a readable report."""
    if edges_df.empty:
        return "No edges detected above threshold."

    lines = []
    lines.append(f"{'Team':25s} {'AI':>7s} {'Mkt':>7s} {'Edge':>7s} {'Dir':>5s} {'Kelly':>7s} {'Agree':>6s} {'Signal':>12s}")
    lines.append("-" * 85)

    for _, row in edges_df.iterrows():
        lines.append(
            f"{row['team']:25s} "
            f"{row['ai_prob']:6.1%} "
            f"{row['market_prob']:6.1%} "
            f"{row['edge_pct']:+6.1f}% "
            f"{row['direction']:>5s} "
            f"{row['half_kelly']:6.1%} "
            f"{row['models_agree']:5d}/{n_models} "
            f"{row['strength']:>12s}"
        )

    return "\n".join(lines)
