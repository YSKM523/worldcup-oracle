"use client";

import { useEffect, useMemo, useState } from "react";
import {
  OUTCOMES,
  useMatchMarket,
  type CurvePoint,
  type MatchMarketState,
  type OutcomeBook,
  type OutcomeSide,
  type TradeItem,
} from "@/lib/useMatchMarket";
import { useInplayCurve, type InplayCurves } from "@/lib/useInplayCurve";
import type { LiveEntry, Pred } from "@/lib/types";
import { zh } from "@/lib/wc";

/* 与 WdlBar 同色系：主=emerald-400 / 平=zinc-400 / 客=rose-500（纯色，无渐变） */
const COLOR: Record<OutcomeSide, string> = {
  home: "#34d399",
  draw: "#a1a1aa",
  away: "#f43f5e",
};
const TEXT_CLS: Record<OutcomeSide, string> = {
  home: "text-emerald-400",
  draw: "text-zinc-300",
  away: "text-rose-400",
};

const cents = (p: number, digits = 1) => `${(p * 100).toFixed(digits)}¢`;
const pp = (d: number) => `${d > 0 ? "+" : ""}${(d * 100).toFixed(1)}pp`;
const usd = (n: number) =>
  n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${(n / 1e3).toFixed(1)}k` : `$${n.toFixed(0)}`;
const hhmm = (t: number) =>
  new Date(t * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
const hhmmss = (t: number) =>
  new Date(t * 1000).toLocaleTimeString("zh-CN", { hour12: false });

function outcomeLabel(o: OutcomeSide, home: string, away: string): string {
  return o === "home" ? zh(home) : o === "draw" ? "平局" : zh(away);
}

/* ── 场内概率曲线（SVG 手绘，无图表库） ─────────────────────────── */

const CW = 640;
const CH = 170;
const PAD = { l: 34, r: 70, t: 10, b: 18 };

function downsample(pts: CurvePoint[], max: number): CurvePoint[] {
  if (pts.length <= max) return pts;
  const stride = Math.ceil(pts.length / max);
  const out: CurvePoint[] = [];
  for (let i = 0; i < pts.length; i += stride) out.push(pts[i]);
  if (out[out.length - 1] !== pts[pts.length - 1]) out.push(pts[pts.length - 1]);
  return out;
}

function ProbChart({
  curves,
  aiCurves,
  kickoffUtc,
  spikeOutcome,
  home,
  away,
}: {
  curves: MatchMarketState["curves"];
  aiCurves?: InplayCurves;
  kickoffUtc: string;
  spikeOutcome: OutcomeSide | null;
  home: string;
  away: string;
}) {
  const all = OUTCOMES.flatMap((o) => [...(curves[o] ?? []), ...(aiCurves?.[o] ?? [])]);
  if (!all.length)
    return <div className="py-8 text-center text-xs text-zinc-600">价格历史加载中…</div>;

  let t0 = Infinity;
  let t1 = -Infinity;
  let pMax = 0;
  for (const x of all) {
    if (x.t < t0) t0 = x.t;
    if (x.t > t1) t1 = x.t;
    if (x.p > pMax) pMax = x.p;
  }
  if (t1 - t0 < 60) t0 = t1 - 60;
  const hi = Math.min(1, Math.max(0.3, Math.ceil((pMax + 0.06) * 10) / 10));
  const X = (t: number) => PAD.l + ((t - t0) / (t1 - t0)) * (CW - PAD.l - PAD.r);
  const Y = (p: number) => PAD.t + (1 - p / hi) * (CH - PAD.t - PAD.b);

  const yStep = hi > 0.5 ? 0.25 : 0.1;
  const yTicks: number[] = [];
  for (let v = yStep; v < hi - 1e-9; v += yStep) yTicks.push(v);
  const xTicks = [t0 + (t1 - t0) * 0.15, t0 + (t1 - t0) * 0.5, t0 + (t1 - t0) * 0.85];
  const koS = Math.floor(new Date(kickoffUtc).getTime() / 1000);
  const showKo = koS > t0 + 60 && koS < t1 - 60;

  // end-of-line labels (which line is which team / draw), de-overlapped
  const labelName = (o: OutcomeSide) => {
    const n = outcomeLabel(o, home, away);
    return n.length > 4 ? n.slice(0, 4) : n;
  };
  const ends = OUTCOMES.map((o) => {
    const c = curves[o];
    const last = c?.[c.length - 1];
    if (!last) return null;
    const ay = Y(last.p);
    return { o, ay, y: ay, name: labelName(o), p: last.p };
  }).filter(Boolean) as { o: OutcomeSide; ay: number; y: number; name: string; p: number }[];
  ends.sort((a, b) => a.y - b.y);
  const LH = 13;
  for (let i = 1; i < ends.length; i++) {
    if (ends[i].y - ends[i - 1].y < LH) ends[i].y = ends[i - 1].y + LH;
  }
  // clamp block within plot area, preserving spacing
  const yMin = PAD.t + 4;
  const yMax = CH - PAD.b;
  const overflow = ends.length ? ends[ends.length - 1].y - yMax : 0;
  if (overflow > 0) for (const e of ends) e.y = Math.max(yMin, e.y - overflow);
  const labelX = CW - PAD.r + 8;
  const aiEnds = OUTCOMES.map((o) => {
    const c = aiCurves?.[o];
    const last = c?.[c.length - 1];
    if (!last) return null;
    const ay = Y(last.p);
    return { o, ay, y: ay };
  }).filter(Boolean) as { o: OutcomeSide; ay: number; y: number }[];
  aiEnds.sort((a, b) => a.y - b.y);
  const AI_LH = 10;
  for (let i = 1; i < aiEnds.length; i++) {
    if (aiEnds[i].y - aiEnds[i - 1].y < AI_LH) aiEnds[i].y = aiEnds[i - 1].y + AI_LH;
  }
  const aiOverflow = aiEnds.length ? aiEnds[aiEnds.length - 1].y - yMax : 0;
  if (aiOverflow > 0) for (const e of aiEnds) e.y = Math.max(yMin, e.y - aiOverflow);
  const aiLabelX = CW - PAD.r - 8;

  return (
    <svg viewBox={`0 0 ${CW} ${CH}`} className="w-full" role="img" aria-label="场内实时概率曲线">
      {yTicks.map((v) => (
        <g key={v}>
          <line x1={PAD.l} x2={CW - PAD.r} y1={Y(v)} y2={Y(v)} stroke="#27272a" strokeWidth="1" />
          <text x={PAD.l - 5} y={Y(v) + 3.5} textAnchor="end" fontSize="10" fill="#52525b">
            {Math.round(v * 100)}%
          </text>
        </g>
      ))}
      {xTicks.map((t) => (
        <text key={t} x={X(t)} y={CH - 5} textAnchor="middle" fontSize="10" fill="#52525b">
          {hhmm(t)}
        </text>
      ))}
      {showKo && (
        <g>
          <line x1={X(koS)} x2={X(koS)} y1={PAD.t} y2={CH - PAD.b} stroke="#71717a" strokeWidth="1" strokeDasharray="3 3" />
          <text x={X(koS) + 4} y={PAD.t + 9} fontSize="10" fill="#71717a">
            开球
          </text>
        </g>
      )}
      {OUTCOMES.map((o) => {
        const pts = downsample(curves[o] ?? [], 360);
        if (pts.length < 2) return null;
        return (
          <polyline
            key={o}
            points={pts.map((x) => `${X(x.t).toFixed(1)},${Y(x.p).toFixed(1)}`).join(" ")}
            fill="none"
            stroke={COLOR[o]}
            strokeWidth={spikeOutcome === o ? 2.5 : 1.6}
            strokeLinejoin="round"
          />
        );
      })}
      {OUTCOMES.map((o) => {
        const pts = downsample(aiCurves?.[o] ?? [], 360);
        if (pts.length < 2) return null;
        return (
          <polyline
            key={`ai-${o}`}
            points={pts.map((x) => `${X(x.t).toFixed(1)},${Y(x.p).toFixed(1)}`).join(" ")}
            fill="none"
            stroke={COLOR[o]}
            strokeWidth="1.2"
            strokeDasharray="4 3"
            strokeLinejoin="round"
            opacity="0.75"
          />
        );
      })}
      {/* end-of-line team / draw labels */}
      {ends.map((e) => (
        <g key={`lbl-${e.o}`}>
          <line
            x1={CW - PAD.r}
            y1={e.ay}
            x2={labelX - 4}
            y2={e.y}
            stroke={COLOR[e.o]}
            strokeWidth="1"
            strokeOpacity="0.5"
          />
          <circle cx={CW - PAD.r} cy={e.ay} r="2" fill={COLOR[e.o]} />
          <text x={labelX} y={e.y + 3.5} fontSize="11" fontWeight="600" fill={COLOR[e.o]}>
            {e.name}
          </text>
        </g>
      ))}
      {aiEnds.map((e) => (
        <g key={`ai-lbl-${e.o}`} opacity="0.85">
          <line
            x1={CW - PAD.r}
            y1={e.ay}
            x2={aiLabelX + 4}
            y2={e.y}
            stroke={COLOR[e.o]}
            strokeWidth="1"
            strokeDasharray="2 2"
            strokeOpacity="0.45"
          />
          <text x={aiLabelX} y={e.y + 3} textAnchor="end" fontSize="9" fontWeight="700" fill={COLOR[e.o]}>
            AI
          </text>
        </g>
      ))}
    </svg>
  );
}

/* ── 盘口深度梯 ──────────────────────────────────────────────────── */

const LADDER_N = 7;

function DepthLadder({ book }: { book: OutcomeBook }) {
  const bids = book.bids.slice(0, LADDER_N);
  const asks = book.asks.slice(0, LADDER_N);
  const maxUsd = Math.max(1, ...bids.map((l) => l.price * l.size), ...asks.map((l) => l.price * l.size));
  const row = (l: { price: number; size: number }, kind: "bid" | "ask") => {
    const notional = l.price * l.size;
    const w = Math.max(2, (notional / maxUsd) * 100);
    return (
      <div key={`${kind}${l.price}`} className="relative flex items-center justify-between px-1.5 py-[3px] text-[11px] tabular-nums">
        <div
          className={`absolute inset-y-0 ${kind === "bid" ? "right-0 bg-emerald-500/15" : "left-0 bg-rose-500/15"}`}
          style={{ width: `${w}%` }}
        />
        {kind === "bid" ? (
          <>
            <span className="relative text-zinc-500">{usd(notional)}</span>
            <span className="relative font-semibold text-emerald-400">{cents(l.price)}</span>
          </>
        ) : (
          <>
            <span className="relative font-semibold text-rose-400">{cents(l.price)}</span>
            <span className="relative text-zinc-500">{usd(notional)}</span>
          </>
        )}
      </div>
    );
  };
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[11px] text-zinc-500">
        <span>
          买盘 <b className="tabular-nums text-zinc-300">{usd(book.bidUsd)}</b>
        </span>
        <span className="tabular-nums">
          中间价 <b className="text-zinc-200">{book.mid != null ? cents(book.mid) : "—"}</b>
          {book.bestBid != null && book.bestAsk != null && (
            <span className="text-zinc-600">　价差 {cents(book.bestAsk - book.bestBid)}</span>
          )}
        </span>
        <span>
          卖盘 <b className="tabular-nums text-zinc-300">{usd(book.askUsd)}</b>
        </span>
      </div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-zinc-800/80 bg-zinc-800/40">
        <div className="bg-zinc-950/70">{bids.map((l) => row(l, "bid"))}</div>
        <div className="bg-zinc-950/70">{asks.map((l) => row(l, "ask"))}</div>
      </div>
    </div>
  );
}

/* ── 逐笔成交带 ──────────────────────────────────────────────────── */

const BIG_TRADE_USD = 2000;

function TradeTape({ trades, home, away }: { trades: TradeItem[]; home: string; away: string }) {
  if (!trades.length)
    return <div className="py-4 text-center text-xs text-zinc-600">暂无成交记录</div>;
  return (
    <div className="max-h-44 overflow-y-auto rounded-lg border border-zinc-800/80">
      {trades.map((t) => {
        const notional = t.price * t.size;
        const big = notional >= BIG_TRADE_USD;
        return (
          <div
            key={t.id}
            className={`flex items-center gap-2 border-b border-zinc-800/50 px-2 py-1 text-[11px] tabular-nums last:border-b-0 ${
              big ? "bg-amber-400/5" : ""
            }`}
          >
            <span className="w-14 shrink-0 text-zinc-600">{hhmmss(t.ts)}</span>
            <span className={`w-12 shrink-0 truncate font-medium ${TEXT_CLS[t.outcome]}`}>
              {outcomeLabel(t.outcome, home, away)}
            </span>
            <span className={`w-7 shrink-0 font-semibold ${t.side === "BUY" ? "text-emerald-400" : "text-rose-400"}`}>
              {t.side === "BUY" ? "买" : "卖"}
            </span>
            <span className="w-12 shrink-0 text-zinc-300">{cents(t.price)}</span>
            <span className={`ml-auto ${big ? "font-bold text-amber-300" : "text-zinc-500"}`}>{usd(notional)}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ── 面板主体 ───────────────────────────────────────────────────── */

export function MatchDetail({
  slug,
  kickoffUtc,
  home,
  away,
  pred,
  liveEntry,
}: {
  slug: string;
  kickoffUtc: string;
  home: string;
  away: string;
  pred?: Pred;
  liveEntry?: LiveEntry;
}) {
  const mm = useMatchMarket(slug, kickoffUtc);
  const aiCurves = useInplayCurve({ pred, liveEntry });
  const [tab, setTab] = useState<OutcomeSide | null>(null);

  // 默认选中当前市场热度最高（中间价最高）的结果
  const favorite = useMemo(() => {
    let best: OutcomeSide = "home";
    let bp = -1;
    for (const o of OUTCOMES) {
      const p = mm.books[o]?.mid ?? -1;
      if (p > bp) {
        bp = p;
        best = o;
      }
    }
    return best;
  }, [mm.books]);
  const active = tab ?? favorite;
  const activeBook = mm.books[active];

  // spike 高亮 45s 内有效（hook 侧已做 TTL，这里只透传）
  const spike = mm.spike;
  const [, forceTick] = useState(0);
  useEffect(() => {
    if (!spike) return;
    const id = setTimeout(() => forceTick((x) => x + 1), 46e3);
    return () => clearTimeout(id);
  }, [spike]);

  if (mm.status === "error")
    return (
      <div className="mt-3 rounded-xl border border-zinc-800/80 bg-zinc-950/60 p-3 text-center text-xs text-zinc-600">
        该场 Polymarket 盘口数据不可用
      </div>
    );

  return (
    <div className="mt-3 space-y-3 rounded-xl border border-zinc-800/80 bg-zinc-950/60 p-3">
      {/* 状态行 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500">
        <span className="inline-flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${mm.wsUp ? "live-dot bg-emerald-400" : "bg-zinc-600"}`} />
          {mm.wsUp ? "订单簿逐笔直连" : "连接中…"}
        </span>
        {mm.volume != null && (
          <span className="tabular-nums">
            成交量 <b className="text-zinc-300">{usd(mm.volume)}</b>
          </span>
        )}
        {mm.liveTradeCount > 0 && (
          <span className="tabular-nums">
            实收 <b className="text-zinc-300">{mm.liveTradeCount}</b> 笔
          </span>
        )}
        <span className="ml-auto text-zinc-600">进球等重大事件通常先于直播反映在盘口</span>
      </div>

      {/* 重大事件警报 */}
      {spike && (
        <div className="live-dot flex items-center gap-2 rounded-lg border border-amber-400/40 bg-amber-400/10 px-2.5 py-1.5 text-xs font-medium text-amber-300">
          ⚡ 市场剧烈波动：{outcomeLabel(spike.outcome, home, away)}{" "}
          <b className="tabular-nums">{pp(spike.delta)}</b>
          <span className="font-normal text-amber-300/70">/ {Math.round((Date.now() - spike.ts) / 1000) + 12}s 内</span>
        </div>
      )}

      {/* 场内概率曲线 */}
      <div>
        <ProbChart curves={mm.curves} aiCurves={aiCurves} kickoffUtc={kickoffUtc} spikeOutcome={spike?.outcome ?? null} home={home} away={away} />
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] tabular-nums">
          {OUTCOMES.map((o) => {
            const c = mm.curves[o];
            const last = c?.[c.length - 1];
            return (
              <span key={o} className="inline-flex items-center gap-1.5 text-zinc-500">
                <span className="inline-block h-1.5 w-3 rounded-full" style={{ background: COLOR[o] }} />
                {outcomeLabel(o, home, away)}{" "}
                <b className={TEXT_CLS[o]}>{last ? `${(last.p * 100).toFixed(1)}%` : "—"}</b>
              </span>
            );
          })}
        </div>
      </div>

      {/* 深度梯：结果切换 */}
      <div>
        <div className="mb-2 flex gap-1">
          {OUTCOMES.map((o) => (
            <button
              key={o}
              onClick={() => setTab(o)}
              className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                active === o ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {outcomeLabel(o, home, away)}
              {mm.books[o]?.mid != null && (
                <span className={`ml-1 tabular-nums ${active === o ? TEXT_CLS[o] : ""}`}>
                  {cents(mm.books[o]!.mid!, 0)}
                </span>
              )}
            </button>
          ))}
        </div>
        {activeBook ? (
          <DepthLadder book={activeBook} />
        ) : (
          <div className="py-4 text-center text-xs text-zinc-600">
            {mm.status === "loading" ? "订单簿加载中…" : "该结果暂无挂单"}
          </div>
        )}
      </div>

      {/* 逐笔成交 */}
      <TradeTape trades={mm.trades} home={home} away={away} />

      <p className="text-[10px] leading-4 text-zinc-700">
        数据直连 Polymarket CLOB（订单簿快照 + 逐笔推送），价格为 Yes 口径；No 侧成交已折算（价=1−p，方向翻转）。仅供研究娱乐。
      </p>
    </div>
  );
}
