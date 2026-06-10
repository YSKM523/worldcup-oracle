"""Build the static prediction dashboard (dashboard/data.json).

Reads pipeline outputs already on disk (Elo cache, TSFM snapshot, daily
champion predictions / sims / edges, locked match predictions, scores) plus
the ESPN schedule, and emits one JSON blob consumed by dashboard/index.html.

Run standalone:  PYTHONPATH=. venv/bin/python -m visualization.dashboard
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import (
    ALL_TEAMS,
    CACHE_DIR,
    GROUPS,
    RESULTS_DIR,
    ROOT,
)
from data.elo import ELO_PARQUET, get_latest_elo
from evaluation.live_scoring import KNOCKOUT_STAGES, _host_home_advantage
from prediction.ensemble import live_model_elos
from prediction.score_predictor import ensemble_match_prediction

log = logging.getLogger(__name__)

DASHBOARD_DIR = ROOT / "dashboard"
SNAPSHOT_PATH = RESULTS_DIR / "predictions" / "model_snapshot_latest.json"
MATCH_PREDS_CSV = RESULTS_DIR / "predictions" / "match_predictions.csv"
MATCH_SCORES_CSV = RESULTS_DIR / "evaluations" / "match_scores.csv"
SCOREBOARD_CSV = RESULTS_DIR / "evaluations" / "scoreboard.csv"
PM_ODDS_PARQUET = CACHE_DIR / "polymarket_odds.parquet"

PAGES_PROJECT = "worldcup-oracle"


# ── Input loading ────────────────────────────────────────────────────────────
def _load_wc_df(wc_df: pd.DataFrame | None) -> pd.DataFrame:
    if wc_df is not None and not wc_df.empty:
        return wc_df
    from data.fetcher_wc_results import WC_RESULTS_PARQUET, fetch_wc_results

    # The cache is fresh right after a pipeline run; refetch only when the
    # schema is missing the schedule fields (espn_id) or the file is absent.
    if WC_RESULTS_PARQUET.exists():
        cached = pd.read_parquet(WC_RESULTS_PARQUET)
        if "espn_id" in cached.columns:
            return cached
    return fetch_wc_results(force=True)


def _latest(glob_pattern: str) -> tuple[str, pd.DataFrame] | None:
    files = sorted((RESULTS_DIR).glob(glob_pattern))
    if not files:
        return None
    f = files[-1]
    date = f.stem.rsplit("_", 1)[-1]
    return date, pd.read_csv(f)


def _load_model_sims() -> tuple[str | None, dict[str, pd.DataFrame]]:
    """Latest per-model simulation results {model: stage-prob frame}."""
    files = sorted((RESULTS_DIR / "simulations").glob("sim_*.csv"))
    if not files:
        return None, {}
    latest_date = max(f.stem.rsplit("_", 1)[-1] for f in files)
    sims = {}
    for f in files:
        if f.stem.endswith(latest_date):
            model = f.stem[len("sim_"):-len(latest_date) - 1]
            sims[model] = pd.read_csv(f)
    return latest_date, sims


# ── Sections ─────────────────────────────────────────────────────────────────
def _build_matches(
    wc_df: pd.DataFrame,
    model_elos: dict[str, dict[str, float]],
    ens_elo: dict[str, float],
) -> list[dict]:
    locked = pd.read_csv(MATCH_PREDS_CSV) if MATCH_PREDS_CSV.exists() else pd.DataFrame()
    locked_by_key: dict[tuple, dict] = {}
    if not locked.empty:
        for _, r in locked.iterrows():
            locked_by_key[(r["kickoff_utc"], r["home_team"], r["away_team"])] = r.to_dict()

    scores = pd.read_csv(MATCH_SCORES_CSV) if MATCH_SCORES_CSV.exists() else pd.DataFrame()
    brier_by_key = {}
    if not scores.empty:
        for _, r in scores.iterrows():
            brier_by_key[(r["kickoff_utc"], r["home_team"], r["away_team"])] = float(r["brier"])

    out = []
    for _, r in wc_df.sort_values("kickoff_utc").iterrows():
        home, away = r["home_team"], r["away_team"]
        known = home in ALL_TEAMS and away in ALL_TEAMS
        completed = bool(r["completed"])
        row = {
            "espn_id": str(r.get("espn_id", "") or ""),
            "kickoff_utc": r["kickoff_utc"],
            "stage": r["stage"],
            "group": r.get("group") if pd.notna(r.get("group")) else None,
            "venue": r.get("venue") if pd.notna(r.get("venue")) else None,
            "city": r.get("venue_city") if pd.notna(r.get("venue_city")) else None,
            "home": home,
            "away": away,
            "tbd": not known,
            "completed": completed,
            "status": r.get("status"),
            "home_score": int(r["home_score"]) if completed else None,
            "away_score": int(r["away_score"]) if completed else None,
            "winner": r.get("winner") if completed and pd.notna(r.get("winner")) else None,
        }

        # Fresh prediction for any match not yet played (today's view)
        if known and not completed:
            ha = _host_home_advantage(home, away)
            is_ko = r["stage"] in KNOCKOUT_STAGES
            elo_pairs = [
                (m.get(home, 1500.0), m.get(away, 1500.0)) for m in model_elos.values()
            ]
            pred = ensemble_match_prediction(elo_pairs, home_advantage=ha, knockout=is_ko)
            pred["elo_home"] = round(ens_elo.get(home, 1500.0))
            pred["elo_away"] = round(ens_elo.get(away, 1500.0))
            row["pred"] = pred

        # Locked (pre-match) prediction for completed matches — what we're
        # actually scored on. Never recomputed after kickoff.
        key = (r["kickoff_utc"], home, away)
        if completed and key in locked_by_key:
            lk = locked_by_key[key]
            row["locked"] = {
                "p_home": float(lk["p_home"]),
                "p_draw": float(lk["p_draw"]),
                "p_away": float(lk["p_away"]),
                "pred_score": lk.get("pred_score") if pd.notna(lk.get("pred_score")) else None,
                "brier": brier_by_key.get(key),
            }
        out.append(row)
    return out


def _build_groups(wc_df: pd.DataFrame, adv_probs: dict[str, float]) -> dict:
    """Live standings per group (pts → gd → gf; FIFA head-to-head ignored)."""
    table: dict[str, dict[str, dict]] = {
        g: {t: {"team": t, "played": 0, "w": 0, "d": 0, "l": 0,
                "gf": 0, "ga": 0, "pts": 0}
            for t in teams}
        for g, teams in GROUPS.items()
    }
    done = wc_df[(wc_df["completed"]) & (wc_df["stage"] == "group")]
    for _, r in done.iterrows():
        g = r.get("group")
        if g not in table or r["home_team"] not in table[g] or r["away_team"] not in table[g]:
            continue
        h, a = table[g][r["home_team"]], table[g][r["away_team"]]
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        h["played"] += 1; a["played"] += 1
        h["gf"] += hs; h["ga"] += as_
        a["gf"] += as_; a["ga"] += hs
        if hs > as_:
            h["w"] += 1; a["l"] += 1; h["pts"] += 3
        elif hs < as_:
            a["w"] += 1; h["l"] += 1; a["pts"] += 3
        else:
            h["d"] += 1; a["d"] += 1; h["pts"] += 1; a["pts"] += 1

    out = {}
    for g, teams in table.items():
        rows = []
        for t, s in teams.items():
            s["gd"] = s["gf"] - s["ga"]
            s["p_advance"] = round(adv_probs.get(t, 0.0), 4)
            rows.append(s)
        rows.sort(key=lambda s: (-s["pts"], -s["gd"], -s["gf"], -s["p_advance"]))
        out[g] = rows
    return out


def _build_champions(sims: dict[str, pd.DataFrame]) -> list[dict]:
    ens = _latest("predictions/predictions_*.csv")
    ai_probs = dict(zip(ens[1]["team"], ens[1]["ai_prob"])) if ens else {}

    market: dict[str, float] = {}
    if PM_ODDS_PARQUET.exists():
        pm = pd.read_parquet(PM_ODDS_PARQUET)
        latest = pm[pm["timestamp"] == pm["timestamp"].max()]
        market = dict(zip(latest["team"], latest["implied_prob"]))

    edges = _latest("edges/edges_*.csv")
    edge_by_team = {}
    if edges:
        for _, r in edges[1].iterrows():
            edge_by_team[r["team"]] = {
                "edge_pct": round(float(r["edge_pct"]), 2),
                "direction": r["direction"],
                "strength": r["strength"],
                "models_agree": int(r["models_agree"]),
                "half_kelly": round(float(r["half_kelly"]), 4),
            }

    stage_cols = ["P(group_advance)", "P(r16)", "P(qf)", "P(sf)", "P(final)", "P(champion)"]
    per_model_champ: dict[str, dict[str, float]] = {}
    stages_ens: dict[str, dict[str, float]] = {}
    for model, df in sims.items():
        d = df.set_index("team")
        for team in d.index:
            per_model_champ.setdefault(team, {})[model] = round(float(d.loc[team, "P(champion)"]), 4)
            acc = stages_ens.setdefault(team, {c: 0.0 for c in stage_cols})
            for c in stage_cols:
                acc[c] += float(d.loc[team, c]) / len(sims)

    out = []
    for team in ALL_TEAMS:
        out.append({
            "team": team,
            "ai": round(float(ai_probs.get(team, 0.0)), 4),
            "market": round(float(market.get(team, 0.0)), 4),
            "edge": edge_by_team.get(team),
            "per_model": per_model_champ.get(team, {}),
            "stages": {
                "advance": round(stages_ens.get(team, {}).get("P(group_advance)", 0.0), 4),
                "r16": round(stages_ens.get(team, {}).get("P(r16)", 0.0), 4),
                "qf": round(stages_ens.get(team, {}).get("P(qf)", 0.0), 4),
                "sf": round(stages_ens.get(team, {}).get("P(sf)", 0.0), 4),
                "final": round(stages_ens.get(team, {}).get("P(final)", 0.0), 4),
                "champion": round(stages_ens.get(team, {}).get("P(champion)", 0.0), 4),
            },
        })
    out.sort(key=lambda r: -r["ai"])
    return out


def _build_performance(matches: list[dict]) -> dict:
    details = []
    for m in matches:
        if not m["completed"] or "locked" not in m:
            continue
        lk = m["locked"]
        if m["stage"] in KNOCKOUT_STAGES:
            pred_side = "home" if lk["p_home"] >= lk["p_away"] else "away"
            actual_side = "home" if m["winner"] == m["home"] else "away"
        else:
            probs = {"home": lk["p_home"], "draw": lk["p_draw"], "away": lk["p_away"]}
            pred_side = max(probs, key=probs.get)
            actual_side = ("home" if m["home_score"] > m["away_score"]
                           else "away" if m["home_score"] < m["away_score"] else "draw")
        actual_score = f"{m['home_score']}-{m['away_score']}"
        details.append({
            "kickoff_utc": m["kickoff_utc"],
            "stage": m["stage"],
            "home": m["home"],
            "away": m["away"],
            "score": actual_score,
            "pred_score": lk["pred_score"],
            "p_home": lk["p_home"], "p_draw": lk["p_draw"], "p_away": lk["p_away"],
            "brier": lk["brier"],
            "winner_hit": pred_side == actual_side,
            "score_hit": lk["pred_score"] == actual_score if lk["pred_score"] else None,
        })

    scored = [d for d in details if d["brier"] is not None]
    score_preds = [d for d in details if d["score_hit"] is not None]
    perf = {
        "n_scored": len(scored),
        "mean_brier": round(float(np.mean([d["brier"] for d in scored])), 4) if scored else None,
        "winner_hit_rate": round(
            float(np.mean([d["winner_hit"] for d in details])), 4) if details else None,
        "score_hits": sum(1 for d in score_preds if d["score_hit"]),
        "n_score_preds": len(score_preds),
        "details": sorted(details, key=lambda d: d["kickoff_utc"], reverse=True),
        "scoreboard": None,
    }

    if SCOREBOARD_CSV.exists():
        board = pd.read_csv(SCOREBOARD_CSV)
        if not board.empty:
            ai_b, pm_b = float(board["ai_brier"].mean()), float(board["pm_brier"].mean())
            perf["scoreboard"] = {
                "n_pairs": len(board),
                "n_teams": int(board["team"].nunique()),
                "ai_brier": round(ai_b, 5),
                "pm_brier": round(pm_b, 5),
                "leader": "AI" if ai_b < pm_b else "Polymarket",
            }
    return perf


# ── Entry points ─────────────────────────────────────────────────────────────
def build_dashboard(wc_df: pd.DataFrame | None = None) -> dict:
    """Assemble dashboard/data.json. Returns the data dict."""
    wc_df = _load_wc_df(wc_df)
    if wc_df.empty:
        raise RuntimeError("No World Cup schedule available — cannot build dashboard.")

    elo_hist = pd.read_parquet(ELO_PARQUET)
    current_elo = {t: v for t, v in get_latest_elo(elo_hist).items() if t in ALL_TEAMS}

    snapshot = None
    if SNAPSHOT_PATH.exists():
        snapshot = json.loads(SNAPSHOT_PATH.read_text())
    model_elos = live_model_elos(current_elo, snapshot, teams=list(ALL_TEAMS))
    ens_elo = {
        t: float(np.mean([m[t] for m in model_elos.values()])) for t in ALL_TEAMS
    }

    sim_date, sims = _load_model_sims()
    adv_probs: dict[str, float] = {}
    for df in sims.values():
        for _, r in df.iterrows():
            adv_probs[r["team"]] = adv_probs.get(r["team"], 0.0) + (
                float(r["P(group_advance)"]) / len(sims)
            )

    matches = _build_matches(wc_df, model_elos, ens_elo)

    market_meta = {}
    if PM_ODDS_PARQUET.exists():
        pm = pd.read_parquet(PM_ODDS_PARQUET)
        latest = pm[pm["timestamp"] == pm["timestamp"].max()]
        market_meta = {
            "odds_time": str(latest["timestamp"].iloc[0]),
            "volume": float(latest["volume"].iloc[0]),
        }

    data = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "models": list(model_elos.keys()),
            "snapshot_as_of": snapshot.get("as_of") if snapshot else None,
            "sim_date": sim_date,
            "n_matches": len(matches),
            "n_completed": sum(1 for m in matches if m["completed"]),
            **market_meta,
        },
        "matches": matches,
        "groups": _build_groups(wc_df, adv_probs),
        "champions": _build_champions(sims),
        "performance": _build_performance(matches),
    }

    DASHBOARD_DIR.mkdir(exist_ok=True)
    out_path = DASHBOARD_DIR / "data.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    log.info("Dashboard data written: %s (%d matches, %d completed)",
             out_path, len(matches), data["meta"]["n_completed"])
    return data


def deploy_dashboard() -> bool:
    """Deploy dashboard/ to Cloudflare Pages. Best-effort; returns success."""
    wrangler = shutil.which("wrangler")
    if wrangler is None:
        # cron has a minimal PATH — fall back to the nvm install
        nvm = os.path.expanduser("~/.nvm/versions/node")
        candidates = sorted(
            (os.path.join(nvm, v, "bin", "wrangler") for v in os.listdir(nvm)),
            reverse=True,
        ) if os.path.isdir(nvm) else []
        wrangler = next((c for c in candidates if os.path.exists(c)), None)
    if wrangler is None:
        log.warning("wrangler not found — skipping dashboard deploy.")
        return False

    env = dict(os.environ)
    env["PATH"] = f"{os.path.dirname(wrangler)}:{env.get('PATH', '')}"
    try:
        result = subprocess.run(
            [wrangler, "pages", "deploy", str(DASHBOARD_DIR),
             "--project-name", PAGES_PROJECT, "--branch", "main",
             "--commit-dirty=true"],
            capture_output=True, text=True, timeout=300, env=env, cwd=str(ROOT),
        )
    except Exception as exc:  # noqa: BLE001 — deploy must never kill the pipeline
        log.error("Dashboard deploy failed: %s", exc)
        return False
    if result.returncode != 0:
        log.error("Dashboard deploy failed:\n%s", result.stderr[-2000:])
        return False
    log.info("Dashboard deployed: %s", result.stdout.strip().splitlines()[-1])
    return True


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    build_dashboard()
    if "--deploy" in sys.argv:
        deploy_dashboard()
