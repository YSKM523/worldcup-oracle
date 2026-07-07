#!/usr/bin/env python3
"""Polymarket CLOB tick collector for worldcup-oracle.

Captures per-match order-book deltas, trades, and 1-second mid snapshots
into SQLite for microstructure research (goal→market latency, CLV,
order-book replay, spike backtests).

Runs 24/7 under systemd --user. For every remaining match that has a
Polymarket slug (from web/public/data.json, refreshed by the daily
pipeline), it connects during the window [kickoff−45m, kickoff+3.5h]
(covers ET + penalties) and records:

  raw_events   — every WS message verbatim (book / price_change / last_trade_price)
  mids         — 1 Hz best-bid/ask/mid per outcome (easy charting & replay)
  trades       — normalized Yes-口径 time & sales (No side: p→1−p, side flipped)
  history_px   — /prices-history backfill from kickoff−1h (covers late starts)

Optional: NTFY_TOPIC env → push on mid spikes (≥4pp within 12s).

Protocol notes (mirrors web/lib/useMatchMarket.ts, field-verified 2026-07-06):
  - subscribe: {"assets_ids": [...yes+no tokens...], "type": "market"}
  - Yes book already merges No-side liquidity; No book is a mirror → only
    track Yes ladders, but subscribe both so No-side trades stream in.
  - price_change carries {price_changes:[{asset_id, price, size, side}]}.

Isolated venv (aiohttp only) — do NOT install into the shared research venv.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_JSON = ROOT / "web" / "public" / "data.json"
DB_PATH = HERE / "ticks.db"

GAMMA = "https://gamma-api.polymarket.com/events"
CLOB = "https://clob.polymarket.com"
CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

PRE_S = 45 * 60
POST_S = int(3.5 * 3600)
SCHED_REFRESH_S = 60
FLUSH_S = 2.0
MID_SAMPLE_S = 1.0
WS_PING_S = 10
RECONNECT_S = 5

SPIKE_WINDOW_S = 12
SPIKE_PP = 0.04
SPIKE_COOLDOWN_S = 60
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

OUTCOMES = ("home", "draw", "away")

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event="

# 中文队名（与 web/lib/wc.ts ZH 同源）
ZH = {
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


def zh(name: str) -> str:
    return ZH.get(name, name)


log = logging.getLogger("collector")


# ── DB ──────────────────────────────────────────────────────────────


def db_init() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS matches(
          slug TEXT PRIMARY KEY, espn_id TEXT, home TEXT, away TEXT,
          kickoff_utc TEXT, stage TEXT);
        CREATE TABLE IF NOT EXISTS raw_events(
          id INTEGER PRIMARY KEY, ts_ms INTEGER, slug TEXT,
          event_type TEXT, payload TEXT);
        CREATE INDEX IF NOT EXISTS ix_raw ON raw_events(slug, ts_ms);
        CREATE TABLE IF NOT EXISTS mids(
          ts_s INTEGER, slug TEXT, outcome TEXT,
          best_bid REAL, best_ask REAL, mid REAL);
        CREATE INDEX IF NOT EXISTS ix_mids ON mids(slug, outcome, ts_s);
        CREATE TABLE IF NOT EXISTS trades(
          key TEXT PRIMARY KEY, ts_s INTEGER, slug TEXT, outcome TEXT,
          side TEXT, price REAL, size REAL);
        CREATE INDEX IF NOT EXISTS ix_trades ON trades(slug, ts_s);
        CREATE TABLE IF NOT EXISTS history_px(
          slug TEXT, outcome TEXT, ts_s INTEGER, p REAL,
          PRIMARY KEY(slug, outcome, ts_s));
        """
    )
    con.commit()
    return con


class Writer:
    """Batched single-writer; asyncio is single-threaded so no locks."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.raw: list[tuple] = []
        self.mids: list[tuple] = []
        self.trades: list[tuple] = []

    def flush(self) -> None:
        if not (self.raw or self.mids or self.trades):
            return
        try:
            if self.raw:
                self.con.executemany(
                    "INSERT INTO raw_events(ts_ms,slug,event_type,payload) VALUES(?,?,?,?)",
                    self.raw,
                )
            if self.mids:
                self.con.executemany("INSERT INTO mids VALUES(?,?,?,?,?,?)", self.mids)
            if self.trades:
                self.con.executemany(
                    "INSERT OR IGNORE INTO trades VALUES(?,?,?,?,?,?,?)", self.trades
                )
            self.con.commit()
            self.raw.clear()
            self.mids.clear()
            self.trades.clear()
        except Exception:  # noqa: BLE001 — a bad batch must not kill capture
            log.exception("db flush failed; dropping batch")
            self.raw.clear()
            self.mids.clear()
            self.trades.clear()


# ── gamma resolution (mirrors parseEvent in useMatchMarket.ts) ──────


async def resolve_tokens(sess: aiohttp.ClientSession, slug: str) -> dict | None:
    """slug → {outcome: {yes, no, conditionId}}; None if not a 3-way event."""
    try:
        async with sess.get(GAMMA, params={"slug": slug}) as r:
            evs = await r.json()
    except Exception:  # noqa: BLE001
        return None
    ev = evs[0] if evs else None
    if not ev:
        return None
    title = ev.get("title", "")
    if " vs. " not in title:
        return None
    home, away = (s.strip().lower() for s in title.split(" vs. ", 1))
    metas: dict[str, dict] = {}
    for m in ev.get("markets", []):
        q = (m.get("question") or "").lower()
        if "draw" in q:
            oc = "draw"
        elif home in q:
            oc = "home"
        elif away in q:
            oc = "away"
        else:
            continue
        raw = m.get("clobTokenIds") or "[]"
        toks = json.loads(raw) if isinstance(raw, str) else raw
        if not toks:
            continue
        metas[oc] = {
            "yes": toks[0],
            "no": toks[1] if len(toks) > 1 else None,
            "conditionId": m.get("conditionId"),
        }
    return metas if len(metas) == 3 else None


# ── per-match capture task ──────────────────────────────────────────


async def ntfy(sess: aiohttp.ClientSession, title: str, body: str) -> None:
    if not NTFY_TOPIC:
        return
    try:
        # 非 ASCII 标题必须走 RFC 2047 且客户端支持参差；ntfy 官方姿势是
        # 标题放 X-Title（UTF-8 需 ?utf-8?b? 编码），正文原生 UTF-8。
        import base64

        enc_title = "=?UTF-8?B?" + base64.b64encode(title.encode()).decode() + "?="
        await sess.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode(),
            headers={"X-Title": enc_title, "Priority": "high", "Tags": "soccer"},
            timeout=aiohttp.ClientTimeout(total=10),
        )
    except Exception:  # noqa: BLE001
        log.warning("ntfy push failed")


async def espn_live(sess: aiohttp.ClientSession, espn_id: str) -> dict | None:
    """Best-effort live score + clock for push context. Never raises."""
    if not espn_id:
        return None
    try:
        async with sess.get(
            ESPN_SUMMARY + espn_id, timeout=aiohttp.ClientTimeout(total=6)
        ) as r:
            d = await r.json()
        comp = (d.get("header", {}).get("competitions") or [{}])[0]
        status = comp.get("status", {})
        clock = status.get("displayClock") or status.get("type", {}).get("detail") or ""
        state = status.get("type", {}).get("state", "")
        out = {"clock": str(clock).strip(), "state": state, "home": None, "away": None}
        for c in comp.get("competitors", []):
            side = c.get("homeAway")
            if side in ("home", "away"):
                out[side] = c.get("score")
        return out
    except Exception:  # noqa: BLE001
        return None


async def capture_match(m: dict, w: Writer, sess: aiohttp.ClientSession, until: float) -> None:
    slug = m["slug"]
    label = f"{m['home']} vs {m['away']}"
    metas = None
    for _ in range(5):
        metas = await resolve_tokens(sess, slug)
        if metas:
            break
        await asyncio.sleep(30)
    if not metas:
        log.error("[%s] token resolution failed — giving up", slug)
        return

    w.con.execute(
        "INSERT OR REPLACE INTO matches VALUES(?,?,?,?,?,?)",
        (slug, m["espn_id"], m["home"], m["away"], m["kickoff_utc"], m.get("stage", "")),
    )
    w.con.commit()

    token_info: dict[str, tuple[str, bool]] = {}  # asset_id → (outcome, is_yes)
    yes_of: dict[str, str] = {}
    for oc, t in metas.items():
        yes_of[oc] = t["yes"]
        token_info[t["yes"]] = (oc, True)
        if t["no"]:
            token_info[t["no"]] = (oc, False)

    # prices-history backfill from kickoff−1h (covers a late collector start)
    ko = datetime.fromisoformat(m["kickoff_utc"].replace("Z", "+00:00")).timestamp()
    now = time.time()
    start_ts = int(min(now, ko - 3600))
    for oc in OUTCOMES:
        try:
            async with sess.get(
                f"{CLOB}/prices-history",
                params={"market": yes_of[oc], "startTs": start_ts, "endTs": int(now), "fidelity": 1},
            ) as r:
                h = await r.json() if r.status == 200 else None
            for pt in (h or {}).get("history", []):
                w.con.execute(
                    "INSERT OR IGNORE INTO history_px VALUES(?,?,?,?)",
                    (slug, oc, int(pt["t"]), float(pt["p"])),
                )
        except Exception:  # noqa: BLE001
            log.warning("[%s] history backfill failed for %s", slug, oc)
    w.con.commit()

    ladders: dict[str, dict[str, dict[float, float]]] = {}  # yes_token → {bids:{p:s}, asks:{p:s}}
    mid_trail: dict[str, list[tuple[float, float]]] = {oc: [] for oc in OUTCOMES}
    last_push = 0.0  # 事件级冷却：一次进球三条线齐跳，只推一条聚合消息
    n_msgs = 0

    oc_name = {"home": zh(m["home"]), "draw": "平局", "away": zh(m["away"])}
    zh_label = f"{zh(m['home'])} vs {zh(m['away'])}"

    async def push_spike(deltas: dict[str, tuple[float, float]]) -> None:
        """deltas: outcome → (delta, current_mid)。取 ESPN 比分/时钟拼上下文后推送。"""
        lv = await espn_live(sess, m["espn_id"])
        # 主角 = 跳幅最大的结果；涨=利好该方向（疑似其进球/对方红牌）
        star_oc, (star_d, _) = max(deltas.items(), key=lambda kv: abs(kv[1][0]))
        what = (
            f"利好{oc_name[star_oc]}（疑似{oc_name[star_oc]}进球或对方红牌/点球）"
            if star_d > 0 and star_oc != "draw"
            else f"趋向平局" if star_oc == "draw" and star_d > 0
            else f"利空{oc_name[star_oc]}"
        )
        score = ""
        clock = ""
        if lv:
            if lv.get("home") is not None and lv.get("away") is not None:
                score = f"{lv['home']}-{lv['away']}"
            clock = lv.get("clock") or ""
        title = f"⚡ {zh(m['home'])} {score or 'vs'} {zh(m['away'])}" + (f" · {clock}" if clock else "")
        lines = [f"盘口 12 秒内剧烈波动，{what}"]
        for oc in OUTCOMES:
            if oc in deltas:
                d, mid = deltas[oc]
                lines.append(f"{oc_name[oc]} {d*100:+.1f}pp → {mid*100:.1f}%")
        if clock or score:
            lines.append(f"实时：{score or '?'}{'，' + clock if clock else ''}（ESPN）")
        await ntfy(sess, title, "\n".join(lines))

    def handle(msg: dict) -> None:
        nonlocal n_msgs
        et = msg.get("event_type")
        if not et:
            return
        n_msgs += 1
        w.raw.append((int(time.time() * 1000), slug, et, json.dumps(msg, separators=(",", ":"))))
        if et == "book":
            aid = msg.get("asset_id", "")
            info = token_info.get(aid)
            if not info or not info[1]:
                return
            ladders[aid] = {
                "bids": {float(x["price"]): float(x["size"]) for x in msg.get("bids", [])},
                "asks": {float(x["price"]): float(x["size"]) for x in msg.get("asks", [])},
            }
        elif et == "price_change":
            for c in msg.get("price_changes", []):
                info = token_info.get(c.get("asset_id", ""))
                if not info or not info[1]:
                    continue
                lad = ladders.get(c["asset_id"])
                if lad is None or c.get("price") is None or c.get("size") is None:
                    continue
                side = lad["bids"] if c.get("side") == "BUY" else lad["asks"]
                p, s = float(c["price"]), float(c["size"])
                if s > 0:
                    side[p] = s
                else:
                    side.pop(p, None)
        elif et == "last_trade_price":
            aid = msg.get("asset_id", "")
            info = token_info.get(aid)
            if not info or msg.get("price") is None:
                return
            oc, is_yes = info
            price = float(msg["price"])
            side = msg.get("side", "BUY")
            if not is_yes:
                price = 1 - price
                side = "SELL" if side == "BUY" else "BUY"
            ts = int(float(msg.get("timestamp", time.time() * 1000)) / 1000)
            key = f"{msg.get('transaction_hash','ws')}-{aid}-{msg.get('price')}-{msg.get('size')}"
            w.trades.append((key, ts, slug, oc, side, price, float(msg.get("size") or 0)))

    async def sampler() -> None:
        nonlocal last_push
        while True:
            ts = int(time.time())
            deltas: dict[str, tuple[float, float]] = {}  # oc → (Δ12s, mid)
            spiked = False
            for oc in OUTCOMES:
                lad = ladders.get(yes_of[oc])
                if not lad or not (lad["bids"] or lad["asks"]):
                    continue
                bb = max(lad["bids"]) if lad["bids"] else None
                ba = min(lad["asks"]) if lad["asks"] else None
                mid = (bb + ba) / 2 if bb is not None and ba is not None else (bb or ba)
                w.mids.append((ts, slug, oc, bb, ba, mid))
                if mid is not None:
                    trail = mid_trail[oc]
                    trail.append((ts, mid))
                    while trail and ts - trail[0][0] > 60:
                        trail.pop(0)
                    ref = next((x for x in trail if ts - x[0] >= SPIKE_WINDOW_S), None)
                    if ref:
                        delta = mid - ref[1]
                        deltas[oc] = (delta, mid)
                        if abs(delta) >= SPIKE_PP:
                            spiked = True
            if spiked and ts - last_push > SPIKE_COOLDOWN_S:
                last_push = ts
                log.info(
                    "[%s] SPIKE %s",
                    slug,
                    " ".join(f"{oc}{d*100:+.1f}pp" for oc, (d, _) in deltas.items()),
                )
                asyncio.ensure_future(push_spike(dict(deltas)))
            w.flush()
            await asyncio.sleep(MID_SAMPLE_S)

    async def pinger(ws: aiohttp.ClientWebSocketResponse) -> None:
        while not ws.closed:
            await ws.send_str("PING")
            await asyncio.sleep(WS_PING_S)

    log.info("[%s] capture start (%s), window until %s",
             slug, label, datetime.fromtimestamp(until, tz=timezone.utc).strftime("%H:%MZ"))
    samp = asyncio.ensure_future(sampler())
    try:
        while time.time() < until:
            try:
                async with sess.ws_connect(CLOB_WS, heartbeat=20) as ws:
                    await ws.send_str(json.dumps({"assets_ids": list(token_info), "type": "market"}))
                    log.info("[%s] WS connected (%d tokens)", slug, len(token_info))
                    async for frame in ws:
                        if frame.type != aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            d = json.loads(frame.data)
                        except ValueError:
                            continue  # PONG / heartbeats
                        for item in d if isinstance(d, list) else [d]:
                            if isinstance(item, dict):
                                handle(item)
                        if time.time() >= until:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] WS error: %s — reconnect in %ss", slug, exc, RECONNECT_S)
            if time.time() < until:
                await asyncio.sleep(RECONNECT_S)
    finally:
        samp.cancel()
        w.flush()
        log.info("[%s] capture end — %d msgs", slug, n_msgs)


# ── schedule loop ───────────────────────────────────────────────────


def load_schedule() -> list[dict]:
    try:
        data = json.loads(DATA_JSON.read_text())
    except Exception:  # noqa: BLE001
        log.exception("cannot read %s", DATA_JSON)
        return []
    out = []
    for m in data.get("matches", []):
        slug = (m.get("market") or {}).get("slug")
        if not slug or m.get("tbd"):
            continue
        out.append(
            {
                "slug": slug,
                "espn_id": m.get("espn_id", ""),
                "home": m.get("home", ""),
                "away": m.get("away", ""),
                "kickoff_utc": m["kickoff_utc"],
                "stage": m.get("stage", ""),
            }
        )
    return out


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    con = db_init()
    w = Writer(con)
    tasks: dict[str, asyncio.Task] = {}
    async with aiohttp.ClientSession() as sess:
        log.info("collector up — db=%s ntfy=%s", DB_PATH, NTFY_TOPIC or "off")
        while True:
            now = time.time()
            for m in load_schedule():
                slug = m["slug"]
                try:
                    ko = datetime.fromisoformat(m["kickoff_utc"].replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                start, until = ko - PRE_S, ko + POST_S
                active = start <= now < until
                running = slug in tasks and not tasks[slug].done()
                if active and not running:
                    tasks[slug] = asyncio.ensure_future(capture_match(m, w, sess, until))
            # reap finished
            for slug in [s for s, t in tasks.items() if t.done()]:
                exc = tasks[slug].exception() if not tasks[slug].cancelled() else None
                if exc:
                    log.error("[%s] task died: %s", slug, exc)
                del tasks[slug]
            await asyncio.sleep(SCHED_REFRESH_S)


if __name__ == "__main__":
    asyncio.run(main())
