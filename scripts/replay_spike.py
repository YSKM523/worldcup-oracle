#!/usr/bin/env python3
"""对 collector/ticks.db 回放尖峰判据，用 ESPN keyEvents 当 ground truth 打分。

调阈值前先跑这个，别拍脑袋。判据本身从 collector/spike.py 导入 —— 这里量到的
精确率/召回，就是线上采集器的精确率/召回。

    python3 scripts/replay_spike.py              # 当前线上判据
    python3 scripts/replay_spike.py --legacy     # 对比旧逻辑(pp≥4 + 队头 ref)

纯标准库，不需要 collector 的隔离 venv。真事件 = ESPN keyEvents 里的
进球/红牌/点球；推送落在真事件 ±120s 内算命中。
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import statistics
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))
import spike  # noqa: E402

DB = ROOT / "collector" / "ticks.db"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event="
OUTCOMES = ("home", "draw", "away")
MATCH_TOL_S = 120
LEGACY_PP = 0.04


def real_event(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("goal", "red card", "penalty")) and "delay" not in t


def espn_events(espn_id: str) -> list[int]:
    with urllib.request.urlopen(SUMMARY + espn_id, timeout=15) as r:
        d = json.load(r)
    out = set()
    for e in d.get("keyEvents") or []:
        wc = e.get("wallclock")
        if wc and real_event((e.get("type") or {}).get("text", "")):
            out.add(int(datetime.strptime(wc, "%Y-%m-%dT%H:%M:%SZ").timestamp()))
    return sorted(out)


def replay(rows: dict[int, dict[str, float]], legacy: bool) -> list[tuple[int, int]]:
    """返回 [(检测时刻, 实际推送时刻)]。确认档的推送时刻比检测晚 CONFIRM_S 秒。"""
    trail = {oc: [] for oc in OUTCOMES}
    cur: dict[str, float] = {}
    last_push = -1e9
    pending = None
    pushes: list[tuple[int, int]] = []
    for ts in sorted(rows):
        cur.update(rows[ts])
        ds = {}
        for oc in OUTCOMES:
            if oc not in cur:
                continue
            t = trail[oc]
            t.append((ts, cur[oc]))
            while t and ts - t[0][0] > spike.TRAIL_S:
                t.pop(0)
            # 旧逻辑取队头（实为 12~60s 窗口），新逻辑取最接近 12s 前的点
            ref = next((x for x in t if ts - x[0] >= spike.WINDOW_S), None) if legacy else spike.pick_ref(t, ts)
            if ref:
                ds[oc] = (cur[oc] - ref[1], ref[1])

        if pending and ts - pending[0] >= spike.CONFIRM_S:
            if spike.confirmed(pending[1], cur):
                last_push = ts
                pushes.append((pending[0], ts))
            pending = None

        if legacy:
            hits = {oc: v for oc, v in ds.items() if abs(v[0]) >= LEGACY_PP}
        else:
            hits = spike.spiked(ds, cur)
        if not hits or ts - last_push <= spike.COOLDOWN_S:
            continue
        if legacy or spike.is_fast(hits):
            pending = None
            last_push = ts
            pushes.append((ts, ts))
        elif pending is None:
            pending = (ts, dict(ds))
    return pushes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", action="store_true", help="回放改造前的旧判据做对比")
    args = ap.parse_args()

    if not DB.exists():
        print(f"没有 {DB}，先让采集器跑一场比赛", file=sys.stderr)
        return 1
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    n_push = n_fp = n_hit = n_ev = 0
    leads: list[int] = []
    print(f"{'比赛':<26}{'推送':>5}{'命中':>8}{'误报':>6}")
    for slug, espn_id, home, away in con.execute("select slug, espn_id, home, away from matches"):
        rows: dict[int, dict[str, float]] = collections.defaultdict(dict)
        q = "select ts_s, outcome, mid from mids where slug=? and mid is not null order by ts_s"
        for ts, oc, mid in con.execute(q, (slug,)):
            rows[ts][oc] = mid
        if not rows:
            continue
        try:
            evs = espn_events(espn_id)
        except Exception as e:  # noqa: BLE001
            print(f"{home} vs {away}: ESPN 拉取失败 {e}", file=sys.stderr)
            continue
        lo, hi = min(rows), max(rows)
        evs = [e for e in evs if lo - 60 <= e <= hi + 60]

        pushes = replay(rows, args.legacy)
        hits, fp = set(), 0
        for detect_ts, push_ts in pushes:
            near = [e for e in evs if abs(e - detect_ts) <= MATCH_TOL_S]
            if near:
                ev = min(near, key=lambda e: abs(e - detect_ts))
                hits.add(ev)
                leads.append(ev - push_ts)  # 正 = 推送早于 ESPN 记录
            else:
                fp += 1
        n_push += len(pushes)
        n_fp += fp
        n_hit += len(hits)
        n_ev += len(evs)
        print(f"{home + ' vs ' + away:<26}{len(pushes):>5}{f'{len(hits)}/{len(evs)}':>8}{fp:>6}")

    if not n_push:
        print("\n没有推送")
        return 0
    prec = (n_push - n_fp) / n_push * 100
    rec = n_hit / n_ev * 100 if n_ev else 0
    med = statistics.median(leads) if leads else 0
    tag = "旧判据 (pp≥4, 队头 ref)" if args.legacy else "当前判据 (spike.py)"
    print(f"\n{tag}")
    print(f"  推送 {n_push} 次，命中真事件 {n_hit}/{n_ev}，误报 {n_fp} 次")
    print(f"  精确率 {prec:.0f}%   召回 {rec:.0f}%   中位提前 ESPN {med:+.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
