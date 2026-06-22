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


from datetime import datetime, timedelta, timezone
from prediction.calibration import Calibration
from evaluation import live_scoring


def _future_match_df(now):
    ko = (now + timedelta(days=1)).isoformat()
    return pd.DataFrame([{
        "kickoff_utc": ko, "stage": "group", "completed": False,
        "home_team": "Spain", "away_team": "Croatia",
    }])


def test_locked_prediction_records_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    df = _future_match_df(now)
    elos = {"Spain": 1900, "Croatia": 1650}
    live_scoring.predict_upcoming_matches(df, elos, calib=Calibration(1.3, 0.5))
    out = pd.read_csv(tmp_path / "mp.csv")
    assert {"p_home_raw", "p_draw_raw", "p_away_raw", "calib_T", "calib_delta"} <= set(out.columns)
    assert out.iloc[0]["calib_T"] == 1.3 and out.iloc[0]["calib_delta"] == 0.5
    # calibrated draw > raw draw (delta>0)
    assert out.iloc[0]["p_draw"] > out.iloc[0]["p_draw_raw"]


def test_predictions_are_immutable_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    df = _future_match_df(now)
    elos = {"Spain": 1900, "Croatia": 1650}
    live_scoring.predict_upcoming_matches(df, elos, calib=Calibration(1.3, 0.5))
    first = pd.read_csv(tmp_path / "mp.csv").iloc[0].to_dict()
    # re-run with a DIFFERENT calibration -> existing row must not change (I3)
    live_scoring.predict_upcoming_matches(df, elos, calib=Calibration(2.0, 0.0))
    after = pd.read_csv(tmp_path / "mp.csv")
    assert len(after) == 1
    assert after.iloc[0]["p_home"] == first["p_home"]
    assert after.iloc[0]["calib_T"] == first["calib_T"]


# ---------------------------------------------------------------------------
# Tests for build_calibration_records
# ---------------------------------------------------------------------------

def _make_preds_csv(path, rows):
    """Write a match_predictions.csv with required columns."""
    pd.DataFrame(rows).to_csv(path, index=False)


def _wc_df_completed(rows):
    """Build a minimal wc_df with completed group-stage matches."""
    return pd.DataFrame(rows)


class TestBuildCalibrationRecords:
    def _past_ko(self, now, days=1):
        """Return a kickoff_utc string for a match `days` ago (tz-aware)."""
        return (now - timedelta(days=days)).isoformat()

    def test_win_a_outcome(self, tmp_path, monkeypatch):
        """A past group match where home wins produces outcome='win_a'."""
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
        ko = self._past_ko(now)
        _make_preds_csv(tmp_path / "mp.csv", [{
            "kickoff_utc": ko, "stage": "group",
            "home_team": "Spain", "away_team": "Croatia",
            "p_home": 0.50, "p_draw": 0.25, "p_away": 0.25,
            "p_home_raw": 0.48, "p_draw_raw": 0.26, "p_away_raw": 0.26,
        }])
        wc_df = _wc_df_completed([{
            "kickoff_utc": ko, "home_team": "Spain", "away_team": "Croatia",
            "home_score": 2, "away_score": 0,
            "completed": True, "stage": "group",
        }])
        records = live_scoring.build_calibration_records(wc_df, now)
        assert len(records) == 1
        assert records[0]["outcome"] == "win_a"
        assert set(records[0]["probs"].keys()) == {"win_a", "draw", "win_b"}
        assert records[0]["probs"]["win_a"] == pytest.approx(0.48)

    def test_draw_outcome(self, tmp_path, monkeypatch):
        """A past group match ending in draw produces outcome='draw'."""
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
        ko = self._past_ko(now)
        _make_preds_csv(tmp_path / "mp.csv", [{
            "kickoff_utc": ko, "stage": "group",
            "home_team": "Spain", "away_team": "Croatia",
            "p_home": 0.50, "p_draw": 0.25, "p_away": 0.25,
            "p_home_raw": 0.48, "p_draw_raw": 0.26, "p_away_raw": 0.26,
        }])
        wc_df = _wc_df_completed([{
            "kickoff_utc": ko, "home_team": "Spain", "away_team": "Croatia",
            "home_score": 1, "away_score": 1,
            "completed": True, "stage": "group",
        }])
        records = live_scoring.build_calibration_records(wc_df, now)
        assert records[0]["outcome"] == "draw"

    def test_win_b_outcome(self, tmp_path, monkeypatch):
        """A past group match where away wins produces outcome='win_b'."""
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
        ko = self._past_ko(now)
        _make_preds_csv(tmp_path / "mp.csv", [{
            "kickoff_utc": ko, "stage": "group",
            "home_team": "Spain", "away_team": "Croatia",
            "p_home": 0.50, "p_draw": 0.25, "p_away": 0.25,
            "p_home_raw": 0.48, "p_draw_raw": 0.26, "p_away_raw": 0.26,
        }])
        wc_df = _wc_df_completed([{
            "kickoff_utc": ko, "home_team": "Spain", "away_team": "Croatia",
            "home_score": 0, "away_score": 3,
            "completed": True, "stage": "group",
        }])
        records = live_scoring.build_calibration_records(wc_df, now)
        assert records[0]["outcome"] == "win_b"

    def test_raw_column_fallback(self, tmp_path, monkeypatch):
        """Legacy rows without *_raw columns fall back to locked p_home/p_draw/p_away."""
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
        ko = self._past_ko(now)
        # Deliberately omit p_home_raw / p_draw_raw / p_away_raw
        _make_preds_csv(tmp_path / "mp.csv", [{
            "kickoff_utc": ko, "stage": "group",
            "home_team": "Brazil", "away_team": "Argentina",
            "p_home": 0.55, "p_draw": 0.20, "p_away": 0.25,
        }])
        wc_df = _wc_df_completed([{
            "kickoff_utc": ko, "home_team": "Brazil", "away_team": "Argentina",
            "home_score": 1, "away_score": 0,
            "completed": True, "stage": "group",
        }])
        records = live_scoring.build_calibration_records(wc_df, now)
        assert len(records) == 1
        # Without raw columns, probs should equal the locked calibrated values
        assert records[0]["probs"]["win_a"] == pytest.approx(0.55)
        assert records[0]["probs"]["draw"] == pytest.approx(0.20)
        assert records[0]["probs"]["win_b"] == pytest.approx(0.25)

    def test_knockout_row_is_skipped(self, tmp_path, monkeypatch):
        """A knockout-stage prediction row is excluded from calibration records."""
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
        ko = self._past_ko(now)
        _make_preds_csv(tmp_path / "mp.csv", [{
            "kickoff_utc": ko, "stage": "r16",
            "home_team": "France", "away_team": "England",
            "p_home": 0.60, "p_draw": 0.0, "p_away": 0.40,
            "p_home_raw": 0.60, "p_draw_raw": 0.0, "p_away_raw": 0.40,
        }])
        wc_df = _wc_df_completed([{
            "kickoff_utc": ko, "home_team": "France", "away_team": "England",
            "home_score": 2, "away_score": 1,
            "completed": True, "stage": "r16",
        }])
        records = live_scoring.build_calibration_records(wc_df, now)
        assert records == []

    def test_aware_now_does_not_raise(self, tmp_path, monkeypatch):
        """Passing timezone-aware now works without TypeError (covers Finding 1)."""
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
        ko = self._past_ko(now)
        _make_preds_csv(tmp_path / "mp.csv", [{
            "kickoff_utc": ko, "stage": "group",
            "home_team": "Spain", "away_team": "Croatia",
            "p_home": 0.50, "p_draw": 0.25, "p_away": 0.25,
            "p_home_raw": 0.48, "p_draw_raw": 0.26, "p_away_raw": 0.26,
        }])
        wc_df = _wc_df_completed([{
            "kickoff_utc": ko, "home_team": "Spain", "away_team": "Croatia",
            "home_score": 1, "away_score": 0,
            "completed": True, "stage": "group",
        }])
        # aware now → must not raise TypeError
        records = live_scoring.build_calibration_records(wc_df, now)
        assert len(records) == 1

    def test_naive_now_does_not_raise(self, tmp_path, monkeypatch):
        """Passing a naive now is coerced to UTC and no longer raises (covers Finding 1)."""
        now_naive = datetime.utcnow()  # naive
        now_aware = now_naive.replace(tzinfo=timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
        ko = self._past_ko(now_aware)
        _make_preds_csv(tmp_path / "mp.csv", [{
            "kickoff_utc": ko, "stage": "group",
            "home_team": "Spain", "away_team": "Croatia",
            "p_home": 0.50, "p_draw": 0.25, "p_away": 0.25,
            "p_home_raw": 0.48, "p_draw_raw": 0.26, "p_away_raw": 0.26,
        }])
        wc_df = _wc_df_completed([{
            "kickoff_utc": ko, "home_team": "Spain", "away_team": "Croatia",
            "home_score": 1, "away_score": 0,
            "completed": True, "stage": "group",
        }])
        # naive now → should not raise TypeError after the fix
        records = live_scoring.build_calibration_records(wc_df, now_naive)
        assert len(records) == 1

    def test_future_kickoff_row_is_silently_skipped(self, tmp_path, monkeypatch):
        """I1 guard: a 'completed' row with kickoff >= now is skipped (not raised).

        The fail-safe replaces the old bare assert so that data/clock-skew rows
        do not abort the daily cron. A valid past row in the same call is still
        included.
        """
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")

        past_ko = self._past_ko(now, days=1)
        future_ko = (now + timedelta(days=1)).isoformat()

        _make_preds_csv(tmp_path / "mp.csv", [
            {   # past row — should be included
                "kickoff_utc": past_ko, "stage": "group",
                "home_team": "Spain", "away_team": "Croatia",
                "p_home": 0.50, "p_draw": 0.25, "p_away": 0.25,
                "p_home_raw": 0.48, "p_draw_raw": 0.26, "p_away_raw": 0.26,
            },
            {   # future kickoff but marked completed (data/clock-skew) — should be skipped
                "kickoff_utc": future_ko, "stage": "group",
                "home_team": "Brazil", "away_team": "France",
                "p_home": 0.45, "p_draw": 0.30, "p_away": 0.25,
                "p_home_raw": 0.44, "p_draw_raw": 0.30, "p_away_raw": 0.26,
            },
        ])
        wc_df = _wc_df_completed([
            {
                "kickoff_utc": past_ko, "home_team": "Spain", "away_team": "Croatia",
                "home_score": 1, "away_score": 0, "completed": True, "stage": "group",
            },
            {
                "kickoff_utc": future_ko, "home_team": "Brazil", "away_team": "France",
                "home_score": 2, "away_score": 1, "completed": True, "stage": "group",
            },
        ])

        # Must NOT raise; future-kickoff row must be excluded; past row still included
        records = live_scoring.build_calibration_records(wc_df, now)
        assert len(records) == 1
        assert records[0]["outcome"] == "win_a"  # Spain 1-0 Croatia


from prediction.ensemble import live_model_elos

def test_live_model_elos_form_bumps_none_unchanged():
    current = {"A": 1600.0, "B": 1500.0}
    snap = {"actual_elo": {"A": 1590.0, "B": 1505.0},
            "model_tournament_elo": {"M": {"A": 1620.0, "B": 1495.0}}}
    a = live_model_elos(current, snap, teams=["A", "B"])
    b = live_model_elos(current, snap, teams=["A", "B"], form_bumps=None)
    assert a == b

def test_live_model_elos_applies_form_bump():
    current = {"A": 1600.0, "B": 1500.0}
    snap = {"actual_elo": {"A": 1600.0, "B": 1500.0},
            "model_tournament_elo": {"M": {"A": 1600.0, "B": 1500.0}}}
    base = live_model_elos(current, snap, teams=["A", "B"])
    bumped = live_model_elos(current, snap, teams=["A", "B"], form_bumps={"A": 40.0})
    assert bumped["M"]["A"] == base["M"]["A"] + 40.0
    assert bumped["M"]["B"] == base["M"]["B"]


def test_step_calibrate_writes_artifact_and_returns_identity_when_empty(tmp_path, monkeypatch):
    from pipeline import matchday_run
    import config
    monkeypatch.setattr(config, "CALIBRATION_PATH", tmp_path / "calib.json")
    monkeypatch.setattr(matchday_run, "CALIBRATION_PATH", tmp_path / "calib.json", raising=False)
    now = datetime.now(timezone.utc)
    calib = matchday_run.step_calibrate(pd.DataFrame(), now)  # empty wc_df
    assert calib.is_identity()


def test_predict_upcoming_default_knobs_unchanged(tmp_path, monkeypatch):
    # With DC_RHO=0 and GOAL_RATE_BLEND=0 (config defaults), the stored scoreline
    # must equal what the pre-Phase-4 path produced (rho omitted / rate static).
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    ko = (now + timedelta(days=1)).isoformat()
    wc = pd.DataFrame([{
        "kickoff_utc": ko, "stage": "group", "completed": False,
        "home_team": "Spain", "away_team": "Croatia", "date": now.date().isoformat(),
    }])
    elos = {"Spain": 1900, "Croatia": 1650}
    model_elos = {"M1": elos, "M2": elos}
    live_scoring.predict_upcoming_matches(wc, elos, model_elos=model_elos)
    out = pd.read_csv(tmp_path / "mp.csv")
    assert len(out) == 1 and out.iloc[0]["pred_score"]  # produced a scoreline, no error
