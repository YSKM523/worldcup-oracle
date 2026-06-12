"""Convert between probability and odds formats."""

from __future__ import annotations


def prob_to_decimal(prob: float) -> float:
    """Convert probability to decimal odds."""
    if prob <= 0:
        return float("inf")
    return 1.0 / prob


def decimal_to_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    if decimal_odds <= 0:
        return 0.0
    return 1.0 / decimal_odds


def prob_to_american(prob: float) -> float:
    """Convert probability to American odds."""
    if prob <= 0 or prob >= 1:
        return 0.0
    if prob >= 0.5:
        return -(prob / (1 - prob)) * 100
    else:
        return ((1 - prob) / prob) * 100


def american_to_prob(american: float) -> float:
    """Convert American odds to implied probability."""
    if american == 0:
        return 0.0
    if american < 0:
        return abs(american) / (abs(american) + 100)
    else:
        return 100 / (american + 100)


def remove_overround(probs: list[float]) -> list[float]:
    """Normalize probabilities to sum to 1.0 (remove bookmaker vig)."""
    total = sum(probs)
    if total == 0:
        return probs
    return [p / total for p in probs]


def normalize_probs(probs: dict[str, float]) -> dict[str, float]:
    """remove_overround for a {team: prob} dict.

    Polymarket champion prices sum to >1 (overround); AI ensemble probs sum
    to 1. Every AI-vs-market comparison must normalize the market side first
    or edges inherit the vig as a systematic bias.
    """
    total = sum(probs.values())
    if total <= 0:
        return dict(probs)
    return {k: v / total for k, v in probs.items()}
