"""Tests for live-tournament conditioning: TournamentState, conditioned MC,
ESPN result parsing, and live scoring."""

import numpy as np
import pandas as pd
import pytest

from config import ALL_TEAMS, GROUPS
from prediction.tournament_simulator import TournamentState, run_monte_carlo

ELO = {t: 1500.0 + 10 * i for i, t in enumerate(sorted(ALL_TEAMS))}

GROUP_A_DONE = [
    ("Mexico", "South Africa", 3, 0),
    ("Mexico", "South Korea", 2, 0),
    ("Mexico", "Czech Republic", 1, 0),
    ("South Korea", "Czech Republic", 1, 1),
    ("South Korea", "South Africa", 2, 0),
    ("Czech Republic", "South Africa", 1, 0),
]


class TestConditionedSimulation:
    def test_completed_group_is_deterministic(self):
        state = TournamentState()
        state.group_played["A"] = GROUP_A_DONE
        df = run_monte_carlo(ELO, n_simulations=500, seed=7, state=state).set_index("team")

        assert df.loc["Mexico", "P(group_advance)"] == 1.0
        assert df.loc["South Korea", "P(group_advance)"] == 1.0
        assert df.loc["South Africa", "P(group_advance)"] == 0.0

    def test_eliminated_team_has_row_with_zeros(self):
        state = TournamentState()
        state.group_played["A"] = GROUP_A_DONE
        df = run_monte_carlo(ELO, n_simulations=200, seed=7, state=state).set_index("team")
        assert df.loc["South Africa", "P(champion)"] == 0.0

    def test_partial_group_shifts_probabilities(self):
        state = TournamentState()
        state.group_played["D"] = [("Brazil", "Haiti", 0, 1)]
        base = run_monte_carlo(ELO, n_simulations=2000, seed=7).set_index("team")
        cond = run_monte_carlo(ELO, n_simulations=2000, seed=7, state=state).set_index("team")

        assert cond.loc["Brazil", "P(group_advance)"] < base.loc["Brazil", "P(group_advance)"]
        assert cond.loc["Haiti", "P(group_advance)"] > base.loc["Haiti", "P(group_advance)"]

    def test_champion_probs_still_sum_to_one(self):
        state = TournamentState()
        state.group_played["A"] = GROUP_A_DONE
        df = run_monte_carlo(ELO, n_simulations=1000, seed=7, state=state)
        assert abs(df["P(champion)"].sum() - 1.0) < 0.01

    def test_known_knockout_winner_is_respected(self):
        # Fix every knockout match Spain plays so Spain always advances
        state = TournamentState()
        spain_wins = {
            frozenset((spain_opponent, "Spain")): "Spain"
            for spain_opponent in ALL_TEAMS if spain_opponent != "Spain"
        }
        for stage in ("r32", "r16", "qf", "sf", "final"):
            state.ko_winners[stage] = dict(spain_wins)

        df = run_monte_carlo(ELO, n_simulations=500, seed=7, state=state).set_index("team")
        # Whenever Spain advances from the group, it wins the title →
        # P(champion) == P(group_advance)
        assert df.loc["Spain", "P(champion)"] == pytest.approx(
            df.loc["Spain", "P(group_advance)"], abs=1e-9
        )

    def test_unconditioned_unchanged(self):
        df_a = run_monte_carlo(ELO, n_simulations=300, seed=11)
        df_b = run_monte_carlo(ELO, n_simulations=300, seed=11, state=None)
        pd.testing.assert_frame_equal(df_a, df_b)


class TestTournamentStateFromResults:
    def _wc_df(self):
        return pd.DataFrame([
            {
                "date": pd.Timestamp("2026-06-11"),
                "kickoff_utc": "2026-06-11T19:00:00+00:00",
                "home_team": "Mexico", "away_team": "South Africa",
                "home_score": 2, "away_score": 1, "winner": "Mexico",
                "completed": True, "status": "STATUS_FINAL",
                "stage": "group", "group": "A",
            },
            {   # scheduled, not completed → must not enter group_played
                "date": pd.Timestamp("2026-06-12"),
                "kickoff_utc": "2026-06-12T02:00:00+00:00",
                "home_team": "South Korea", "away_team": "Czech Republic",
                "home_score": 0, "away_score": 0, "winner": None,
                "completed": False, "status": "STATUS_SCHEDULED",
                "stage": "group", "group": "A",
            },
            {   # knockout with penalty winner
                "date": pd.Timestamp("2026-06-29"),
                "kickoff_utc": "2026-06-29T19:00:00+00:00",
                "home_team": "Spain", "away_team": "France",
                "home_score": 1, "away_score": 1, "winner": "Spain",
                "completed": True, "status": "STATUS_FINAL_PEN",
                "stage": "r32", "group": None,
            },
        ])

    def test_from_results(self):
        state = TournamentState.from_results(self._wc_df(), all_teams=set(ALL_TEAMS))
        assert state.group_played["A"] == [("Mexico", "South Africa", 2, 1)]
        assert state.ko_winners["r32"][frozenset(("Spain", "France"))] == "Spain"
        assert frozenset(("Spain", "France")) in state.ko_fixtures["r32"]

    def test_groups_complete_false_when_partial(self):
        state = TournamentState.from_results(self._wc_df(), all_teams=set(ALL_TEAMS))
        assert not state.groups_complete(GROUPS)


class TestEspnParsing:
    def test_parse_event(self):
        from data.fetcher_wc_results import _parse_event

        event = {
            "date": "2026-06-11T19:00Z",
            "status": {"type": {"name": "STATUS_FINAL", "completed": True}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "winner": True, "score": "2",
                     "team": {"displayName": "Czechia"}},
                    {"homeAway": "away", "score": "0",
                     "team": {"displayName": "South Africa"}},
                ],
            }],
        }
        row = _parse_event(event)
        assert row["home_team"] == "Czech Republic"  # ESPN alias normalized
        assert row["winner"] == "Czech Republic"
        assert row["stage"] == "group"
        assert row["completed"] is True


class TestLiveScoring:
    def test_real_eliminations_knockout_loser(self):
        from evaluation.live_scoring import real_eliminations

        wc_df = pd.DataFrame([{
            "date": pd.Timestamp("2026-06-29"),
            "kickoff_utc": "2026-06-29T19:00:00+00:00",
            "home_team": "Spain", "away_team": "France",
            "home_score": 2, "away_score": 0, "winner": "Spain",
            "completed": True, "status": "STATUS_FINAL",
            "stage": "r32", "group": None,
        }])
        elim = real_eliminations(wc_df)
        assert "France" in elim
        assert "Spain" not in elim

    def test_no_eliminations_during_group_stage(self):
        from evaluation.live_scoring import real_eliminations

        wc_df = pd.DataFrame([{
            "date": pd.Timestamp("2026-06-11"),
            "kickoff_utc": "2026-06-11T19:00:00+00:00",
            "home_team": "Mexico", "away_team": "South Africa",
            "home_score": 5, "away_score": 0, "winner": "Mexico",
            "completed": True, "status": "STATUS_FINAL",
            "stage": "group", "group": "A",
        }])
        assert real_eliminations(wc_df) == {}
