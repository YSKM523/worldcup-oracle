import importlib.util
import math
import unittest
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_script(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class KalshiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script("01_fetch_kalshi.py", "fetch_kalshi")

    def test_target_times_move_early_kickoff_lock_to_previous_day(self):
        lock, ko = self.mod.target_times("2026-06-12T02:00:00+00:00")
        self.assertEqual(lock.isoformat(), "2026-06-11T06:10:00+00:00")
        self.assertEqual(ko.isoformat(), "2026-06-12T01:55:00+00:00")

    def test_kalshi_leg_classifier_strips_reg_time_prefix(self):
        self.assertEqual(
            self.mod.classify_leg("Reg Time: Belgium", "Belgium", "Portugal"),
            "home",
        )
        self.assertEqual(
            self.mod.classify_leg("Tie", "Belgium", "Portugal"), "draw"
        )

    def test_short_country_alias_does_not_collide_with_australia(self):
        self.assertEqual(
            self.mod.classify_leg("Australia", "United States", "Australia"),
            "away",
        )

    def test_candle_selection_uses_mid_then_close_fallback(self):
        candles = [
            {
                "end_period_ts": 100,
                "price": {"close_dollars": "0.40"},
                "yes_bid": {"close_dollars": "0.38"},
                "yes_ask": {"close_dollars": "0.42"},
            },
            {
                "end_period_ts": 200,
                "price": {"close_dollars": "0.55"},
                "yes_bid": {"close_dollars": "0.00"},
                "yes_ask": {"close_dollars": None},
            },
        ]
        self.assertEqual(self.mod.select_candle(candles, 150)["mid"], 0.40)
        self.assertEqual(self.mod.select_candle(candles, 250)["mid"], 0.55)


class PolymarketContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script("02_fetch_polymarket.py", "fetch_pm")

    def test_market_classifier_handles_draw_and_team_questions(self):
        self.assertEqual(
            self.mod.classify_market(
                {"question": "Will Mexico vs South Africa end in a draw?"},
                "Mexico",
                "South Africa",
            ),
            "draw",
        )
        self.assertEqual(
            self.mod.classify_market(
                {"groupItemTitle": "South Africa"}, "Mexico", "South Africa"
            ),
            "away",
        )

    def test_history_selection_takes_last_price_not_after_target(self):
        history = [{"t": 50, "p": 0.2}, {"t": 90, "p": 0.4}, {"t": 110, "p": 0.8}]
        self.assertEqual(self.mod.select_price(history, 100), {"ts": 90, "price": 0.4})

    def test_event_match_rejects_props_and_allows_recorded_one_hour_offset(self):
        match = {
            "home": "Mexico",
            "away": "Ecuador",
            "kickoff_utc": "2026-07-01T02:00:00+00:00",
        }
        moneyline = {
            "title": "Mexico vs. Ecuador",
            "endDate": "2026-07-01T01:00:00Z",
            "markets": [{}, {}, {}],
        }
        props = {
            "title": "Mexico vs. Ecuador - Exact Score",
            "endDate": "2026-07-01T02:00:00Z",
            "markets": [{}, {}, {}],
        }
        self.assertTrue(self.mod.event_matches(moneyline, match))
        self.assertFalse(self.mod.event_matches(props, match))


class AnalysisContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script("03_analyze.py", "analyze_accuracy")

    def test_probability_normalization_and_scores(self):
        p, raw_sum = self.mod.normalize_probs([0.5, 0.3, 0.3])
        self.assertTrue(math.isclose(sum(p), 1.0, abs_tol=1e-12))
        self.assertEqual(raw_sum, 1.1)
        self.assertTrue(math.isclose(self.mod.brier(p, "home"), sum((a-b)**2 for a,b in zip(p,[1,0,0]))))
        self.assertTrue(math.isclose(self.mod.log_loss(p, "home"), -math.log(p[0])))

    def test_missing_ledger_is_exclusive_with_documented_precedence(self):
        category, reasons = self.mod.coverage_category(
            has_kalshi=False,
            has_pm=False,
            has_ai=False,
            prices_complete=False,
        )
        self.assertEqual(category, "缺 Kalshi")
        self.assertEqual(set(reasons), {"缺 Kalshi", "缺 PM", "缺 AI locked", "价格时刻无数据"})


if __name__ == "__main__":
    unittest.main()
