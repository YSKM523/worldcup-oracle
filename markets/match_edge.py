"""Per-match (W/D/L) edge: de-vig the Polymarket 3-way, then reuse detect_edges.

market_raw holds raw Yes prices (implied probs summing to >1 with vig); it is
de-vigged with normalize_probs before differencing so edges don't inherit the
vig. Returns [] when no market or the book is below the liquidity floor — it
never fabricates a market.
"""

from __future__ import annotations

from config import MIN_MARKET_VOLUME
from markets.edge_detector import detect_edges
from markets.odds_converter import normalize_probs


def match_edge(ai_probs, market_raw, model_probs=None, volume=0.0, min_edge_pct=2.0):
    if not market_raw or volume < MIN_MARKET_VOLUME:
        return []
    market_devig = normalize_probs({
        "home": market_raw["home"], "draw": market_raw["draw"], "away": market_raw["away"],
    })
    edges = detect_edges(ai_probs, market_devig, model_probs, min_edge_pct=min_edge_pct)
    return [
        {
            "side": row["team"],
            "edge_pct": row["edge_pct"],
            "direction": row["direction"],
            "half_kelly": row["half_kelly"],
            "models_agree": int(row["models_agree"]),
            "strength": row["strength"],
        }
        for _, row in edges.iterrows()
    ]
