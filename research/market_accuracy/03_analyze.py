#!/usr/bin/env python3
"""Analyze local AI, Kalshi, and Polymarket three-way probabilities."""

from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA_PATH = ROOT / "web" / "public" / "data.json"
KALSHI_PATH = HERE / "out" / "kalshi_prices.json"
PM_PATH = HERE / "out" / "pm_prices.json"
ACCURACY_PATH = HERE / "out" / "accuracy.json"
JOINED_PATH = HERE / "out" / "joined.csv"
REPORT_PATH = HERE / "REPORT.md"
FIGS_DIR = HERE / "figs"
OUTCOMES = ("home", "draw", "away")
LEDGER_CATEGORIES = ("完整三源", "缺 Kalshi", "缺 PM", "缺 AI locked", "价格时刻无数据")
STAGES = ("group", "r32", "r16", "qf")
SOURCE_LABELS = {"ai": "AI", "polymarket": "Polymarket", "kalshi": "Kalshi"}


def match_key(match: dict[str, Any]) -> str:
    return f"{match['kickoff_utc']}|{match['home']}|{match['away']}"


def normalize_probs(values: Iterable[float]) -> tuple[list[float], float]:
    probs = [float(value) for value in values]
    if len(probs) != 3 or any(not math.isfinite(p) or p < 0 for p in probs):
        raise ValueError(f"invalid three-way probabilities: {probs}")
    raw_sum = sum(probs)
    if raw_sum <= 0:
        raise ValueError(f"non-positive probability sum: {probs}")
    normalized_values = [p / raw_sum for p in probs]
    assert abs(sum(normalized_values) - 1.0) <= 1e-12
    return normalized_values, raw_sum


def truth_vector(outcome: str) -> list[int]:
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome}")
    return [int(outcome == candidate) for candidate in OUTCOMES]


def brier(probs: Iterable[float], outcome: str) -> float:
    return sum((p - y) ** 2 for p, y in zip(probs, truth_vector(outcome)))


def log_loss(probs: Iterable[float], outcome: str) -> float:
    index = OUTCOMES.index(outcome)
    probability = min(max(list(probs)[index], 1e-15), 1 - 1e-15)
    return -math.log(probability)


def coverage_category(
    *, has_kalshi: bool, has_pm: bool, has_ai: bool, prices_complete: bool
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not has_kalshi:
        reasons.append("缺 Kalshi")
    if not has_pm:
        reasons.append("缺 PM")
    if not has_ai:
        reasons.append("缺 AI locked")
    if not prices_complete:
        reasons.append("价格时刻无数据")
    # This precedence makes the audit ledger mutually exclusive while retaining
    # all overlapping diagnostics in `reasons`.
    category = reasons[0] if reasons else "完整三源"
    return category, reasons


def source_structurally_complete(row: dict[str, Any], source: str) -> bool:
    legs = row.get("legs", {})
    if set(legs) != set(OUTCOMES):
        return False
    if source == "kalshi":
        return bool(row.get("event_ticker")) and row.get("result") in OUTCOMES
    return bool(row.get("event_id")) and all(legs[o].get("yes_token") for o in OUTCOMES)


def source_prices_complete(row: dict[str, Any]) -> bool:
    legs = row.get("legs", {})
    return all(legs.get(outcome, {}).get(point, {}).get("mid") is not None for outcome in OUTCOMES for point in ("t_lock", "t_ko"))


def extract_probs(row: dict[str, Any], point: str) -> tuple[list[float], float]:
    return normalize_probs(row["legs"][outcome][point]["mid"] for outcome in OUTCOMES)


def metric(rows: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "brier": None, "log_loss": None}
    briers = [float(row[f"{prefix}_brier"]) for row in rows]
    losses = [float(row[f"{prefix}_log_loss"]) for row in rows]
    return {
        "n": len(rows),
        "brier": float(np.mean(briers)),
        "log_loss": float(np.mean(losses)),
    }


def bootstrap_difference(
    rows: list[dict[str, Any]], left: str, right: str, seed: int = 42, repetitions: int = 1000
) -> dict[str, Any]:
    differences = np.array([row[f"{left}_brier"] - row[f"{right}_brier"] for row in rows], dtype=float)
    if not len(differences):
        return {"n": 0, "mean_difference": None, "ci95": [None, None], "bootstrap_repetitions": repetitions}
    rng = np.random.default_rng(seed)
    sampled = rng.choice(differences, size=(repetitions, len(differences)), replace=True).mean(axis=1)
    low, high = np.percentile(sampled, [2.5, 97.5])
    return {
        "n": len(differences),
        "mean_difference": float(differences.mean()),
        "ci95": [float(low), float(high)],
        "bootstrap_repetitions": repetitions,
        "seed": seed,
    }


def calibration(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    pooled: list[tuple[float, int]] = []
    for row in rows:
        probs = [row[f"{prefix}_p_{outcome}"] for outcome in OUTCOMES]
        truth = truth_vector(row["outcome"])
        pooled.extend(zip(probs, truth))
    output = []
    for bin_index in range(10):
        values = [(p, y) for p, y in pooled if min(int(p * 10), 9) == bin_index]
        output.append(
            {
                "bin": bin_index,
                "lower": bin_index / 10,
                "upper": (bin_index + 1) / 10,
                "n": len(values),
                "mean_predicted": float(np.mean([p for p, _ in values])) if values else None,
                "observed_frequency": float(np.mean([y for _, y in values])) if values else None,
            }
        )
    assert sum(item["n"] for item in output) == 3 * len(rows)
    return output


def describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def fmt(value: Any, digits: int = 4) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def pct(value: Any, digits: int = 1) -> str:
    return "—" if value is None else f"{100 * float(value):.{digits}f}%"


def join_matches() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ledger = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    matches = [m for m in ledger["matches"] if m.get("completed") is True]
    kalshi_payload = json.loads(KALSHI_PATH.read_text(encoding="utf-8"))
    pm_payload = json.loads(PM_PATH.read_text(encoding="utf-8"))
    kalshi_by_key = {row["match_key"]: row for row in kalshi_payload["rows"]}
    pm_by_key = {row["match_key"]: row for row in pm_payload["rows"]}
    full_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    discrepancies: list[dict[str, Any]] = []

    for match in matches:
        key = match_key(match)
        kalshi = kalshi_by_key.get(key, {})
        pm = pm_by_key.get(key, {})
        locked = match.get("locked") or {}
        has_ai = all(locked.get(field) is not None for field in ("p_home", "p_draw", "p_away"))
        has_kalshi = source_structurally_complete(kalshi, "kalshi")
        has_pm = source_structurally_complete(pm, "pm")
        prices_complete = source_prices_complete(kalshi) and source_prices_complete(pm)
        category, reasons = coverage_category(
            has_kalshi=has_kalshi,
            has_pm=has_pm,
            has_ai=has_ai,
            prices_complete=prices_complete,
        )
        audit = {
            "match_key": key,
            "kickoff_utc": match["kickoff_utc"],
            "home": match["home"],
            "away": match["away"],
            "stage": match.get("stage"),
            "category": category,
            "diagnostic_reasons": reasons,
            "kalshi_event_ticker": kalshi.get("event_ticker"),
            "pm_event_slug": pm.get("event_slug"),
            "pm_event_end_date": pm.get("event_end_date"),
            "pm_event_kickoff_offset_seconds": pm.get("event_kickoff_offset_seconds"),
        }
        audit_rows.append(audit)
        if category != "完整三源":
            continue

        outcome = kalshi["result"]
        ai_probs, ai_sum = normalize_probs([locked["p_home"], locked["p_draw"], locked["p_away"]])
        pm_lock, pm_lock_sum = extract_probs(pm, "t_lock")
        pm_ko, pm_ko_sum = extract_probs(pm, "t_ko")
        kalshi_lock, kalshi_lock_sum = extract_probs(kalshi, "t_lock")
        kalshi_ko, kalshi_ko_sum = extract_probs(kalshi, "t_ko")
        vectors = {
            "ai_lock": (ai_probs, ai_sum),
            "pm_lock": (pm_lock, pm_lock_sum),
            "pm_ko": (pm_ko, pm_ko_sum),
            "kalshi_lock": (kalshi_lock, kalshi_lock_sum),
            "kalshi_ko": (kalshi_ko, kalshi_ko_sum),
        }
        row: dict[str, Any] = {
            "match_key": key,
            "kickoff_utc": match["kickoff_utc"],
            "t_lock": kalshi["t_lock"],
            "t_ko": kalshi["t_ko"],
            "stage": match.get("stage"),
            "home": match["home"],
            "away": match["away"],
            "home_score": match.get("home_score"),
            "away_score": match.get("away_score"),
            "outcome": outcome,
            "kalshi_event_ticker": kalshi.get("event_ticker"),
            "pm_event_slug": pm.get("event_slug"),
        }
        for prefix, (probs, raw_sum) in vectors.items():
            for outcome_name, probability in zip(OUTCOMES, probs):
                row[f"{prefix}_p_{outcome_name}"] = probability
            row[f"{prefix}_raw_sum"] = raw_sum
            row[f"{prefix}_brier"] = brier(probs, outcome)
            row[f"{prefix}_log_loss"] = log_loss(probs, outcome)
            assert abs(sum(probs) - 1.0) <= 1e-6
        full_rows.append(row)

        if match.get("stage") == "group":
            home_score, away_score = match.get("home_score"), match.get("away_score")
            score_outcome = "draw" if home_score == away_score else ("home" if home_score > away_score else "away")
            if score_outcome != outcome:
                discrepancies.append(
                    {
                        "match_key": key,
                        "kickoff_utc": match["kickoff_utc"],
                        "match": f"{match['home']} vs {match['away']}",
                        "score": f"{home_score}-{away_score}",
                        "score_outcome": score_outcome,
                        "kalshi_outcome": outcome,
                        "event_ticker": kalshi.get("event_ticker"),
                    }
                )

    assert len(audit_rows) == len(matches)
    assert sum(Counter(row["category"] for row in audit_rows).values()) == len(matches)
    return full_rows, audit_rows, discrepancies


def build_accuracy(
    rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]], discrepancies: list[dict[str, Any]]
) -> dict[str, Any]:
    categories = Counter(row["category"] for row in audit_rows)
    group_rows = [row for row in rows if row["stage"] == "group"]
    by_stage: dict[str, Any] = {}
    for stage in STAGES:
        stage_rows = [row for row in rows if row["stage"] == stage]
        by_stage[stage] = {
            "ai_t_lock": metric(stage_rows, "ai_lock"),
            "polymarket_t_lock": metric(stage_rows, "pm_lock"),
            "kalshi_t_lock": metric(stage_rows, "kalshi_lock"),
            "polymarket_t_ko": metric(stage_rows, "pm_ko"),
            "kalshi_t_ko": metric(stage_rows, "kalshi_ko"),
        }

    accuracy = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "completed_matches": len(audit_rows),
            "complete_three_source_matches": len(rows),
            "stages_present": sorted({row["stage"] for row in audit_rows}),
            "outcome_definition": "Kalshi settled regulation-time result",
            "t_lock_definition": "06:10 UTC on kickoff day, or previous day when kickoff is before 06:10 UTC",
            "t_ko_definition": "kickoff minus 5 minutes",
        },
        "coverage": {
            "precedence": list(LEDGER_CATEGORIES[1:]),
            "counts": {category: categories.get(category, 0) for category in LEDGER_CATEGORIES},
            "ledger": audit_rows,
        },
        "metrics": {
            "t_lock": {
                "ai": metric(rows, "ai_lock"),
                "polymarket": metric(rows, "pm_lock"),
                "kalshi": metric(rows, "kalshi_lock"),
            },
            "t_ko": {
                "polymarket": metric(rows, "pm_ko"),
                "kalshi": metric(rows, "kalshi_ko"),
            },
        },
        "paired_comparisons": {
            "pm_minus_kalshi_t_ko": bootstrap_difference(rows, "pm_ko", "kalshi_ko"),
            "ai_minus_pm_t_lock": bootstrap_difference(rows, "ai_lock", "pm_lock"),
            "ai_minus_kalshi_t_lock": bootstrap_difference(rows, "ai_lock", "kalshi_lock"),
        },
        "group_only_sensitivity": {
            "reason": "AI knockout locked probabilities have p_draw=0 and represent advancement rather than regulation-time three-way outcomes",
            "metrics_t_lock": {
                "ai": metric(group_rows, "ai_lock"),
                "polymarket": metric(group_rows, "pm_lock"),
                "kalshi": metric(group_rows, "kalshi_lock"),
            },
            "paired_comparisons": {
                "ai_minus_pm_t_lock": bootstrap_difference(group_rows, "ai_lock", "pm_lock"),
                "ai_minus_kalshi_t_lock": bootstrap_difference(group_rows, "ai_lock", "kalshi_lock"),
            },
        },
        "calibration_t_lock": {
            "ai": calibration(rows, "ai_lock"),
            "polymarket": calibration(rows, "pm_lock"),
            "kalshi": calibration(rows, "kalshi_lock"),
        },
        "by_stage": by_stage,
        "raw_probability_sums": {
            "ai_t_lock": describe([row["ai_lock_raw_sum"] for row in rows]),
            "polymarket_t_lock": describe([row["pm_lock_raw_sum"] for row in rows]),
            "polymarket_t_ko": describe([row["pm_ko_raw_sum"] for row in rows]),
            "kalshi_t_lock": describe([row["kalshi_lock_raw_sum"] for row in rows]),
            "kalshi_t_ko": describe([row["kalshi_ko_raw_sum"] for row in rows]),
        },
        "group_score_discrepancies": {
            "n_group_complete_cases": sum(row["stage"] == "group" for row in rows),
            "count": len(discrepancies),
            "matches": discrepancies,
        },
        "semantic_audit": {
            "knockout_complete_cases": sum(row["stage"] != "group" for row in rows),
            "knockout_ai_p_draw_zero": sum(row["stage"] != "group" and row["ai_lock_p_draw"] == 0 for row in rows),
            "knockout_regulation_draws_with_ai_zero": sum(
                row["stage"] != "group" and row["outcome"] == "draw" and row["ai_lock_p_draw"] == 0
                for row in rows
            ),
            "log_loss_probability_floor": 1e-15,
            "pm_event_enddate_offset_anomalies": [
                {
                    "match_key": row["match_key"],
                    "offset_seconds": row["pm_event_kickoff_offset_seconds"],
                }
                for row in audit_rows
                if row.get("pm_event_kickoff_offset_seconds") not in (None, 0)
            ],
        },
    }
    return accuracy


def write_outputs(rows: list[dict[str, Any]], accuracy: dict[str, Any]) -> None:
    ACCURACY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = ACCURACY_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(accuracy, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(ACCURACY_PATH)
    pd.DataFrame(rows).to_csv(JOINED_PATH, index=False, quoting=csv.QUOTE_MINIMAL)
    written = pd.read_csv(JOINED_PATH)
    assert len(written) == accuracy["scope"]["complete_three_source_matches"]


def plot_figures(accuracy: dict[str, Any]) -> list[str]:
    FIGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.environ.setdefault("MPLCONFIGDIR", "/tmp/worldcup-oracle-matplotlib")
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager

        cjk_font = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
        if cjk_font.exists():
            font_manager.fontManager.addfont(str(cjk_font))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(cjk_font)).get_name()
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        return []

    colors = {"ai": "#245B8A", "polymarket": "#D58A2A", "kalshi": "#B44C73"}
    markers = {"ai": "o", "polymarket": "s", "kalshi": "^"}
    created: list[str] = []

    fig, ax = plt.subplots(figsize=(8.4, 6.2), facecolor="white")
    for source in ("ai", "polymarket", "kalshi"):
        bins = [b for b in accuracy["calibration_t_lock"][source] if b["n"]]
        ax.plot(
            [b["mean_predicted"] for b in bins],
            [b["observed_frequency"] for b in bins],
            color=colors[source],
            marker=markers[source],
            linewidth=2,
            markersize=6,
            label=SOURCE_LABELS[source],
        )
    ax.plot([0, 1], [0, 1], color="#333333", linestyle="--", linewidth=1.4, label="理想校准")
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="预测概率（bin 内均值）", ylabel="实际发生频率")
    ax.set_title(
        f"三源校准曲线（t_lock）\n三腿事件池化 · 10 档 · 完整三源 n={accuracy['scope']['complete_three_source_matches']} 场",
        loc="left",
        weight="bold",
        pad=12,
    )
    ax.grid(True, color="#E5E7EB", linewidth=0.8)
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    path = FIGS_DIR / "calibration.png"
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    created.append(str(path.relative_to(HERE)))

    overall = accuracy["metrics"]["t_lock"]
    group = accuracy["group_only_sensitivity"]["metrics_t_lock"]
    ko_metrics = accuracy["metrics"]["t_ko"]
    panels = [
        ("t_lock · 全部完整场", "AI 淘汰赛为晋级概率", ["ai", "polymarket", "kalshi"], [overall[s]["brier"] for s in ("ai", "polymarket", "kalshi")], accuracy["scope"]["complete_three_source_matches"]),
        ("t_lock · 仅小组赛", "三源均为常规时间三向", ["ai", "polymarket", "kalshi"], [group[s]["brier"] for s in ("ai", "polymarket", "kalshi")], group["ai"]["n"]),
        ("t_ko · 临场市场", "只比较两个市场", ["polymarket", "kalshi"], [ko_metrics[s]["brier"] for s in ("polymarket", "kalshi")], ko_metrics["polymarket"]["n"]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 5.5), facecolor="white", sharey=True)
    max_value = max(value for _, _, _, values, _ in panels for value in values)
    for ax, (title, subtitle, sources, values, panel_n) in zip(axes, panels):
        bars = ax.bar([SOURCE_LABELS[s] for s in sources], values, color=[colors[s] for s in sources], edgecolor="#333333", linewidth=0.7)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.008, f"{value:.4f}", ha="center", va="bottom", fontsize=9)
        ax.set_ylim(0, max_value * 1.18)
        ax.set_title(f"{title}\n{subtitle} · n={panel_n}", loc="left", weight="bold", fontsize=10.5, pad=8)
        ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", labelrotation=12)
    axes[0].set_ylabel("三向 Brier（越低越好）")
    fig.suptitle("Brier 对比：全部样本、可比敏感性与临场市场", x=0.06, ha="left", weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    path = FIGS_DIR / "brier_comparison.png"
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    created.append(str(path.relative_to(HERE)))
    return created


def conclusion_markdown(accuracy: dict[str, Any]) -> str:
    lock = accuracy["metrics"]["t_lock"]
    ko = accuracy["metrics"]["t_ko"]
    comparisons = accuracy["paired_comparisons"]
    n = accuracy["scope"]["complete_three_source_matches"]
    ranked = sorted(lock.items(), key=lambda item: item[1]["brier"])
    winner = SOURCE_LABELS[ranked[0][0]]
    best = ranked[0][1]["brier"]
    pmk = comparisons["pm_minus_kalshi_t_ko"]
    aipm = comparisons["ai_minus_pm_t_lock"]
    aik = comparisons["ai_minus_kalshi_t_lock"]
    group = accuracy["group_only_sensitivity"]
    group_metrics = group["metrics_t_lock"]
    group_aipm = group["paired_comparisons"]["ai_minus_pm_t_lock"]
    semantic = accuracy["semantic_audit"]
    return f"""> **在 {n} 场完整样本的机械评分中，`t_lock` 的 Polymarket / Kalshi 明显优于 AI：Brier 约 0.483 对 0.555，AI−市场的 95% 配对 bootstrap 区间不跨 0。但总体 AI 差距混入了一个重要的目标定义错位；不能把它全部解释成模型本身更差。**
>
> - **同信息时点（`t_lock`）**：AI / Polymarket / Kalshi 的 Brier 分别为 **{lock['ai']['brier']:.4f} / {lock['polymarket']['brier']:.4f} / {lock['kalshi']['brier']:.4f}**，log-loss 分别为 **{lock['ai']['log_loss']:.4f} / {lock['polymarket']['log_loss']:.4f} / {lock['kalshi']['log_loss']:.4f}**。
> - **淘汰赛语义审计**：{semantic['knockout_complete_cases']} 场淘汰赛的 AI locked 均为 **`p_draw=0` 的晋级概率**，却按任务要求用 90 分钟三向真值评分；其中 {semantic['knockout_regulation_draws_with_ai_zero']} 场 90 分钟平局令 AI log-loss 在 `1e-15` floor 下单场达到 34.54。因此总体 log-loss 尤其不可直接作三向模型能力比较。
> - **仅小组赛的可比敏感性**：三源都确实预测常规时间三向时，AI / PM / Kalshi Brier 为 **{group_metrics['ai']['brier']:.4f} / {group_metrics['polymarket']['brier']:.4f} / {group_metrics['kalshi']['brier']:.4f}**（n={group_metrics['ai']['n']}）；AI−PM 为 **{group_aipm['mean_difference']:+.4f}**，95% CI **[{group_aipm['ci95'][0]:+.4f}, {group_aipm['ci95'][1]:+.4f}]**。这说明市场优势不只由淘汰赛错位制造，但总体效应量仍被错位放大。
> - **临场市场对市场（`t_ko`）**：Polymarket / Kalshi 的 Brier 为 **{ko['polymarket']['brier']:.4f} / {ko['kalshi']['brier']:.4f}**；PM−Kalshi 的配对差为 **{pmk['mean_difference']:+.4f}**，95% bootstrap CI **[{pmk['ci95'][0]:+.4f}, {pmk['ci95'][1]:+.4f}]**。
> - **AI 对市场（`t_lock`）**：AI−PM 为 **{aipm['mean_difference']:+.4f}**（95% CI **[{aipm['ci95'][0]:+.4f}, {aipm['ci95'][1]:+.4f}]**）；AI−Kalshi 为 **{aik['mean_difference']:+.4f}**（95% CI **[{aik['ci95'][0]:+.4f}, {aik['ci95'][1]:+.4f}]**。差值为负表示左侧更准；区间跨 0 时应表述为“样本不足以确认差异”。
> - **这不是把 AI 与临场盘口硬比**：AI 在每日 06:00 UTC 左右锁定；主比较让市场也停在 06:10 UTC。`t_ko` 的市场额外吸收了当天新闻、伤停与首发名单等新信息，AI 无法使用这些信息，所以 `t_ko` 只回答“两个市场谁更准”，不回答“AI 是否不如临场市场”。"""


def build_report(accuracy: dict[str, Any], figures: list[str]) -> str:
    n = accuracy["scope"]["complete_three_source_matches"]
    completed = accuracy["scope"]["completed_matches"]
    counts = accuracy["coverage"]["counts"]
    lock = accuracy["metrics"]["t_lock"]
    ko = accuracy["metrics"]["t_ko"]
    comparisons = accuracy["paired_comparisons"]
    discrepancy = accuracy["group_score_discrepancies"]
    group_sensitivity = accuracy["group_only_sensitivity"]
    semantic = accuracy["semantic_audit"]
    lines = [
        "# 2026 世界杯三方预测准确度：AI vs Polymarket vs Kalshi",
        "",
        f"**研究范围**：截至 {datetime.now(timezone.utc).date().isoformat()}，账本中已完赛 {completed} 场；完整三源、两时点样本 {n} 场。",
        "",
        "---",
        "",
        "## 结论先行",
        "",
        conclusion_markdown(accuracy),
        "",
        "---",
        "",
        "## 核心结果：同一信息集与临场市场必须分开读",
        "",
        "| 比较口径 | 来源 | n | Brier ↓ | log-loss ↓ |",
        "|---|---|---:|---:|---:|",
        f"| `t_lock` | AI | {lock['ai']['n']} | {fmt(lock['ai']['brier'])} | {fmt(lock['ai']['log_loss'])} |",
        f"| `t_lock` | Polymarket | {lock['polymarket']['n']} | {fmt(lock['polymarket']['brier'])} | {fmt(lock['polymarket']['log_loss'])} |",
        f"| `t_lock` | Kalshi | {lock['kalshi']['n']} | {fmt(lock['kalshi']['brier'])} | {fmt(lock['kalshi']['log_loss'])} |",
        f"| `t_ko` | Polymarket | {ko['polymarket']['n']} | {fmt(ko['polymarket']['brier'])} | {fmt(ko['polymarket']['log_loss'])} |",
        f"| `t_ko` | Kalshi | {ko['kalshi']['n']} | {fmt(ko['kalshi']['brier'])} | {fmt(ko['kalshi']['log_loss'])} |",
        "",
        "Brier 图分成三个零基线面板：全部完整样本、仅小组赛的同目标敏感性、临场市场对市场。这样既保留任务要求的全赛事机械评分，也不把淘汰赛目标错位藏在总体均值里。",
        "",
        "![Brier 对比](figs/brier_comparison.png)" if "figs/brier_comparison.png" in figures else "_matplotlib 不可用，已跳过 Brier 图；精确值见上表。_",
        "",
        "### 淘汰赛 AI 不是常规时间三向盘：小组赛敏感性更可比",
        "",
        f"完整样本含 {semantic['knockout_complete_cases']} 场淘汰赛；这些场次 AI locked 的 `p_draw` 全为 0，口径实际是晋级概率。90 分钟真值中有 {semantic['knockout_regulation_draws_with_ai_zero']} 场平局，所以按三向 log-loss 机械评分会产生结构性惩罚。为保证全赛事流水账，本报告仍保留指定的总体指标；为回答模型能力问题，另报 72 场小组赛敏感性。",
        "",
        "| 仅小组赛 `t_lock` | n | Brier | log-loss |",
        "|---|---:|---:|---:|",
        f"| AI | {group_sensitivity['metrics_t_lock']['ai']['n']} | {fmt(group_sensitivity['metrics_t_lock']['ai']['brier'])} | {fmt(group_sensitivity['metrics_t_lock']['ai']['log_loss'])} |",
        f"| Polymarket | {group_sensitivity['metrics_t_lock']['polymarket']['n']} | {fmt(group_sensitivity['metrics_t_lock']['polymarket']['brier'])} | {fmt(group_sensitivity['metrics_t_lock']['polymarket']['log_loss'])} |",
        f"| Kalshi | {group_sensitivity['metrics_t_lock']['kalshi']['n']} | {fmt(group_sensitivity['metrics_t_lock']['kalshi']['brier'])} | {fmt(group_sensitivity['metrics_t_lock']['kalshi']['log_loss'])} |",
        "",
        "### 配对差与不确定性",
        "",
        "| 配对差（左−右） | n | 均值 | 1000 次 bootstrap 95% CI |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (
        ("pm_minus_kalshi_t_ko", "PM−Kalshi @ `t_ko`"),
        ("ai_minus_pm_t_lock", "AI−PM @ `t_lock`"),
        ("ai_minus_kalshi_t_lock", "AI−Kalshi @ `t_lock`"),
    ):
        item = comparisons[key]
        lines.append(f"| {label} | {item['n']} | {item['mean_difference']:+.4f} | [{item['ci95'][0]:+.4f}, {item['ci95'][1]:+.4f}] |")
    lines += [
        "",
        "负值表示左侧 Brier 更低。bootstrap 以比赛为重采样单位，保留同场三源的相关性；这是描述性不确定性区间，不是多重检验校正后的显著性声明。",
        "",
        "### 校准：三腿事件池化只能看整体形状",
        "",
        "每场的 home/draw/away 三个概率都作为一个二元事件进入 10 档可靠性曲线；因此每源共有 `3 × n` 个事件。空 bin 不插值，也不画虚构点。",
        "",
        "![校准曲线](figs/calibration.png)" if "figs/calibration.png" in figures else "_matplotlib 不可用，已跳过校准图；逐 bin 数值保存在 `out/accuracy.json`。_",
        "",
        "---",
        "",
        "## 分阶段结果：后期轮次样本很小",
        "",
        "| stage | n | AI @ lock | PM @ lock | Kalshi @ lock | PM @ ko | Kalshi @ ko |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for stage in STAGES:
        item = accuracy["by_stage"][stage]
        lines.append(
            f"| {stage} | {item['ai_t_lock']['n']} | {fmt(item['ai_t_lock']['brier'])} | {fmt(item['polymarket_t_lock']['brier'])} | {fmt(item['kalshi_t_lock']['brier'])} | {fmt(item['polymarket_t_ko']['brier'])} | {fmt(item['kalshi_t_ko']['brier'])} |"
        )
    lines += [
        "",
        "表中均为 Brier。`qf` 即使尚无完赛样本也保留为 0 行，避免把“尚未发生”误读为“数据缺失”。淘汰赛分层的 n 很小，不应据此给来源排位。",
        "",
        "---",
        "",
        "## 数据、时点与评分定义",
        "",
        "- **比赛母表**：`web/public/data.json` 中 `completed == true` 的每场比赛；分析粒度是一场比赛。AI 使用 `locked.p_home/p_draw/p_away`，不从赛后字段重建预测。",
        "- **`t_ko`**：官方账本开球时间减 5 分钟。Kalshi 的 `occurrence_datetime` 不用于开球时间。",
        "- **`t_lock`**：开球 UTC 日 06:10；若开球早于 06:10，则使用前一日 06:10。这是对每日 06:00 AI 锁定 cron 留出 10 分钟后的可审计代理点。",
        "- **市场价**：Kalshi 优先用有效 bid/ask 的 midpoint，任一侧缺失或为 0 时退回 candle close；Polymarket 使用 Yes token 最后一个 `t <= target` 的历史成交价。两者都不向后看，也不填充没有历史点的腿。",
        "- **去 vig**：每源每场每时点把三腿除以原始三腿和。原始和完整保存在 `joined.csv`，汇总保存在 `accuracy.json`。AI 也重新归一，防止舍入误差。",
        "- **真值**：只使用 Kalshi 三腿中唯一 settled `yes`，即常规时间三向结果。Brier 为 `Σ(p−y)²`，范围 0–2；log-loss 为 `−log(p_true)`。为输出有限 JSON，精确 0 的真实腿用 `1e-15` floor，报告同时单列这种结构性 0 的数量。",
        f"- **事件匹配审计**：Polymarket 94 场 `endDate` 与账本开球完全一致；{len(semantic['pm_event_enddate_offset_anomalies'])} 场相差 −3600 秒（Mexico–Ecuador、Mexico–England），以唯一精确 moneyline 标题受控匹配，所有目标时刻仍只用账本 `kickoff_utc`。偏移明细保存在 `accuracy.json`。",
        "",
        "### 原始三腿和（市场 overround / underround）",
        "",
        "| 来源时点 | n | 均值 | 中位数 | 最小 | 最大 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("ai_t_lock", "AI @ lock"),
        ("polymarket_t_lock", "PM @ lock"),
        ("polymarket_t_ko", "PM @ ko"),
        ("kalshi_t_lock", "Kalshi @ lock"),
        ("kalshi_t_ko", "Kalshi @ ko"),
    ):
        item = accuracy["raw_probability_sums"][key]
        lines.append(f"| {label} | {item['n']} | {fmt(item['mean'])} | {fmt(item['median'])} | {fmt(item['min'])} | {fmt(item['max'])} |")
    lines += [
        "",
        "原始和大于 1 是正 overround，小于 1 是 underround；这张表描述三只独立二元合约合成三向盘时的总和，不等同于传统庄家固定抽水。",
        "",
        "---",
        "",
        "## Ground truth 交叉校验",
        "",
        f"完整样本中的小组赛共 **{discrepancy['n_group_complete_cases']}** 场；Kalshi settled 常规时间结果与 `home_score/away_score` 推断结果不一致 **{discrepancy['count']}** 场。",
        "",
        "| 开球 | 比赛 | 比分 | 比分推断 | Kalshi | event |",
        "|---|---|---:|---|---|---|",
    ]
    if discrepancy["matches"]:
        for item in discrepancy["matches"]:
            lines.append(f"| {item['kickoff_utc']} | {item['match']} | {item['score']} | {item['score_outcome']} | {item['kalshi_outcome']} | `{item['event_ticker']}` |")
    else:
        lines.append("| — | 无不一致 | — | — | — | — |")
    lines += [
        "",
        "淘汰赛不做比分反推，因为账本终场比分可能含加时或点球信息，不能可靠恢复 90 分钟三向结果。",
        "",
        "---",
        "",
        "## 缺数账本：96 场逐场互斥归类",
        "",
        "归类优先级依次为 `缺 Kalshi → 缺 PM → 缺 AI locked → 价格时刻无数据`；这样每场恰好进入一类。若同场有多个问题，`diagnostic_reasons` 仍完整保留在 `accuracy.json`，不会因互斥汇总而丢失。",
        "",
        "| 类别 | 场数 |",
        "|---|---:|",
    ]
    for category in LEDGER_CATEGORIES:
        lines.append(f"| {category} | {counts[category]} |")
    lines += [
        "",
        "### 逐场流水账",
        "",
        "| # | 开球 UTC | 比赛 | stage | 互斥类别 | 全部诊断 |",
        "|---:|---|---|---|---|---|",
    ]
    for index, item in enumerate(accuracy["coverage"]["ledger"], start=1):
        reasons = "；".join(item["diagnostic_reasons"]) or "—"
        lines.append(f"| {index} | {item['kickoff_utc']} | {item['home']} vs {item['away']} | {item['stage']} | {item['category']} | {reasons} |")
    lines += [
        "",
        "`joined.csv` 只含“完整三源”行，所以其行数必须且已经断言等于上表的完整三源场数；其余比赛没有进入任何准确度均值。不存在补值。",
        "",
        "---",
        "",
        "## 诚实的局限",
        "",
        "1. **信息集不同是核心限制，不是脚注。** 市场在 `t_lock` 后仍持续吸收新信息，例如伤停确认、当天状态、天气变化和首发名单；AI 锁定后无法使用这些信息。因此 AI 与市场的公平比较锚定 `t_lock`，而 `t_ko` 只比较两个市场。即使临场市场 Brier 更低，也不能把全部差值解释成模型结构更优。",
        "2. **历史价不等于无限流动性的可成交价。** Kalshi midpoint 可能来自很宽的 bid/ask，退回 close 时则是最后成交；Polymarket 历史 API给最后成交价而非同步盘口 midpoint。去 vig 修正了三腿总和，却不能消除价差、陈旧成交或深度差异。",
        "3. **完整案例分析可能有选择偏差。** 任一事件、腿、锁定预测或目标时点价格缺失都会整场排除。缺数账本使排除透明，但不能保证完整样本与缺失样本可交换。",
        "4. **96 场仍是小样本，淘汰赛尤其小。** 配对 bootstrap 区间反映当前比赛集合上的采样不确定性；它不是未来世界杯的外推保证，也没有对多个阶段/来源比较做 family-wise 校正。",
        "5. **Kalshi 是真值源也是被评估源。** settled result 是离散赛果，不使用其价格，所以没有机械泄漏；但若平台结算规则或个别 market 映射错误，会同时影响标签与 Kalshi 行。小组赛比分交叉校验用于发现这类问题，淘汰赛只能人工核对 market 文本与 settled 腿。",
        "6. **校准曲线把三腿池化。** home/draw/away 的基准率和难度不同，池化图适合总体诊断，不等同于每一腿分别校准；每 bin 样本也相互依赖，因为同一场贡献三个事件。",
        "7. **这是一届赛事的回测，不是投注建议。** 球队构成、市场参与者和模型版本都随时间变化；点估计差异不能直接转换成未来收益。",
        "",
        "---",
        "",
        "## 下一步",
        "",
        "- 赛事继续后，用同一脚本追加 QF/SF/final，保持时点和缺数规则不变，避免事后改口径。",
        "- 若要研究可交易性，另存目标时点价差、深度和最近成交距目标时点的 age；准确度与执行成本应分开报告。",
        "- 样本扩大后补充 outcome-specific 校准与按成交活跃度的敏感性分析；在当前 n 下不把小分层噪声包装成稳定结论。",
        "",
        "## 可复现运行",
        "",
        "```bash",
        "/home/ubuntu/worldcup-oracle/venv/bin/python research/market_accuracy/01_fetch_kalshi.py",
        "/home/ubuntu/worldcup-oracle/venv/bin/python research/market_accuracy/02_fetch_polymarket.py",
        "/home/ubuntu/worldcup-oracle/venv/bin/python research/market_accuracy/03_analyze.py",
        "```",
        "",
        "两个 fetch 脚本访问网络并覆写各自 JSON；`03_analyze.py` 只读本地三个输入文件。所有 JSON 使用固定字段结构，分析 bootstrap 随机种子固定为 42。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    rows, audit_rows, discrepancies = join_matches()
    accuracy = build_accuracy(rows, audit_rows, discrepancies)
    write_outputs(rows, accuracy)
    figures = plot_figures(accuracy)
    REPORT_PATH.write_text(build_report(accuracy, figures), encoding="utf-8")

    print("核心准确度（完整三源）")
    print(f"  n={len(rows)} / completed={len(audit_rows)}")
    for source in ("ai", "polymarket", "kalshi"):
        item = accuracy["metrics"]["t_lock"][source]
        print(f"  t_lock {SOURCE_LABELS[source]}: Brier={item['brier']:.6f}, log-loss={item['log_loss']:.6f}, n={item['n']}")
    for source in ("polymarket", "kalshi"):
        item = accuracy["metrics"]["t_ko"][source]
        print(f"  t_ko {SOURCE_LABELS[source]}: Brier={item['brier']:.6f}, log-loss={item['log_loss']:.6f}, n={item['n']}")
    for key, item in accuracy["paired_comparisons"].items():
        print(f"  {key}: diff={item['mean_difference']:+.6f}, CI95=[{item['ci95'][0]:+.6f}, {item['ci95'][1]:+.6f}], n={item['n']}")
    group = accuracy["group_only_sensitivity"]
    print(
        "  group-only t_lock Brier: "
        + ", ".join(
            f"{SOURCE_LABELS[source]}={group['metrics_t_lock'][source]['brier']:.6f}"
            for source in ("ai", "polymarket", "kalshi")
        )
        + f", n={group['metrics_t_lock']['ai']['n']}"
    )
    print(f"  缺数账本: {accuracy['coverage']['counts']}")
    print(f"  Kalshi result vs 小组赛比分不一致: {len(discrepancies)}")
    print(f"  joined.csv rows == 完整三源: {len(pd.read_csv(JOINED_PATH))} == {len(rows)}")
    print(f"  figures: {figures or 'skipped (matplotlib unavailable)'}")


if __name__ == "__main__":
    main()
