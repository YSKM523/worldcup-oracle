#!/usr/bin/env python3
"""Data-freshness watchdog for worldcup-oracle.

Independent of the pipeline on purpose: it reads the *output* the pipeline is
supposed to keep fresh (web/public/data.json → meta.generated_at) and pushes a
Polymarket-collector-style ntfy alert if that output is stale. This catches the
exact failure the pipeline itself can't report: cron silently not running at all.

Stdlib only (urllib) so it runs under bare cron without the project venv.
Run every few hours from cron:

    0 */6 * * * cd /home/ubuntu/worldcup-oracle && python3 scripts/freshness_watchdog.py >> results/logs/watchdog.log 2>&1

Age uses the same system clock the pipeline stamps with, so the comparison is
self-consistent regardless of any absolute clock offset.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "web" / "public" / "data.json"
STATE = ROOT / "results" / "logs" / ".watchdog_state.json"

# data.json is rebuilt daily (matchday 06:00 UTC / daily 08:00 UTC). Alert once
# it is older than a day + margin — i.e. a rebuild was very likely missed.
THRESHOLD_H = float(os.environ.get("WATCHDOG_THRESHOLD_H", "28"))
# don't re-alert more often than this while it stays stale
COOLDOWN_H = float(os.environ.get("WATCHDOG_COOLDOWN_H", "12"))
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "wc-oracle-458e50").strip()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now_utc().strftime("%Y-%m-%d %H:%M:%SZ")


def push(title: str, body: str) -> None:
    if not NTFY_TOPIC:
        print(f"{stamp()} ntfy disabled (no topic) — would send: {title}")
        return
    import base64

    enc_title = "=?UTF-8?B?" + base64.b64encode(title.encode()).decode() + "?="
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"X-Title": enc_title, "Priority": "high", "Tags": "warning"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        print(f"{stamp()} ALERT pushed: {title}")
    except Exception as e:  # noqa: BLE001 — watchdog must never crash cron
        print(f"{stamp()} ntfy push FAILED: {e}")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(d: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d))
    except Exception as e:  # noqa: BLE001
        print(f"{stamp()} state save failed: {e}")


def main() -> int:
    if not DATA_JSON.exists():
        push("⚠️ Oracle 看板数据缺失", f"{DATA_JSON} 不存在——pipeline 可能从未成功产出。")
        return 0

    try:
        meta = json.loads(DATA_JSON.read_text()).get("meta", {})
        gen = meta.get("generated_at")
        gen_dt = datetime.fromisoformat(gen.replace("Z", "+00:00"))
        if gen_dt.tzinfo is None:
            gen_dt = gen_dt.replace(tzinfo=timezone.utc)
    except Exception as e:  # noqa: BLE001
        push("⚠️ Oracle 数据无法解析", f"读取 data.json 的 generated_at 失败：{e}")
        return 0

    age_h = (now_utc() - gen_dt).total_seconds() / 3600
    fresh = age_h <= THRESHOLD_H
    print(f"{stamp()} data.json age={age_h:.1f}h threshold={THRESHOLD_H:.0f}h "
          f"-> {'OK' if fresh else 'STALE'}")

    state = load_state()
    if fresh:
        # clear any prior alert marker so the next staleness re-alerts promptly
        if state.get("alerted"):
            save_state({})
        return 0

    # stale — respect cooldown
    last = state.get("last_alert_ts", 0)
    if time.time() - last < COOLDOWN_H * 3600:
        print(f"{stamp()} stale but within {COOLDOWN_H:.0f}h cooldown — no re-alert")
        return 0

    n_done = meta.get("n_completed", "?")
    n_all = meta.get("n_matches", "?")
    push(
        "⚠️ Oracle 数据已过期",
        f"看板 data.json 已 {age_h:.0f} 小时未更新（阈值 {THRESHOLD_H:.0f}h）。\n"
        f"最后生成：{gen_dt.strftime('%Y-%m-%d %H:%MZ')} · 进度 {n_done}/{n_all}\n"
        f"疑似 daily/matchday cron 未跑成功，请查 results/logs/。",
    )
    save_state({"alerted": True, "last_alert_ts": time.time()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
