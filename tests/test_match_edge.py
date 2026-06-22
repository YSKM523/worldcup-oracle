from markets.match_edge import match_edge

AI = {"home": 0.55, "draw": 0.25, "away": 0.20}
# vigged market: sums to 1.08 (raw Yes prices)
MKT_RAW = {"home": 0.45, "draw": 0.28, "away": 0.35}
MODELS = {"m0": {"home": 0.57, "draw": 0.24, "away": 0.19},
          "m1": {"home": 0.54, "draw": 0.25, "away": 0.21},
          "m2": {"home": 0.56, "draw": 0.25, "away": 0.19}}

def test_no_market_returns_empty():
    assert match_edge(AI, None, MODELS, volume=1e6) == []
    assert match_edge(AI, {}, MODELS, volume=1e6) == []

def test_low_volume_returns_empty():
    assert match_edge(AI, MKT_RAW, MODELS, volume=1000) == []  # < MIN_MARKET_VOLUME

def test_devig_before_differencing():
    # de-vigged home = 0.45/1.08 = 0.4167; AI home 0.55 -> edge ~+13.3pp BUY home.
    # If the raw 0.45 were used (no de-vig), edge would be only +10pp.
    out = match_edge(AI, MKT_RAW, MODELS, volume=1e6)
    home = next(e for e in out if e["side"] == "home")
    assert home["direction"] == "BUY"
    assert home["edge_pct"] > 12.0  # de-vigged, not the raw +10pp

def test_models_agree_counted():
    out = match_edge(AI, MKT_RAW, MODELS, volume=1e6)
    home = next(e for e in out if e["side"] == "home")
    assert home["models_agree"] == 3  # all 3 models above the de-vig market on home

def test_sides_keyed_home_draw_away():
    out = match_edge(AI, MKT_RAW, MODELS, volume=1e6)
    assert all(e["side"] in {"home", "draw", "away"} for e in out)
