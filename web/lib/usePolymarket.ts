"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Match, PolyLive, PolyMatchOdds } from "./types";
import { canonicalTeam, kickoffEpoch } from "./wc";

const GAMMA = "https://gamma-api.polymarket.com/events";
const CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market";
const CHAMPION_SLUG = "world-cup-winner";
const POLL_MS = 5 * 60e3; // Gamma CDN caches 5 min — champion 榜 + WS 兜底用
const WS_FLUSH_MS = 2e3; // WS 推送很密(比赛日>60条/秒)，攒 2s 再刷 React state
const WS_RECONNECT_MS = 5e3;
// Live window around now: just-finished through the next ~30h of fixtures.
const WINDOW_BEFORE_MS = 3 * 3600e3;
const WINDOW_AFTER_MS = 30 * 3600e3;

interface GammaMarket {
  question?: string;
  outcomePrices?: string | string[];
  clobTokenIds?: string | string[];
}
interface GammaEvent {
  title?: string;
  endDate?: string;
  markets?: GammaMarket[];
}

const yesPrice = (m: GammaMarket): number | null => {
  const raw = m.outcomePrices ?? "[]";
  const arr = typeof raw === "string" ? (JSON.parse(raw) as string[]) : raw;
  const p = Number(arr?.[0]);
  return Number.isFinite(p) ? p : null;
};

/** clobTokenIds[0] 与 outcomes[0]="Yes" 对应。 */
const yesToken = (m: GammaMarket): string | null => {
  const raw = m.clobTokenIds ?? "[]";
  const arr = typeof raw === "string" ? (JSON.parse(raw) as string[]) : raw;
  return arr?.[0] ?? null;
};

function parseChampion(ev: GammaEvent): Record<string, number> {
  const out: Record<string, number> = {};
  for (const m of ev.markets ?? []) {
    let name = m.question ?? "";
    name = name.replace(/^Will\s+/i, "");
    name = name.replace(/\s+win the .*$/i, "").trim();
    const price = yesPrice(m);
    if (name && price != null) out[canonicalTeam(name)] = price;
  }
  return out;
}

type Side = "home" | "draw" | "away";
interface ParsedMoneyline {
  key: string;
  odds: PolyMatchOdds;
  /** Yes-token id → 该 token 对应哪个结果 */
  tokens: Record<string, Side>;
}

function parseMoneyline(ev: GammaEvent): ParsedMoneyline | null {
  const title = ev.title ?? "";
  if (!title.includes(" vs. ") || !ev.endDate || (ev.markets?.length ?? 0) !== 3) return null;
  const [home, away] = title.split(" vs. ", 2).map((s) => s.trim().toLowerCase());
  let h: number | null = null;
  let d: number | null = null;
  let a: number | null = null;
  const tokens: Record<string, Side> = {};
  for (const m of ev.markets ?? []) {
    const q = (m.question ?? "").toLowerCase();
    const p = yesPrice(m);
    if (p == null) continue;
    let side: Side | null = null;
    if (q.includes("draw")) side = "draw";
    else if (q.includes(home)) side = "home";
    else if (q.includes(away)) side = "away";
    if (!side) continue;
    if (side === "home") h = p;
    else if (side === "draw") d = p;
    else a = p;
    const tok = yesToken(m);
    if (tok) tokens[tok] = side;
  }
  if (h == null || d == null || a == null) return null;
  return { key: kickoffEpoch(ev.endDate), odds: { home: h, draw: d, away: a, src: "gamma" }, tokens };
}

/* ── CLOB WS 消息(只取所需字段) ─────────────────────────────────── */
interface WsBookLevel {
  price: string;
  size: string;
}
interface WsMsg {
  event_type?: string;
  asset_id?: string;
  bids?: WsBookLevel[];
  asks?: WsBookLevel[];
  price?: string; // last_trade_price
  price_changes?: { asset_id: string; best_bid?: string; best_ask?: string }[];
}

/** book 快照 → 最优买/卖价（防御式取 max/min，不依赖数组顺序）。 */
function bookBest(levels: WsBookLevel[] | undefined, kind: "bid" | "ask"): number | null {
  if (!levels?.length) return null;
  let best: number | null = null;
  for (const l of levels) {
    const p = Number(l.price);
    if (!Number.isFinite(p)) continue;
    if (best == null || (kind === "bid" ? p > best : p < best)) best = p;
  }
  return best;
}

const mid = (bid: number | null, ask: number | null, last: number | null): number | null =>
  bid != null && ask != null ? (bid + ask) / 2 : (last ?? bid ?? ask);

/**
 * Client-side live Polymarket odds:
 *  - Gamma API 5 分钟轮询：champion 榜 + 每场兜底价 + 解析 CLOB token id
 *  - CLOB WebSocket：窗口内比赛逐笔推送 best bid/ask，2s 节流合成中间价
 * Falls back silently to the data.json snapshot on any failure.
 */
export function usePolymarket(matches: Match[]): PolyLive {
  const slugs = useMemo(() => {
    const now = Date.now();
    const lo = now - WINDOW_BEFORE_MS;
    const hi = now + WINDOW_AFTER_MS;
    const list: string[] = [];
    for (const m of matches) {
      if (!m.market?.slug) continue;
      const t = new Date(m.kickoff_utc).getTime();
      if (t >= lo && t <= hi) list.push(m.market.slug);
    }
    return Array.from(new Set(list));
  }, [matches]);
  const slugKey = slugs.join(",");

  const [live, setLive] = useState<PolyLive>({
    champion: {},
    matches: {},
    championFresh: false,
    updatedAt: null,
    wsConnected: false,
  });
  // token → 场次/方向 映射（gamma 解析出来，WS 订阅用）
  const [assetMap, setAssetMap] = useState<Record<string, { key: string; side: Side }>>({});
  // WS 报价缓存（ref，不触发渲染；定时 flush）
  const quotes = useRef<Record<string, { bid: number | null; ask: number | null; last: number | null }>>({});
  const gammaOdds = useRef<Record<string, PolyMatchOdds>>({});

  /* ── 1. Gamma 轮询 ──────────────────────────────────────────── */
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;

    const getEvents = (params: string) =>
      fetch(`${GAMMA}?${params}`)
        .then((r) => r.json() as Promise<GammaEvent[]>)
        .catch(() => null);

    async function refresh() {
      const matchSlugs = slugKey ? slugKey.split(",") : [];
      const [champRes, ...matchRes] = await Promise.all([
        getEvents(`slug=${CHAMPION_SLUG}`),
        ...matchSlugs.map((s) => getEvents(`slug=${encodeURIComponent(s)}`)),
      ]);
      if (cancelled) return;

      const champion = champRes?.[0] ? parseChampion(champRes[0]) : {};
      const championFresh = Object.keys(champion).length > 0;
      const nextMap: Record<string, { key: string; side: Side }> = {};
      const nextGamma: Record<string, PolyMatchOdds> = {};
      for (const res of matchRes) {
        const parsed = res?.[0] ? parseMoneyline(res[0]) : null;
        if (!parsed) continue;
        nextGamma[parsed.key] = parsed.odds;
        for (const [tok, side] of Object.entries(parsed.tokens)) {
          nextMap[tok] = { key: parsed.key, side };
        }
      }
      gammaOdds.current = nextGamma;
      setAssetMap((prev) => {
        const a = Object.keys(prev).sort().join();
        const b = Object.keys(nextMap).sort().join();
        return a === b ? prev : nextMap; // token 集不变则不重连 WS
      });
      if (championFresh || Object.keys(nextGamma).length) {
        setLive((s) => ({
          ...s,
          champion: championFresh ? champion : s.champion,
          championFresh: championFresh || s.championFresh,
          // gamma 价只填 WS 尚无报价的场次，不覆盖实时价
          matches: { ...nextGamma, ...pickWs(s.matches) },
          updatedAt: Date.now(),
        }));
      }
      timer = setTimeout(refresh, POLL_MS);
    }
    const pickWs = (m: Record<string, PolyMatchOdds>) =>
      Object.fromEntries(Object.entries(m).filter(([, v]) => v.src === "ws"));

    refresh();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [slugKey]);

  /* ── 2. CLOB WebSocket 实时层 ───────────────────────────────── */
  const assetKey = Object.keys(assetMap).sort().join(",");
  useEffect(() => {
    const tokens = assetKey ? assetKey.split(",") : [];
    if (!tokens.length) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let reconnect: ReturnType<typeof setTimeout>;
    let flusher: ReturnType<typeof setInterval>;
    let dirty = false;

    const handle = (it: WsMsg) => {
      const upsert = (tok: string | undefined, patch: Partial<{ bid: number | null; ask: number | null; last: number | null }>) => {
        if (!tok || !(tok in assetMap)) return;
        const q = (quotes.current[tok] ??= { bid: null, ask: null, last: null });
        Object.assign(q, patch);
        dirty = true;
      };
      if (it.event_type === "book") {
        upsert(it.asset_id, { bid: bookBest(it.bids, "bid"), ask: bookBest(it.asks, "ask") });
      } else if (it.event_type === "price_change") {
        for (const c of it.price_changes ?? []) {
          upsert(c.asset_id, {
            ...(c.best_bid != null ? { bid: Number(c.best_bid) } : {}),
            ...(c.best_ask != null ? { ask: Number(c.best_ask) } : {}),
          });
        }
      } else if (it.event_type === "last_trade_price") {
        upsert(it.asset_id, { last: Number(it.price) });
      }
    };

    const flush = () => {
      if (!dirty) return;
      dirty = false;
      // 按场次聚合三个方向的中间价；缺的方向用 gamma 兜底
      const byKey: Record<string, Partial<Record<Side, number>>> = {};
      for (const [tok, { key, side }] of Object.entries(assetMap)) {
        const q = quotes.current[tok];
        if (!q) continue;
        const p = mid(q.bid, q.ask, q.last);
        if (p != null) (byKey[key] ??= {})[side] = p;
      }
      const now = Date.now();
      setLive((s) => {
        const matches = { ...s.matches };
        for (const [key, sides] of Object.entries(byKey)) {
          const base = matches[key] ?? gammaOdds.current[key];
          if (!base && (sides.home == null || sides.draw == null || sides.away == null)) continue;
          matches[key] = {
            home: sides.home ?? base!.home,
            draw: sides.draw ?? base!.draw,
            away: sides.away ?? base!.away,
            src: "ws",
            ts: now,
          };
        }
        return { ...s, matches, updatedAt: now };
      });
    };

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(CLOB_WS);
      } catch {
        reconnect = setTimeout(connect, WS_RECONNECT_MS);
        return;
      }
      ws.onopen = () => {
        ws?.send(JSON.stringify({ assets_ids: tokens, type: "market" }));
        setLive((s) => ({ ...s, wsConnected: true }));
      };
      ws.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data as string) as WsMsg | WsMsg[];
          for (const it of Array.isArray(d) ? d : [d]) handle(it);
        } catch {
          /* 非 JSON 心跳等，忽略 */
        }
      };
      ws.onclose = () => {
        setLive((s) => ({ ...s, wsConnected: false }));
        if (!closed) reconnect = setTimeout(connect, WS_RECONNECT_MS);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    flusher = setInterval(flush, WS_FLUSH_MS);
    return () => {
      closed = true;
      clearTimeout(reconnect);
      clearInterval(flusher);
      ws?.close();
      setLive((s) => ({ ...s, wsConnected: false }));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetKey]);

  return live;
}
