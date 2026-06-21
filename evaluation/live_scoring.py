"""Live scoring during the tournament.

Three jobs, run daily by the Phase B pipeline:
1. predict_upcoming_matches — store pre-match probabilities for fixtures in
   the next few days (first prediction wins; never overwritten → no lookahead).
2. score_completed_matches — Brier-score stored predictions against results.
3. update_scoreboard — running AI vs Polymarket comparison on the champion
   market, scored on teams whose elimination is already real.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from config import (
    ALL_TEAMS,
    CACHE_DIR,
    GROUPS,
    HOST_TEAMS,
    RESULTS_DIR,
    WC_HOST_HOME_ADVANTAGE_ELO,
)
from markets.odds_converter import normalize_probs
from prediction.calibration import Calibration, calibrate
from prediction.match_predictor import knockout_probabilities, match_probabilities
from prediction.score_predictor import ensemble_match_prediction

log = logging.getLogger(__name__)

MATCH_PREDS_CSV = RESULTS_DIR / "predictions" / "match_predictions.csv"
MATCH_SCORES_CSV = RESULTS_DIR / "evaluations" / "match_scores.csv"
SCOREBOARD_CSV = RESULTS_DIR / "evaluations" / "scoreboard.csv"
POLYMARKET_ODDS_PARQUET = CACHE_DIR / "polymarket_odds.parquet"

KNOCKOUT_STAGES = ("r32", "r16", "qf", "sf", "third", "final")


def _host_home_advantage(home: str, away: str) -> float:
    """Hosts play home games throughout the group stage (and mostly beyond)."""
    if home in HOST_TEAMS:
        return WC_HOST_HOME_ADVANTAGE_ELO
    if away in HOST_TEAMS:
        return -WC_HOST_HOME_ADVANTAGE_ELO
    return 0.0


def predict_upcoming_matches(
    wc_df: pd.DataFrame,
    elo_ratings: dict[str, float],
    horizon_days: int = 3,
    model_elos: dict[str, dict[str, float]] | None = None,
    calib: Calibration | None = None,
) -> int:
    """Store pre-match probabilities for upcoming fixtures. Returns # added.

    With model_elos (per-model live Elo), probabilities are the model
    ensemble and a most-likely scoreline is stored too; otherwise falls back
    to single-Elo Davidson probs.
    """
    if wc_df is None or wc_df.empty:
        return 0

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=horizon_days)

    existing = pd.read_csv(MATCH_PREDS_CSV) if MATCH_PREDS_CSV.exists() else pd.DataFrame()
    seen = set()
    if not existing.empty:
        seen = set(zip(existing["kickoff_utc"], existing["home_team"], existing["away_team"]))

    rows = []
    for _, r in wc_df.iterrows():
        if r["completed"]:
            continue
        if r["home_team"] not in ALL_TEAMS or r["away_team"] not in ALL_TEAMS:
            continue
        kickoff = datetime.fromisoformat(r["kickoff_utc"])
        if not (now <= kickoff <= horizon):
            continue
        key = (r["kickoff_utc"], r["home_team"], r["away_team"])
        if key in seen:
            continue  # first prediction stands — no revision after the fact

        home, away = r["home_team"], r["away_team"]
        ha = _host_home_advantage(home, away)
        is_ko = r["stage"] in KNOCKOUT_STAGES

        if model_elos:
            elo_pairs = [
                (m.get(home, 1500.0), m.get(away, 1500.0))
                for m in model_elos.values()
            ]
            pred = ensemble_match_prediction(elo_pairs, home_advantage=ha,
                                             knockout=is_ko, calib=calib)
            if is_ko:
                p_home, p_draw, p_away = pred["p_adv_home"], 0.0, pred["p_adv_away"]
                ph_raw, pd_raw, pa_raw = pred["p_adv_home"], 0.0, pred["p_adv_away"]
            else:
                p_home, p_draw, p_away = pred["p_home"], pred["p_draw"], pred["p_away"]
                ph_raw, pd_raw, pa_raw = pred["p_home_raw"], pred["p_draw_raw"], pred["p_away_raw"]
            pred_score = pred["scoreline"]["most_likely"]
            pred_score_p = pred["scoreline"]["most_likely_p"]
        else:
            elo_h = elo_ratings.get(home, 1500.0)
            elo_a = elo_ratings.get(away, 1500.0)
            if is_ko:
                raw = knockout_probabilities(elo_h, elo_a, home_advantage=ha)
                cal = knockout_probabilities(elo_h, elo_a, home_advantage=ha, calib=calib)
                p_home, p_draw, p_away = cal["win_a"], 0.0, cal["win_b"]
                ph_raw, pd_raw, pa_raw = raw["win_a"], 0.0, raw["win_b"]
            else:
                raw = match_probabilities(elo_h, elo_a, home_advantage=ha)
                cal = calibrate(raw, calib)
                p_home, p_draw, p_away = cal["win_a"], cal["draw"], cal["win_b"]
                ph_raw, pd_raw, pa_raw = raw["win_a"], raw["draw"], raw["win_b"]
            pred_score, pred_score_p = None, None

        _cal = calib or Calibration()
        rows.append({
            "predicted_at": now.isoformat(),
            "kickoff_utc": r["kickoff_utc"],
            "stage": r["stage"],
            "home_team": home,
            "away_team": away,
            "p_home": round(p_home, 4),
            "p_draw": round(p_draw, 4),
            "p_away": round(p_away, 4),
            "p_home_raw": round(ph_raw, 4),
            "p_draw_raw": round(pd_raw, 4),
            "p_away_raw": round(pa_raw, 4),
            "calib_T": _cal.T,
            "calib_delta": _cal.delta,
            "pred_score": pred_score,
            "pred_score_p": pred_score_p,
        })

    if rows:
        out = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
        out.to_csv(MATCH_PREDS_CSV, index=False)
        log.info("Stored %d new match predictions.", len(rows))
    return len(rows)


def score_completed_matches(wc_df: pd.DataFrame) -> pd.DataFrame | None:
    """Brier-score stored predictions against completed results (idempotent)."""
    if wc_df is None or wc_df.empty or not MATCH_PREDS_CSV.exists():
        return None

    preds = pd.read_csv(MATCH_PREDS_CSV)
    done = wc_df[wc_df["completed"]]
    if preds.empty or done.empty:
        return None

    merged = preds.merge(
        done[["kickoff_utc", "home_team", "away_team",
              "home_score", "away_score", "winner"]],
        on=["kickoff_utc", "home_team", "away_team"],
        how="inner",
    )
    if merged.empty:
        return None

    rows = []
    for _, r in merged.iterrows():
        if r["stage"] in KNOCKOUT_STAGES:
            # Two-way: scored on the advancing team (covers ET + penalties)
            o_home = 1.0 if r["winner"] == r["home_team"] else 0.0
            brier = (r["p_home"] - o_home) ** 2 + (r["p_away"] - (1 - o_home)) ** 2
        else:
            o_home = 1.0 if r["home_score"] > r["away_score"] else 0.0
            o_draw = 1.0 if r["home_score"] == r["away_score"] else 0.0
            o_away = 1.0 if r["home_score"] < r["away_score"] else 0.0
            brier = (
                (r["p_home"] - o_home) ** 2
                + (r["p_draw"] - o_draw) ** 2
                + (r["p_away"] - o_away) ** 2
            )
        rows.append({
            "kickoff_utc": r["kickoff_utc"],
            "stage": r["stage"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "score": f"{int(r['home_score'])}-{int(r['away_score'])}",
            "p_home": r["p_home"], "p_draw": r["p_draw"], "p_away": r["p_away"],
            "brier": round(float(brier), 4),
        })

    scores = pd.DataFrame(rows).sort_values("kickoff_utc").reset_index(drop=True)
    scores.to_csv(MATCH_SCORES_CSV, index=False)
    log.info(
        "Match scoring: %d matches, mean Brier %.4f "
        "(reference: 0.6667 = uniform 3-way guess)",
        len(scores), scores["brier"].mean(),
    )
    return scores


def build_calibration_records(wc_df: pd.DataFrame, now: datetime) -> list[dict]:
    """WC group records {raw 3-way probs, outcome} for matches kicked off before now.

    Uses RAW probabilities (pre-calibration) so the fit never sees its own output.
    Enforces kickoff_utc < now (I1).
    """
    if wc_df is None or wc_df.empty or not MATCH_PREDS_CSV.exists():
        return []
    preds = pd.read_csv(MATCH_PREDS_CSV)
    done = wc_df[wc_df["completed"]]
    if preds.empty or done.empty:
        return []

    merged = preds.merge(
        done[["kickoff_utc", "home_team", "away_team", "home_score", "away_score"]],
        on=["kickoff_utc", "home_team", "away_team"], how="inner",
    )
    records = []
    for _, r in merged.iterrows():
        if r["stage"] in KNOCKOUT_STAGES:
            continue  # group-only fit (3-way)
        ko = datetime.fromisoformat(r["kickoff_utc"])
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=timezone.utc)
        now_utc = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        if ko >= now_utc:
            log.error("Calibration I1 guard: skipping fit record with kickoff %s >= now %s "
                      "(%s vs %s)", ko, now_utc, r["home_team"], r["away_team"])
            continue
        # RAW probs: legacy rows (locked before this feature) have no *_raw -> raw==locked
        ph = r.get("p_home_raw"); ph = r["p_home"] if pd.isna(ph) else ph
        pdr = r.get("p_draw_raw"); pdr = r["p_draw"] if pd.isna(pdr) else pdr
        pa = r.get("p_away_raw"); pa = r["p_away"] if pd.isna(pa) else pa
        if r["home_score"] > r["away_score"]:
            outcome = "win_a"
        elif r["home_score"] == r["away_score"]:
            outcome = "draw"
        else:
            outcome = "win_b"
        records.append({
            "probs": {"win_a": float(ph), "draw": float(pdr), "win_b": float(pa)},
            "outcome": outcome,
        })
    return records


def real_eliminations(wc_df: pd.DataFrame) -> dict[str, str]:
    """Teams already eliminated by real results → {team: elimination_date}.

    - Loser of any completed knockout match (SF losers can't win the title).
    - After ALL group matches are played: every team outside the 8 best
      thirds + winners + runners.
    """
    out: dict[str, str] = {}
    if wc_df is None or wc_df.empty:
        return out

    done = wc_df[wc_df["completed"]]

    # Knockout losers
    ko = done[done["stage"].isin(("r32", "r16", "qf", "sf", "final"))]
    for _, r in ko.iterrows():
        if not r.get("winner"):
            continue
        loser = r["away_team"] if r["winner"] == r["home_team"] else r["home_team"]
        date = str(r["date"].date() if hasattr(r["date"], "date") else r["date"])
        out.setdefault(loser, date)

    # Group-stage eliminations (only decidable once all 72 group games are in)
    group_done = done[done["stage"] == "group"]
    if len(group_done) >= 72:
        from prediction.tournament_simulator import (
            TournamentState,
            _select_best_third_place,
            _simulate_group,
        )

        state = TournamentState.from_results(wc_df, all_teams=set(ALL_TEAMS))
        rng = np.random.default_rng(0)  # tiebreak only; real ties are rare
        last_group_date = str(group_done["date"].max().date())

        thirds = []
        advancing: set[str] = set()
        for g, teams in GROUPS.items():
            standings = _simulate_group(teams, {}, rng, played=state.group_played.get(g, []))
            advancing.add(standings[0][0])
            advancing.add(standings[1][0])
            t3 = standings[2]
            thirds.append((t3[0], t3[1], t3[2], t3[3], g))

        advancing |= set(_select_best_third_place(thirds, rng))
        for team in ALL_TEAMS:
            if team not in advancing:
                out.setdefault(team, last_group_date)

    return out


def update_scoreboard(wc_df: pd.DataFrame) -> pd.DataFrame | None:
    """Running AI-vs-Polymarket Brier comparison on the champion market.

    For every team whose elimination is real, every earlier daily snapshot of
    P(champion) resolves to outcome 0. Compare AI's resolved Brier against
    Polymarket's on exactly the same (team, date) pairs.
    """
    eliminated = real_eliminations(wc_df)
    if not eliminated:
        log.info("Scoreboard: no real eliminations yet — nothing to resolve.")
        return None

    # Daily AI champion probs
    ai_by_date: dict[str, dict[str, float]] = {}
    for f in sorted((RESULTS_DIR / "predictions").glob("predictions_*.csv")):
        date = f.stem.replace("predictions_", "")
        df = pd.read_csv(f)
        ai_by_date[date] = dict(zip(df["team"], df["ai_prob"]))

    # Daily Polymarket champion probs
    if not POLYMARKET_ODDS_PARQUET.exists():
        return None
    pm = pd.read_parquet(POLYMARKET_ODDS_PARQUET)
    pm["date"] = pd.to_datetime(pm["timestamp"]).dt.strftime("%Y-%m-%d")
    # De-vig per snapshot so the Brier comparison is AI(sum=1) vs PM(sum=1)
    pm_by_date = {
        d: normalize_probs(dict(zip(g["team"], g["implied_prob"])))
        for d, g in pm.groupby("date")
    }

    rows = []
    for team, elim_date in eliminated.items():
        for date, ai_probs in ai_by_date.items():
            if date > elim_date or date not in pm_by_date:
                continue
            ai_p = ai_probs.get(team)
            pm_p = pm_by_date[date].get(team)
            if ai_p is None or pm_p is None:
                continue
            rows.append({
                "team": team,
                "snapshot_date": date,
                "eliminated_on": elim_date,
                "ai_prob": ai_p,
                "pm_prob": pm_p,
                "ai_brier": round(float(ai_p) ** 2, 6),
                "pm_brier": round(float(pm_p) ** 2, 6),
            })

    if not rows:
        return None

    board = pd.DataFrame(rows)
    board.to_csv(SCOREBOARD_CSV, index=False)

    ai_total = board["ai_brier"].mean()
    pm_total = board["pm_brier"].mean()
    leader = "AI" if ai_total < pm_total else "Polymarket"
    log.info(
        "Scoreboard: %d resolved (team,day) pairs | AI Brier %.5f vs PM %.5f → %s leads",
        len(board), ai_total, pm_total, leader,
    )
    return board
