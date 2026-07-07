"use client";

import { useEffect, useState } from "react";

/**
 * Per-match live market microstructure, browser-direct from Polymarket
 * (all endpoints CORS `*`, no auth — verified 2026-07-06):
 *  - Gamma event by slug     → 3 moneyline markets, token ids, volume
 *  - GET /book ×3            → full-depth ladder init (Yes book merges No-side liquidity)
 *  - GET /prices-history     → intra-match probability curve backfill (fidelity=1 ≈ 1pt/min)
 *  - data-api /trades ×3     → time & sales backfill
 *  - CLOB WS (own connection, panel-scoped) → book snapshots + price_change 档位增量
 *    + last_trade_price 逐笔成交。面板关闭即断开。
 */

const GAMMA = "https://gamma-api.polymarket.com/events";
const CLOB = "https://clob.polymarket.com";
const DATA_API = "https://data-api.polymarket.com";
const CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market";

const FLUSH_MS = 600; // 比赛日 price_change ~50条/秒，必须攒批渲染
const RECONNECT_MS = 5e3;
const MAX_TRADES = 60;
const MAX_CURVE_LIVE = 2400;
const CURVE_MIN_GAP_S = 2;
// 重大事件探测：中间价 SPIKE_WINDOW_S 秒内跳变 ≥ SPIKE_PP
const SPIKE_WINDOW_S = 12;
const SPIKE_PP = 0.04;
const SPIKE_TTL_MS = 45e3;

export type OutcomeSide = "home" | "draw" | "away";
export const OUTCOMES: OutcomeSide[] = ["home", "draw", "away"];

export interface BookLevel {
  price: number;
  size: number;
}
export interface OutcomeBook {
  /** best→deep（价格降序） */
  bids: BookLevel[];
  /** best→deep（价格升序） */
  asks: BookLevel[];
  bestBid: number | null;
  bestAsk: number | null;
  mid: number | null;
  /** 全簿名义深度 (USDC) */
  bidUsd: number;
  askUsd: number;
}
/** 逐笔成交，统一折算成 Yes 口径（No 成交价=1−p，方向翻转）。 */
export interface TradeItem {
  id: string;
  outcome: OutcomeSide;
  side: "BUY" | "SELL";
  price: number;
  size: number;
  /** epoch 秒 */
  ts: number;
}
export interface CurvePoint {
  t: number;
  p: number;
}
export interface SpikeAlert {
  outcome: OutcomeSide;
  delta: number;
  ts: number;
}
export interface MatchMarketState {
  status: "loading" | "live" | "error";
  wsUp: boolean;
  books: Partial<Record<OutcomeSide, OutcomeBook>>;
  /** 最新在前 */
  trades: TradeItem[];
  curves: Partial<Record<OutcomeSide, CurvePoint[]>>;
  volume: number | null;
  spike: SpikeAlert | null;
  /** 本次面板打开以来 WS 实收成交笔数 */
  liveTradeCount: number;
}

const INIT: MatchMarketState = {
  status: "loading",
  wsUp: false,
  books: {},
  trades: [],
  curves: {},
  volume: null,
  spike: null,
  liveTradeCount: 0,
};

/* ── gamma 解析（与 usePolymarket.parseMoneyline 同口径） ────────── */

interface GammaMarket {
  question?: string;
  conditionId?: string;
  clobTokenIds?: string | string[];
  volume?: number | string;
}
interface GammaEvent {
  title?: string;
  markets?: GammaMarket[];
}

interface OutcomeMeta {
  outcome: OutcomeSide;
  conditionId: string;
  yesToken: string;
  noToken: string | null;
}

function parseEvent(ev: GammaEvent): { metas: OutcomeMeta[]; volume: number } | null {
  const title = ev.title ?? "";
  if (!title.includes(" vs. ")) return null;
  const [home, away] = title.split(" vs. ", 2).map((s) => s.trim().toLowerCase());
  const metas: OutcomeMeta[] = [];
  let volume = 0;
  for (const m of ev.markets ?? []) {
    const q = (m.question ?? "").toLowerCase();
    let outcome: OutcomeSide | null = null;
    if (q.includes("draw")) outcome = "draw";
    else if (q.includes(home)) outcome = "home";
    else if (q.includes(away)) outcome = "away";
    if (!outcome || !m.conditionId) continue;
    const raw = m.clobTokenIds ?? "[]";
    const toks = typeof raw === "string" ? (JSON.parse(raw) as string[]) : raw;
    if (!toks?.[0]) continue;
    metas.push({ outcome, conditionId: m.conditionId, yesToken: toks[0], noToken: toks[1] ?? null });
    volume += Number(m.volume) || 0;
  }
  return metas.length === 3 ? { metas, volume } : null;
}

/* ── 订单簿账本 ──────────────────────────────────────────────────── */

interface Ladder {
  bids: Map<number, number>;
  asks: Map<number, number>;
}

function toBook(l: Ladder | undefined): OutcomeBook | null {
  if (!l || (l.bids.size === 0 && l.asks.size === 0)) return null;
  const bids: BookLevel[] = [...l.bids].map(([price, size]) => ({ price, size })).sort((a, b) => b.price - a.price);
  const asks: BookLevel[] = [...l.asks].map(([price, size]) => ({ price, size })).sort((a, b) => a.price - b.price);
  const bestBid = bids[0]?.price ?? null;
  const bestAsk = asks[0]?.price ?? null;
  const usd = (ls: BookLevel[]) => ls.reduce((s, x) => s + x.price * x.size, 0);
  return {
    bids,
    asks,
    bestBid,
    bestAsk,
    mid: bestBid != null && bestAsk != null ? (bestBid + bestAsk) / 2 : (bestBid ?? bestAsk),
    bidUsd: usd(bids),
    askUsd: usd(asks),
  };
}

/* ── WS 消息（只取所需字段） ─────────────────────────────────────── */

interface WsLevel {
  price: string;
  size: string;
}
interface WsMsg {
  event_type?: string;
  asset_id?: string;
  bids?: WsLevel[];
  asks?: WsLevel[];
  price?: string;
  size?: string;
  side?: string;
  timestamp?: string;
  transaction_hash?: string;
  price_changes?: { asset_id: string; price?: string; size?: string; side?: string }[];
}

/**
 * slug 为 null 或面板关闭时传 null → 不建立任何连接。
 * 全部状态 effect 作用域内自持，卸载即释放。
 */
export function useMatchMarket(slug: string | null, kickoffUtc: string): MatchMarketState {
  const [state, setState] = useState<MatchMarketState>(INIT);

  useEffect(() => {
    if (!slug) {
      setState(INIT);
      return;
    }
    let closed = false;
    let ws: WebSocket | null = null;
    let reconnect: ReturnType<typeof setTimeout>;
    let flusher: ReturnType<typeof setInterval>;

    /* effect 作用域账本（不进 React state，flush 时快照） */
    const ladders: Record<string, Ladder> = {}; // yesToken → ladder
    const tokenOutcome: Record<string, { outcome: OutcomeSide; yes: boolean }> = {};
    const histCurves: Partial<Record<OutcomeSide, CurvePoint[]>> = {};
    const liveCurves: Record<OutcomeSide, CurvePoint[]> = { home: [], draw: [], away: [] };
    const midTrail: Record<OutcomeSide, CurvePoint[]> = { home: [], draw: [], away: [] };
    const trades: TradeItem[] = [];
    const seenTrade = new Set<string>();
    let metas: OutcomeMeta[] = [];
    let volume: number | null = null;
    let spike: SpikeAlert | null = null;
    let liveTradeCount = 0;
    let wsUp = false;
    let dirty = false;

    const yesTokenOf: Partial<Record<OutcomeSide, string>> = {};

    const addTrade = (t: TradeItem, live: boolean) => {
      if (seenTrade.has(t.id)) return;
      seenTrade.add(t.id);
      trades.push(t);
      trades.sort((a, b) => b.ts - a.ts);
      if (trades.length > MAX_TRADES) trades.length = MAX_TRADES;
      if (live) liveTradeCount++;
      dirty = true;
    };

    /** 折算成 Yes 口径 */
    const normTrade = (
      tokenYes: boolean,
      outcome: OutcomeSide,
      side: string,
      price: number,
      size: number,
      ts: number,
      key: string
    ): TradeItem => ({
      id: key,
      outcome,
      side: (tokenYes ? side : side === "BUY" ? "SELL" : "BUY") as "BUY" | "SELL",
      price: tokenYes ? price : 1 - price,
      size,
      ts,
    });

    const handleWs = (m: WsMsg) => {
      const et = m.event_type;
      if (et === "book" && m.asset_id) {
        const info = tokenOutcome[m.asset_id];
        if (!info?.yes) return; // Yes 簿已合并 No 侧流动性，No 簿是镜像
        const ladder: Ladder = { bids: new Map(), asks: new Map() };
        for (const l of m.bids ?? []) ladder.bids.set(Number(l.price), Number(l.size));
        for (const l of m.asks ?? []) ladder.asks.set(Number(l.price), Number(l.size));
        ladders[m.asset_id] = ladder;
        dirty = true;
      } else if (et === "price_change") {
        for (const c of m.price_changes ?? []) {
          const info = tokenOutcome[c.asset_id];
          if (!info?.yes) continue;
          const ladder = ladders[c.asset_id];
          if (!ladder || c.price == null || c.size == null) continue;
          const sideMap = c.side === "BUY" ? ladder.bids : ladder.asks;
          const price = Number(c.price);
          const size = Number(c.size);
          if (size > 0) sideMap.set(price, size);
          else sideMap.delete(price);
          dirty = true;
        }
      } else if (et === "last_trade_price" && m.asset_id && m.price) {
        const info = tokenOutcome[m.asset_id];
        if (!info) return;
        const ts = Math.floor(Number(m.timestamp ?? Date.now()) / 1000);
        const key = `${m.transaction_hash ?? "ws"}-${m.asset_id}-${m.price}-${m.size}`;
        addTrade(
          normTrade(info.yes, info.outcome, m.side ?? "BUY", Number(m.price), Number(m.size ?? 0), ts, key),
          true
        );
      }
    };

    const flush = () => {
      if (closed) return;
      const nowS = Math.floor(Date.now() / 1000);
      const books: Partial<Record<OutcomeSide, OutcomeBook>> = {};
      for (const o of OUTCOMES) {
        const tok = yesTokenOf[o];
        const b = tok ? toBook(ladders[tok]) : null;
        if (b) books[o] = b;
        // 实时曲线追加 + 事件探测
        if (b?.mid != null) {
          const lc = liveCurves[o];
          const last = lc[lc.length - 1];
          if (!last || nowS - last.t >= CURVE_MIN_GAP_S) {
            lc.push({ t: nowS, p: b.mid });
            if (lc.length > MAX_CURVE_LIVE) lc.splice(0, lc.length - MAX_CURVE_LIVE);
          }
          const trail = midTrail[o];
          trail.push({ t: nowS, p: b.mid });
          while (trail.length && nowS - trail[0].t > 60) trail.shift();
          const ref = trail.find((x) => nowS - x.t >= SPIKE_WINDOW_S);
          if (ref) {
            const delta = b.mid - ref.p;
            if (Math.abs(delta) >= SPIKE_PP && (!spike || Math.abs(delta) > Math.abs(spike.delta) || Date.now() - spike.ts > SPIKE_TTL_MS)) {
              spike = { outcome: o, delta, ts: Date.now() };
              dirty = true;
            }
          }
        }
      }
      if (spike && Date.now() - spike.ts > SPIKE_TTL_MS) {
        spike = null;
        dirty = true;
      }
      if (!dirty) return;
      dirty = false;
      const curves: Partial<Record<OutcomeSide, CurvePoint[]>> = {};
      for (const o of OUTCOMES) {
        const merged = [...(histCurves[o] ?? []), ...liveCurves[o]];
        if (merged.length) curves[o] = merged;
      }
      setState({
        status: "live",
        wsUp,
        books,
        trades: [...trades],
        curves,
        volume,
        spike,
        liveTradeCount,
      });
    };

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(CLOB_WS);
      } catch {
        reconnect = setTimeout(connect, RECONNECT_MS);
        return;
      }
      ws.onopen = () => {
        ws?.send(JSON.stringify({ assets_ids: Object.keys(tokenOutcome), type: "market" }));
        wsUp = true;
        dirty = true;
      };
      ws.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data as string) as WsMsg | WsMsg[];
          for (const it of Array.isArray(d) ? d : [d]) handleWs(it);
        } catch {
          /* 心跳等非 JSON，忽略 */
        }
      };
      ws.onclose = () => {
        wsUp = false;
        dirty = true;
        if (!closed) reconnect = setTimeout(connect, RECONNECT_MS);
      };
      ws.onerror = () => ws?.close();
    };

    async function init() {
      const evs = (await fetch(`${GAMMA}?slug=${encodeURIComponent(slug!)}`)
        .then((r) => r.json())
        .catch(() => null)) as GammaEvent[] | null;
      if (closed) return;
      const parsed = evs?.[0] ? parseEvent(evs[0]) : null;
      if (!parsed) {
        setState({ ...INIT, status: "error" });
        return;
      }
      metas = parsed.metas;
      volume = parsed.volume;
      for (const meta of metas) {
        yesTokenOf[meta.outcome] = meta.yesToken;
        tokenOutcome[meta.yesToken] = { outcome: meta.outcome, yes: true };
        if (meta.noToken) tokenOutcome[meta.noToken] = { outcome: meta.outcome, yes: false };
      }

      // 曲线窗口：赛前看最近 3h 盘面漂移；开赛后从开球前 1h 起
      const nowS = Math.floor(Date.now() / 1000);
      const koS = Math.floor(new Date(kickoffUtc).getTime() / 1000);
      const startTs = nowS < koS ? nowS - 3 * 3600 : koS - 3600;

      const jobs: Promise<void>[] = [];
      for (const meta of metas) {
        jobs.push(
          fetch(`${CLOB}/book?token_id=${meta.yesToken}`)
            .then((r) => (r.ok ? r.json() : null))
            .then((b: { bids?: WsLevel[]; asks?: WsLevel[] } | null) => {
              if (!b || closed || ladders[meta.yesToken]) return; // WS 快照已先到则不覆盖
              const ladder: Ladder = { bids: new Map(), asks: new Map() };
              for (const l of b.bids ?? []) ladder.bids.set(Number(l.price), Number(l.size));
              for (const l of b.asks ?? []) ladder.asks.set(Number(l.price), Number(l.size));
              ladders[meta.yesToken] = ladder;
              dirty = true;
            })
            .catch(() => undefined)
        );
        jobs.push(
          fetch(`${CLOB}/prices-history?market=${meta.yesToken}&startTs=${startTs}&endTs=${nowS}&fidelity=1`)
            .then((r) => (r.ok ? r.json() : null))
            .then((h: { history?: { t: number; p: number }[] } | null) => {
              if (!h?.history || closed) return;
              histCurves[meta.outcome] = h.history.map((x) => ({ t: x.t, p: x.p }));
              dirty = true;
            })
            .catch(() => undefined)
        );
        jobs.push(
          fetch(`${DATA_API}/trades?market=${meta.conditionId}&limit=30`)
            .then((r) => (r.ok ? r.json() : null))
            .then(
              (
                arr:
                  | { side?: string; price?: number; size?: number; timestamp?: number; outcomeIndex?: number; transactionHash?: string; asset?: string }[]
                  | null
              ) => {
                if (!arr || closed) return;
                for (const t of arr) {
                  if (t.price == null || t.timestamp == null) continue;
                  const yes = t.outcomeIndex !== 1;
                  const key = `${t.transactionHash ?? "hist"}-${t.asset}-${t.price}-${t.size}`;
                  addTrade(
                    normTrade(yes, meta.outcome, t.side ?? "BUY", t.price, t.size ?? 0, t.timestamp, key),
                    false
                  );
                }
              }
            )
            .catch(() => undefined)
        );
      }
      connect();
      flusher = setInterval(flush, FLUSH_MS);
      await Promise.all(jobs);
      if (!closed) {
        dirty = true;
        flush();
      }
    }

    init();
    return () => {
      closed = true;
      clearTimeout(reconnect);
      clearInterval(flusher);
      ws?.close();
    };
  }, [slug, kickoffUtc]);

  return state;
}
