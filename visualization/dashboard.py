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
from markets.odds_converter import normalize_probs
from prediction.ensemble import live_model_elos
from prediction.score_predictor import ensemble_match_prediction

log = logging.getLogger(__name__)

# Next.js app: web/ is the source, web/out the prebuilt static export.
# The daily pipeline only swaps data.json — no rebuild needed. Rebuild with
# `cd web && npm run build` after UI changes.
WEB_PUBLIC_DIR = ROOT / "web" / "public"
WEB_OUT_DIR = ROOT / "web" / "out"
SNAPSHOT_PATH = RESULTS_DIR / "predictions" / "model_snapshot_latest.json"
MATCH_PREDS_CSV = RESULTS_DIR / "predictions" / "match_predictions.csv"
MATCH_SCORES_CSV = RESULTS_DIR / "evaluations" / "match_scores.csv"
SCOREBOARD_CSV = RESULTS_DIR / "evaluations" / "scoreboard.csv"
PM_ODDS_PARQUET = CACHE_DIR / "polymarket_odds.parquet"

PAGES_PROJECT = "worldcup-oracle"

# Venues span UTC−4…−7; kickoff_utc − 6h groups matches by venue-local
# matchday (must stay consistent with data.fetcher_wc_results._LOCAL_SHIFT).
LOCAL_SHIFT_H = 6

TEAM_ZH = {
    "Mexico": "墨西哥", "South Korea": "韩国", "Czech Republic": "捷克", "South Africa": "南非",
    "United States": "美国", "Turkey": "土耳其", "Australia": "澳大利亚", "Paraguay": "巴拉圭",
    "Canada": "加拿大", "Switzerland": "瑞士", "Bosnia and Herzegovina": "波黑", "Qatar": "卡塔尔",
    "Brazil": "巴西", "Morocco": "摩洛哥", "Scotland": "苏格兰", "Haiti": "海地",
    "Germany": "德国", "Ivory Coast": "科特迪瓦", "Ecuador": "厄瓜多尔", "Curaçao": "库拉索",
    "Netherlands": "荷兰", "Japan": "日本", "Sweden": "瑞典", "Tunisia": "突尼斯",
    "Belgium": "比利时", "Iran": "伊朗", "Egypt": "埃及", "New Zealand": "新西兰",
    "Spain": "西班牙", "Uruguay": "乌拉圭", "Saudi Arabia": "沙特阿拉伯", "Cape Verde": "佛得角",
    "Argentina": "阿根廷", "Algeria": "阿尔及利亚", "Austria": "奥地利", "Jordan": "约旦",
    "France": "法国", "Senegal": "塞内加尔", "Iraq": "伊拉克", "Norway": "挪威",
    "Portugal": "葡萄牙", "Colombia": "哥伦比亚", "Uzbekistan": "乌兹别克斯坦", "DR Congo": "刚果(金)",
    "England": "英格兰", "Croatia": "克罗地亚", "Ghana": "加纳", "Panama": "巴拿马",
}


def _zh(name: str) -> str:
    return TEAM_ZH.get(name, name)


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


# ── Focus matchday (one detailed issue per day) ─────────────────────────────
def _local_matchday(kickoff_utc: str) -> str:
    dt = datetime.fromisoformat(kickoff_utc)
    return (dt - pd.Timedelta(hours=LOCAL_SHIFT_H)).strftime("%Y-%m-%d")


def _team_form(matches: pd.DataFrame, team: str, n: int = 5) -> list[dict]:
    """Last n internationals for a team, most recent first."""
    sub = matches[
        (matches["home_team"] == team) | (matches["away_team"] == team)
    ].sort_values("date").tail(n)
    out = []
    for _, r in sub.iterrows():
        at_home = r["home_team"] == team
        gf = int(r["home_score"] if at_home else r["away_score"])
        ga = int(r["away_score"] if at_home else r["home_score"])
        out.append({
            "date": str(r["date"].date()),
            "opp": r["away_team"] if at_home else r["home_team"],
            "score": f"{gf}-{ga}",
            "res": "W" if gf > ga else ("D" if gf == ga else "L"),
        })
    return out[::-1]


def _h2h(matches: pd.DataFrame, home: str, away: str) -> dict:
    """All meetings between the two teams (1990+), from the home side's view."""
    sub = matches[
        ((matches["home_team"] == home) & (matches["away_team"] == away))
        | ((matches["home_team"] == away) & (matches["away_team"] == home))
    ].sort_values("date")
    w = d = l = 0
    last = []
    for _, r in sub.iterrows():
        flip = r["home_team"] != home
        gf = int(r["away_score"] if flip else r["home_score"])
        ga = int(r["home_score"] if flip else r["away_score"])
        if gf > ga:
            w += 1
        elif gf == ga:
            d += 1
        else:
            l += 1
        last.append({"date": str(r["date"].date()), "score": f"{gf}-{ga}",
                     "tournament": r["tournament"]})
    return {"n": len(sub), "w": w, "d": d, "l": l, "last": last[-3:]}


def _analysis_zh(m: dict, det: dict) -> str:
    """Rule-based Chinese matchup summary built from the numbers."""
    home, away = m["home"], m["away"]
    p = m.get("pred")
    if p is None:
        return ""
    is_ko = m["stage"] in KNOCKOUT_STAGES
    parts = []

    # Strength gap
    diff = det["elo_home"] - det["elo_away"]
    fav = home if diff >= 0 else away
    gap = abs(diff)
    if gap >= 250:
        gap_word = "实力明显高出一档"
    elif gap >= 120:
        gap_word = "纸面实力占优"
    elif gap >= 50:
        gap_word = "略占上风"
    else:
        gap_word = None
    host = next((t for t in (home, away) if t in ("United States", "Canada", "Mexico")), None)
    if gap_word is None:
        opener = "两队实力接近，胜负难料"
        if host:
            opener = f"{_zh(host)}坐拥东道主主场之利，但{opener}"
    elif host == fav:
        opener = f"{_zh(fav)}坐拥东道主主场之利，且{gap_word}"
    elif host:
        opener = f"{_zh(host)}坐拥东道主主场之利，但{_zh(fav)}{gap_word}"
    else:
        opener = f"{_zh(fav)}{gap_word}"
    parts.append(
        f"{opener}（Elo {det['elo_home']} vs {det['elo_away']}，"
        f"分列 48 队第 {det['rank_home']}/{det['rank_away']} 位）。"
    )

    # Model view
    if is_ko:
        side = home if p["p_adv_home"] >= 0.5 else away
        prob = max(p["p_adv_home"], p["p_adv_away"])
        parts.append(
            f"模型给 {_zh(side)} {prob:.0%} 的晋级概率，"
            f"最可能比分 {p['scoreline']['most_likely']}"
            f"（xG {p['scoreline']['xg_home']} - {p['scoreline']['xg_away']}）。"
        )
    else:
        probs = [("主胜", p["p_home"]), ("平局", p["p_draw"]), ("客胜", p["p_away"])]
        top_lbl, top_p = max(probs, key=lambda x: x[1])
        draw_note = f"，平局概率也有 {p['p_draw']:.0%}" if p["p_draw"] >= 0.22 and top_lbl != "平局" else ""
        parts.append(
            f"三模型集成看{top_lbl}（{top_p:.0%}）{draw_note}，"
            f"最可能比分 {p['scoreline']['most_likely']}"
            f"（xG {p['scoreline']['xg_home']} - {p['scoreline']['xg_away']}，"
            f"大 2.5 球 {p['scoreline']['p_over25']:.0%}）。"
        )

    # Form, only when notable
    for team, form in ((home, det["form_home"]), (away, det["form_away"])):
        if len(form) >= 5:
            wins = sum(1 for f in form if f["res"] == "W")
            losses = sum(1 for f in form if f["res"] == "L")
            if wins >= 4:
                parts.append(f"{_zh(team)}近 5 场 {wins} 胜，状态出色。")
            elif losses >= 3:
                parts.append(f"{_zh(team)}近 5 场 {losses} 负，状态堪忧。")

    # Head-to-head
    h2h = det["h2h"]
    if h2h["n"] > 0:
        parts.append(
            f"两队 1990 年以来交手 {h2h['n']} 次，"
            f"{_zh(home)} {h2h['w']} 胜 {h2h['d']} 平 {h2h['l']} 负。"
        )
    else:
        parts.append("两队 1990 年以来没有交手记录。")
    return "".join(parts)


def _attach_matchday_details(
    matches: list[dict],
    matches_hist: pd.DataFrame,
    ens_elo: dict[str, float],
    adv_probs: dict[str, float],
    champ_probs: dict[str, float],
) -> str | None:
    """Pick the next venue-local matchday and enrich its matches with deep
    detail (form, H2H, ranks, stakes, analysis). Returns the matchday date."""
    now = datetime.now(timezone.utc)
    candidates = [
        m for m in matches
        if not m["tbd"] and not m["completed"]
        and datetime.fromisoformat(m["kickoff_utc"]) > now - pd.Timedelta(hours=5)
    ]
    if not candidates:
        return None
    focus = min(_local_matchday(m["kickoff_utc"]) for m in candidates)

    elo_rank = {
        t: i + 1
        for i, (t, _) in enumerate(sorted(ens_elo.items(), key=lambda x: -x[1]))
    }
    for m in matches:
        if m["tbd"] or _local_matchday(m["kickoff_utc"]) != focus:
            continue
        det = {
            "elo_home": round(ens_elo.get(m["home"], 1500.0)),
            "elo_away": round(ens_elo.get(m["away"], 1500.0)),
            "rank_home": elo_rank.get(m["home"], 48),
            "rank_away": elo_rank.get(m["away"], 48),
            "form_home": _team_form(matches_hist, m["home"]),
            "form_away": _team_form(matches_hist, m["away"]),
            "h2h": _h2h(matches_hist, m["home"], m["away"]),
            "advance_home": round(adv_probs.get(m["home"], 0.0), 4),
            "advance_away": round(adv_probs.get(m["away"], 0.0), 4),
            "champion_home": round(champ_probs.get(m["home"], 0.0), 4),
            "champion_away": round(champ_probs.get(m["away"], 0.0), 4),
        }
        det["analysis"] = _analysis_zh(m, det)
        m["detail"] = det
    return focus


# ── Sections ─────────────────────────────────────────────────────────────────
def _kickoff_epoch(iso: str) -> int | None:
    """Normalize a kickoff ISO ('…Z' or '…+00:00') to an epoch second."""
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def _index_moneylines(moneylines: dict[str, dict]) -> dict[int, list[dict]]:
    """Group moneyline markets by kickoff epoch (parallel kickoffs share one)."""
    by_epoch: dict[int, list[dict]] = {}
    for kickoff, ml in moneylines.items():
        ep = _kickoff_epoch(kickoff)
        if ep is not None:
            by_epoch.setdefault(ep, []).append(ml)
    return by_epoch


def _match_market(ml_by_epoch: dict[int, list[dict]], kickoff: str,
                  home: str, away: str) -> dict | None:
    """Find the moneyline for a fixture by kickoff, disambiguating ties by team."""
    ep = _kickoff_epoch(kickoff)
    cands = ml_by_epoch.get(ep, []) if ep is not None else []
    if not cands:
        return None
    if len(cands) == 1:
        ml = cands[0]
    else:
        teams = {home, away}
        ml = next((c for c in cands if {c["home_name"], c["away_name"]} == teams), None)
        if ml is None:
            return None
    # Orient prices to our fixture's home/away (PM order may differ).
    if ml["home_name"] == away and ml["away_name"] == home:
        home_price, away_price = ml["away_price"], ml["home_price"]
    else:
        home_price, away_price = ml["home_price"], ml["away_price"]
    return {
        "slug": ml["slug"],
        "home": round(home_price, 4),
        "draw": round(ml["draw_price"], 4),
        "away": round(away_price, 4),
        "volume": round(ml["volume"]),
    }


def _build_matches(
    wc_df: pd.DataFrame,
    model_elos: dict[str, dict[str, float]],
    ens_elo: dict[str, float],
    moneylines: dict[str, dict] | None = None,
) -> list[dict]:
    ml_by_epoch = _index_moneylines(moneylines or {})
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

        # Polymarket per-match moneyline (raw W/D/L prices + slug for live poll)
        if known:
            mkt = _match_market(ml_by_epoch, r["kickoff_utc"], home, away)
            if mkt:
                row["market"] = mkt

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
    market_raw: dict[str, float] = {}
    if PM_ODDS_PARQUET.exists():
        pm = pd.read_parquet(PM_ODDS_PARQUET)
        latest = pm[pm["timestamp"] == pm["timestamp"].max()]
        raw = dict(zip(latest["team"], latest["implied_prob"]))
        market = normalize_probs(raw)  # de-vigged, for the AI-vs-market edge
        market_raw = raw  # raw price, for tradeable decimal odds

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
            "market_raw": round(float(market_raw.get(team, 0.0)), 4),
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


def _load_calibration_meta() -> dict | None:
    from config import CALIBRATION_PATH
    import json as _json
    if not CALIBRATION_PATH.exists():
        return None
    try:
        d = _json.loads(CALIBRATION_PATH.read_text())
        return {
            "T": d.get("T"), "delta": d.get("delta"), "n_wc": d.get("n_wc"),
            "draw_rate_observed": d.get("draw_rate_observed"),
            "draw_rate_predicted_raw": d.get("draw_rate_predicted_raw"),
        }
    except (ValueError, OSError):
        return None


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

    # Per-match Polymarket moneylines (best-effort; never block the build).
    moneylines: dict[str, dict] = {}
    try:
        from data.fetcher_polymarket import fetch_match_moneylines

        moneylines = fetch_match_moneylines()
    except Exception as exc:  # noqa: BLE001 — odds are optional decoration
        log.warning("Polymarket moneyline fetch failed: %s", exc)

    matches = _build_matches(wc_df, model_elos, ens_elo, moneylines)

    # Focus matchday: today's (or the next) slate gets the deep-dive treatment
    from data.fetcher_matches import fetch_matches

    matches_hist = fetch_matches(force=False)
    ens_pred = _latest("predictions/predictions_*.csv")
    champ_probs = dict(zip(ens_pred[1]["team"], ens_pred[1]["ai_prob"])) if ens_pred else {}
    matchday = _attach_matchday_details(
        matches, matches_hist, ens_elo, adv_probs, champ_probs
    )

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
            "matchday": matchday,
            "n_matches": len(matches),
            "n_completed": sum(1 for m in matches if m["completed"]),
            "calibration": _load_calibration_meta(),
            **market_meta,
        },
        "matches": matches,
        "groups": _build_groups(wc_df, adv_probs),
        "champions": _build_champions(sims),
        "performance": _build_performance(matches),
    }

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    WEB_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (WEB_PUBLIC_DIR / "data.json").write_text(payload)
    if WEB_OUT_DIR.exists():  # prebuilt export — swap data in place for deploy
        (WEB_OUT_DIR / "data.json").write_text(payload)
    else:
        log.warning("web/out missing — run `cd web && npm run build` once.")
    log.info("Dashboard data written: %s (%d matches, %d completed)",
             WEB_PUBLIC_DIR / "data.json", len(matches), data["meta"]["n_completed"])
    return data


def deploy_dashboard() -> bool:
    """Deploy web/out to Cloudflare Pages. Best-effort; returns success."""
    if not (WEB_OUT_DIR / "index.html").exists():
        log.warning("web/out has no build — skipping deploy.")
        return False
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
            [wrangler, "pages", "deploy", str(WEB_OUT_DIR),
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
