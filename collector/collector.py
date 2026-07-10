#!/usr/bin/env python3
"""Polymarket CLOB tick collector for worldcup-oracle.

Captures per-match order-book deltas, trades, and 1-second mid snapshots
into SQLite for microstructure research (goal→market latency, CLV,
order-book replay, spike backtests).

Runs 24/7 under systemd --user. For every remaining match that has a
Polymarket slug (from web/public/data.json, refreshed by the daily
pipeline), it connects during the window [kickoff−45m, kickoff+3.5h]
(covers ET + penalties) and records:

  mids         — 1 Hz best-bid/ask/mid per outcome (easy charting & replay)
  trades       — normalized Yes-口径 time & sales (No side: p→1−p, side flipped)
  history_px   — /prices-history backfill from kickoff−1h (covers late starts)

Optional: NTFY_TOPIC env → push on mid spikes (≥5pp AND ≥0.45 logit within 12s;
≥12pp pushes instantly, smaller moves wait 5s for confirmation).

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

import kalshi
import spike

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
        CREATE TABLE IF NOT EXISTS mids(
          ts_s INTEGER, slug TEXT, outcome TEXT,
          best_bid REAL, best_ask REAL, mid REAL);
        CREATE INDEX IF NOT EXISTS ix_mids ON mids(slug, outcome, ts_s);
        CREATE TABLE IF NOT EXISTS kalshi_mids(
          ts_s INTEGER, slug TEXT, outcome TEXT,
          best_bid REAL, best_ask REAL, mid REAL);
        CREATE INDEX IF NOT EXISTS ix_kalshi_mids ON kalshi_mids(slug, outcome, ts_s);
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
        # raw_events archive intentionally dropped: it stored every WS message
        # verbatim (~750B × ~2M rows ≈ 1.8GB per match) as pure debug data with
        # no downstream consumer. mids/trades are derived live from the same
        # messages, so nothing analytical is lost.
        self.mids: list[tuple] = []
        self.kalshi: list[tuple] = []
        self.trades: list[tuple] = []

    def flush(self) -> None:
        if not (self.mids or self.kalshi or self.trades):
            return
        try:
            if self.mids:
                self.con.executemany("INSERT INTO mids VALUES(?,?,?,?,?,?)", self.mids)
            if self.kalshi:
                self.con.executemany(
                    "INSERT INTO kalshi_mids VALUES(?,?,?,?,?,?)", self.kalshi
                )
            if self.trades:
                self.con.executemany(
                    "INSERT OR IGNORE INTO trades VALUES(?,?,?,?,?,?,?)", self.trades
                )
            self.con.commit()
            self.mids.clear()
            self.kalshi.clear()
            self.trades.clear()
        except Exception:  # noqa: BLE001 — a bad batch must not kill capture
            log.exception("db flush failed; dropping batch")
            self.mids.clear()
            self.kalshi.clear()
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
    """Best-effort live score + clock for push context. Never raises.

    Timeout is deliberately tight: this sits in front of the push, so a slow
    ESPN must not delay the alert. No score → push without one.
    """
    if not espn_id:
        return None
    try:
        async with sess.get(
            ESPN_SUMMARY + espn_id, timeout=aiohttp.ClientTimeout(total=1.5)
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
    pending: dict | None = None  # 待确认的中等跳变：{"ts", "ds"}
    kalshi_last: dict = {}
    n_msgs = 0

    oc_name = {"home": zh(m["home"]), "draw": "平局", "away": zh(m["away"])}
    zh_label = f"{zh(m['home'])} vs {zh(m['away'])}"

    async def push_spike(deltas: dict[str, tuple[float, float]], detect_ts: int) -> None:
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
        if (
            kalshi_last.get("ts") is not None
            and abs(detect_ts - kalshi_last["ts"]) <= kalshi.FRESH_S
        ):
            parts = []
            if "home" in kalshi_last:
                parts.append(f"{zh(m['home'])} {kalshi_last['home']*100:.0f}%")
            if "draw" in kalshi_last:
                parts.append(f"平局 {kalshi_last['draw']*100:.0f}%")
            if "away" in kalshi_last:
                parts.append(f"{zh(m['away'])} {kalshi_last['away']*100:.0f}%")
            if parts:
                lines.append("Kalshi：" + " · ".join(parts))
        # 检测时刻。收到推送时和手机时间对一下，就能量出 ntfy 端到端投递延迟。
        lines.append(datetime.fromtimestamp(detect_ts, timezone.utc).strftime("检测 %H:%M:%SZ"))
        await ntfy(sess, title, "\n".join(lines))

    def handle(msg: dict) -> None:
        nonlocal n_msgs
        et = msg.get("event_type")
        if not et:
            return
        n_msgs += 1
        # (raw_events archive removed — see Writer; mids/trades derived below)
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

    def fire(ds: dict[str, tuple[float, float]], cur: dict[str, float], detect_ts: int, tier: str) -> None:
        deltas = {oc: (cur[oc] - ref, cur[oc]) for oc, (_, ref) in ds.items() if oc in cur}
        log.info(
            "[%s] SPIKE(%s) %s",
            slug,
            tier,
            " ".join(f"{oc}{d*100:+.1f}pp" for oc, (d, _) in deltas.items()),
        )
        asyncio.ensure_future(push_spike(deltas, detect_ts))

    async def sampler() -> None:
        nonlocal last_push, pending
        while True:
            ts = int(time.time())
            cur: dict[str, float] = {}
            ds: dict[str, tuple[float, float]] = {}  # oc → (Δ12s, ref_mid)
            for oc in OUTCOMES:
                lad = ladders.get(yes_of[oc])
                if not lad or not (lad["bids"] or lad["asks"]):
                    continue
                bb = max(lad["bids"]) if lad["bids"] else None
                ba = min(lad["asks"]) if lad["asks"] else None
                mid = (bb + ba) / 2 if bb is not None and ba is not None else (bb or ba)
                w.mids.append((ts, slug, oc, bb, ba, mid))
                if mid is None:
                    continue
                cur[oc] = mid
                trail = mid_trail[oc]
                trail.append((ts, mid))
                while trail and ts - trail[0][0] > spike.TRAIL_S:
                    trail.pop(0)
                ref = spike.pick_ref(trail, ts)
                if ref:
                    ds[oc] = (mid - ref[1], ref[1])

            # 到期的待确认候选：站住了才推，回撤的直接丢弃
            if pending and ts - pending["ts"] >= spike.CONFIRM_S:
                if spike.confirmed(pending["ds"], cur):
                    last_push = ts
                    fire(pending["ds"], cur, pending["ts"], "confirmed")
                else:
                    log.info("[%s] spike reverted, dropped", slug)
                pending = None

            hits = spike.spiked(ds, cur)
            if hits and ts - last_push > spike.COOLDOWN_S:
                if spike.is_fast(hits):
                    # 进球级：立即推，绝不为确认多等 5 秒
                    pending = None
                    last_push = ts
                    fire(ds, cur, ts, "instant")
                elif pending is None:
                    pending = {"ts": ts, "ds": dict(ds)}
            w.flush()
            await asyncio.sleep(MID_SAMPLE_S)

    async def kalshi_poller() -> None:
        legs = None
        for attempt in range(kalshi.RESOLVE_ATTEMPTS):
            try:
                legs = await kalshi.resolve(sess, m["home"], m["away"])
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — Kalshi 缺席不能打断 Polymarket 主链路
                legs = None
            if legs:
                break
            if attempt + 1 < kalshi.RESOLVE_ATTEMPTS:
                await asyncio.sleep(kalshi.RESOLVE_RETRY_S)
        if not legs:
            log.info("[%s] Kalshi resolution failed — giving up", slug)
            return

        failures = 0
        while True:
            try:
                quotes = await kalshi.poll_once(sess, legs)
                ts = int(time.time())
                snapshot = {"ts": ts}
                for oc, (bid, ask, mid) in quotes.items():
                    w.kalshi.append((ts, slug, oc, bid, ask, mid))
                    if mid is not None:
                        snapshot[oc] = mid
                kalshi_last.clear()
                kalshi_last.update(snapshot)
                failures = 0
                await asyncio.sleep(kalshi.POLL_S)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 独立降级，不影响 CLOB 采集
                failures += 1
                if failures == 1 or failures % 60 == 0:
                    log.warning(
                        "[%s] Kalshi poll error (%d consecutive): %s",
                        slug,
                        failures,
                        exc,
                    )
                await asyncio.sleep(5)

    async def pinger(ws: aiohttp.ClientWebSocketResponse) -> None:
        while not ws.closed:
            await ws.send_str("PING")
            await asyncio.sleep(WS_PING_S)

    log.info("[%s] capture start (%s), window until %s",
             slug, label, datetime.fromtimestamp(until, tz=timezone.utc).strftime("%H:%MZ"))
    samp = asyncio.ensure_future(sampler())
    kal = asyncio.ensure_future(kalshi_poller())
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
        kal.cancel()
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
