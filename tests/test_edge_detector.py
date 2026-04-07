"""Tests for edge detection and Kelly criterion."""

import sys
sys.path.insert(0, ".")

import pytest
import numpy as np

from markets.edge_detector import kelly_fraction, detect_edges


class TestKellyFraction:
    def test_no_edge_returns_zero(self):
        # AI agrees with market: no edge
        assert kelly_fraction(0.10, 0.10) == 0.0

    def test_negative_edge_returns_zero(self):
        # AI thinks less likely than market
        assert kelly_fraction(0.05, 0.10) == 0.0

    def test_positive_edge_returns_positive(self):
        # AI thinks more likely than market
        f = kelly_fraction(0.15, 0.10)
        assert f > 0.0

    def test_half_kelly_is_half(self):
        # Full Kelly for these values: (b*p - q) / b
        # b = (1/0.10) - 1 = 9
        # full = (9*0.20 - 0.80) / 9 = (1.8 - 0.8) / 9 = 0.1111
        # half = 0.0556
        f = kelly_fraction(0.20, 0.10)
        assert abs(f - 0.0556) < 0.001

    def test_zero_market_prob(self):
        assert kelly_fraction(0.10, 0.0) == 0.0

    def test_one_market_prob(self):
        assert kelly_fraction(0.50, 1.0) == 0.0


class TestDetectEdges:
    def test_no_edges_when_equal(self):
        ai = {"A": 0.10, "B": 0.20}
        mkt = {"A": 0.10, "B": 0.20}
        edges = detect_edges(ai, mkt, min_edge_pct=1.0)
        assert len(edges) == 0

    def test_detects_positive_edge(self):
        ai = {"A": 0.20}
        mkt = {"A": 0.10}
        edges = detect_edges(ai, mkt, min_edge_pct=3.0)
        assert len(edges) == 1
        assert edges.iloc[0]["direction"] == "BUY"
        assert edges.iloc[0]["edge_pct"] == pytest.approx(10.0, abs=0.1)

    def test_detects_negative_edge(self):
        ai = {"A": 0.05}
        mkt = {"A": 0.15}
        edges = detect_edges(ai, mkt, min_edge_pct=3.0)
        assert len(edges) == 1
        assert edges.iloc[0]["direction"] == "SELL"

    def test_min_edge_filter(self):
        ai = {"A": 0.11}
        mkt = {"A": 0.10}
        edges = detect_edges(ai, mkt, min_edge_pct=3.0)
        assert len(edges) == 0  # 1% edge below 3% threshold

    def test_strong_edge_flag(self):
        ai = {"A": 0.20}
        mkt = {"A": 0.10}
        model_probs = {
            "M1": {"A": 0.18},
            "M2": {"A": 0.22},
            "M3": {"A": 0.19},
            "M4": {"A": 0.15},
        }
        edges = detect_edges(
            ai, mkt, model_probs=model_probs,
            min_edge_pct=3.0, strong_edge_pct=5.0, min_models_agree=3,
        )
        assert edges.iloc[0]["strength"] == "STRONG EDGE"

    def test_sorted_by_absolute_edge(self):
        ai = {"A": 0.15, "B": 0.05, "C": 0.30}
        mkt = {"A": 0.10, "B": 0.15, "C": 0.10}
        edges = detect_edges(ai, mkt, min_edge_pct=3.0)
        edge_pcts = edges["edge_pct"].abs().tolist()
        assert edge_pcts == sorted(edge_pcts, reverse=True)
