"use client";

import { useState, type KeyboardEvent } from "react";
import { buildMatchScripts, buildScoreDistribution, buildValueRows, type ValueRow } from "../lib/forecastAnalytics";
import type { KalshiMarketState, LiveEntry, MarketSide, Match, MatchWeather, PolyLive } from "../lib/types";
import { kickoffEpoch, zh } from "../lib/wc";

type ForecastTab = "value" | "scripts" | "scores" | "watch";

/** Console-only inputs supplied by FocusCard during Task 3 integration. */
export interface ForecastAnalyticsTabsProps {
  match: Match;
  poly: PolyLive;
  weather?: MatchWeather | null;
  kalshi?: KalshiMarketState;
  liveEntry?: LiveEntry;
}

const TABS: Array<{ id: ForecastTab; label: string }> = [
  { id: "value", label: "VALUE · 盘口价值" },
  { id: "scripts", label: "SCRIPTS · 比赛剧本" },
  { id: "scores", label: "SCORES · 比分分布" },
  { id: "watch", label: "WATCH · 盯盘清单" },
];

const SIDE_CLASS: Record<MarketSide, string> = { home: "text-emerald-300", draw: "text-zinc-300", away: "text-rose-300" };
const SIDE_DOT: Record<MarketSide, string> = { home: "bg-emerald-400", draw: "bg-zinc-400", away: "bg-rose-400" };

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
const odds = (value: number | null) => value == null ? "—" : value.toFixed(2);
const number = (value: number | null) => value == null ? "—" : pct(value);

function sideLabel(side: MarketSide, match: Match) {
  return side === "home" ? zh(match.home) : side === "draw" ? "平局" : zh(match.away);
}

function validAi(match: Match): Record<MarketSide, number> | null {
  const pred = match.pred;
  if (!pred) return null;
  const values = { home: pred.p_home, draw: pred.p_draw, away: pred.p_away };
  return Object.values(values).every((value) => Number.isFinite(value) && value > 0) ? values : null;
}

function marketPrices(match: Match, poly: PolyLive): Record<MarketSide, number> | null {
  const live = poly.matches[kickoffEpoch(match.kickoff_utc)];
  const values = live ?? match.market;
  return values ? { home: values.home, draw: values.draw, away: values.away } : null;
}

function MarketUnavailable() {
  return <div className="border border-dashed border-zinc-800 px-3 py-4 text-center text-[11px] font-semibold tracking-[0.1em] text-zinc-500">MARKET UNAVAILABLE</div>;
}

function ValuePanel({ match, ai, rows }: { match: Match; ai: Record<MarketSide, number> | null; rows: ValueRow[] }) {
  if (!ai) return <div className="py-6 text-center text-[11px] font-semibold tracking-[0.1em] text-zinc-500">FORECAST UNAVAILABLE</div>;
  const marketAvailable = rows.some((row) => row.market != null);
  return (
    <div className="space-y-2 px-3">
      <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.14em] text-zinc-400"><span>AI FAIR</span><span className="h-px flex-1 bg-zinc-800" /><span className="text-zinc-600">PM DEVIG · HALF KELLY</span></div>
      {!marketAvailable && <MarketUnavailable />}
      <div className="grid grid-cols-[minmax(80px,1fr)_54px_54px_54px_54px_54px] border-b border-zinc-800 pb-1 text-right text-[9px] uppercase tracking-[0.08em] text-zinc-600">
        <span className="text-left">Outcome</span><span>AI</span><span>PM</span><span>Fair</span><span>Edge</span><span>½ Kelly</span>
      </div>
      {rows.map((row) => (
        <div key={row.side} data-forecast-value={row.side} className="grid min-h-8 grid-cols-[minmax(80px,1fr)_54px_54px_54px_54px_54px] items-center border-b border-zinc-900 text-right text-[11px] tabular-nums last:border-b-0">
          <span className={`flex min-w-0 items-center gap-2 text-left font-medium ${SIDE_CLASS[row.side]}`}><span className={`h-1.5 w-1.5 shrink-0 ${SIDE_DOT[row.side]}`} /><span className="truncate">{sideLabel(row.side, match)}</span></span>
          <strong className="text-zinc-100">{pct(row.ai)}</strong><span className="text-zinc-300">{number(row.market)}</span><span className="text-zinc-300">{odds(row.fairOdds)}</span>
          <span className={row.edge == null ? "text-zinc-600" : row.edge > 0 ? "text-emerald-300" : row.edge < 0 ? "text-rose-300" : "text-zinc-400"}>{row.edge == null ? "—" : `${row.edge > 0 ? "+" : ""}${(row.edge * 100).toFixed(1)}pp`}</span>
          <span className="text-zinc-400">{row.halfKelly == null ? "—" : pct(row.halfKelly)}</span>
        </div>
      ))}
    </div>
  );
}

function ScriptsPanel({ match, distribution }: { match: Match; distribution: ReturnType<typeof buildScoreDistribution> }) {
  if (!distribution) return <div className="py-6 text-center text-[11px] font-semibold tracking-[0.1em] text-zinc-500">SCORE MODEL UNAVAILABLE</div>;
  return (
    <div className="space-y-2 px-3">
      <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.14em] text-zinc-400"><span>比赛剧本</span><span className="h-px flex-1 bg-zinc-800" /><span className="text-zinc-600">RESULT PATHS</span></div>
      {buildMatchScripts(distribution).map((script) => (
        <div key={script.side} data-forecast-script={script.side} className="grid grid-cols-[minmax(92px,1fr)_58px_minmax(100px,1.2fr)] items-center gap-3 border-b border-zinc-900 py-2 text-[11px] tabular-nums last:border-b-0">
          <span className={`flex items-center gap-2 font-medium ${SIDE_CLASS[script.side]}`}><span className={`h-1.5 w-1.5 ${SIDE_DOT[script.side]}`} />{sideLabel(script.side, match)}路径</span>
          <strong className="text-right text-zinc-100">{pct(script.p)}</strong>
          <span className="text-right text-zinc-400">{script.leadingScores.length ? script.leadingScores.map((score) => `${score.label} ${pct(score.p)}`).join(" · ") : "4+ tail"}</span>
        </div>
      ))}
    </div>
  );
}

function ScoresPanel({ match, distribution }: { match: Match; distribution: ReturnType<typeof buildScoreDistribution> }) {
  const ranking = match.pred?.scoreline.top_scores ?? [];
  if (!distribution) return <div className="py-6 text-center text-[11px] font-semibold tracking-[0.1em] text-zinc-500">SCORE MODEL UNAVAILABLE</div>;
  return (
    <div className="space-y-3 px-3">
      <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.14em] text-zinc-400"><span>比分分布</span><span className="h-px flex-1 bg-zinc-800" /><span className="text-zinc-600">0–3 + 4+</span></div>
      <div data-forecast-score-grid className="grid grid-cols-4 gap-px overflow-hidden border border-zinc-800 bg-zinc-800">
        {distribution.cells.map((cell) => {
          const isMode = cell.label === distribution.mode.label;
          return <div key={cell.label} data-forecast-score={cell.label} data-most-likely={isMode || undefined} className={`min-h-11 bg-zinc-950 px-2 py-1.5 text-right tabular-nums ${isMode ? "bg-amber-400/10 text-amber-200" : "text-zinc-300"}`}><b className="float-left text-[10px] font-medium text-zinc-500">{cell.label}</b><span className="text-[11px]">{pct(cell.p)}</span></div>;
        })}
      </div>
      <div data-forecast-score-tail className="flex items-center border-y border-zinc-800 py-2 text-[11px] tabular-nums"><span className="font-semibold text-zinc-300">4+ TAIL</span><span className="ml-auto text-zinc-100">{pct(distribution.tail)}</span></div>
      <div className="text-[10px] text-zinc-500"><span className="font-semibold tracking-[0.12em] text-zinc-400">TOP SCORES</span><span className="ml-3 tabular-nums">{ranking.length ? ranking.map((score) => `${score.score} ${pct(score.p)}`).join(" · ") : "—"}</span></div>
    </div>
  );
}

function WatchPanel({ match, poly, kalshi, weather, liveEntry, rows }: ForecastAnalyticsTabsProps & { rows: ValueRow[] }) {
  const quote = poly.matches[kickoffEpoch(match.kickoff_utc)];
  const quoteUpdatedAt = quote?.ts ?? poly.updatedAt;
  const pmFresh = quoteUpdatedAt != null && Date.now() - quoteUpdatedAt <= 120_000;
  const pmStatus = !quote ? "PM UNAVAILABLE" : poly.wsConnected && pmFresh ? "PM WS · FRESH" : pmFresh ? "PM SNAPSHOT · FRESH" : "PM STALE";
  const kalStatus = kalshi?.status === "live" ? kalshi.stale ? "KAL STALE" : "KAL LIVE" : "KAL UNAVAILABLE";
  const divergence = rows.reduce<number | null>((max, row) => row.edge == null ? max : Math.max(max ?? 0, Math.abs(row.edge)), null);
  const weatherStatus = !weather ? "WEATHER UNAVAILABLE" : `WEATHER ${Math.round(weather.temp_c)}°C · ${Math.round(weather.humidity_pct)}%${weather.forecast ? " · FORECAST" : ""}`;
  const feedStatus = !liveEntry ? "MATCH FEED · UNAVAILABLE" : liveEntry.state === "in" ? `MATCH FEED · LIVE ${liveEntry.clock}` : liveEntry.state === "post" ? "MATCH FEED · FINAL" : "MATCH FEED · PRE-MATCH";
  const lines = [pmStatus, kalStatus, divergence == null ? "AI / PM · UNAVAILABLE" : `AI / PM MAX Δ ${(divergence * 100).toFixed(1)}pp`, weatherStatus, feedStatus];
  return (
    <div className="space-y-2 px-3">
      <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.14em] text-zinc-400"><span>盯盘清单</span><span className="h-px flex-1 bg-zinc-800" /><span className="text-zinc-600">SOURCE HEALTH</span></div>
      <ul className="divide-y divide-zinc-900 border-y border-zinc-800">{lines.map((line) => <li key={line} className="flex min-h-8 items-center text-[11px] font-medium tabular-nums text-zinc-300"><span className="mr-2 h-1.5 w-1.5 bg-zinc-600" />{line}</li>)}</ul>
    </div>
  );
}

export function ForecastAnalyticsTabs(props: ForecastAnalyticsTabsProps) {
  const [tab, setTab] = useState<ForecastTab>("scores");
  const ai = validAi(props.match);
  const distribution = buildScoreDistribution(props.match.pred?.scoreline.xg_home ?? Number.NaN, props.match.pred?.scoreline.xg_away ?? Number.NaN);
  const rows = ai ? buildValueRows(ai, marketPrices(props.match, props.poly)) : [];
  const selectByKey = (event: KeyboardEvent<HTMLButtonElement>, current: ForecastTab) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next = Math.min(TABS.length - 1, Math.max(0, TABS.findIndex((item) => item.id === current) + (event.key === "ArrowRight" ? 1 : -1)));
    setTab(TABS[next].id);
  };

  return (
    <section data-forecast-tabs className="mt-4 flex min-h-0 flex-1 flex-col border-y border-zinc-800/70">
      <div role="tablist" aria-label="预测分析" className="overflow-x-auto border-b border-zinc-800"><div className="flex min-w-max">
        {TABS.map((item) => <button key={item.id} id={`forecast-tab-${item.id}`} data-forecast-tab={item.id} role="tab" type="button" aria-selected={tab === item.id} aria-controls={`forecast-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} onClick={() => setTab(item.id)} onKeyDown={(event) => selectByKey(event, item.id)} className={`border-b-2 px-3 py-2 text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap ${tab === item.id ? "border-emerald-400 text-zinc-100" : "border-transparent text-zinc-600 hover:text-zinc-300"}`}>{item.label}</button>)}
      </div></div>
      <div id={`forecast-panel-${tab}`} role="tabpanel" aria-labelledby={`forecast-tab-${tab}`} className="min-h-0 flex-1 overflow-y-auto py-3">
        {tab === "value" && <ValuePanel match={props.match} ai={ai} rows={rows} />}
        {tab === "scripts" && <ScriptsPanel match={props.match} distribution={distribution} />}
        {tab === "scores" && <ScoresPanel match={props.match} distribution={distribution} />}
        {tab === "watch" && <WatchPanel {...props} rows={rows} />}
      </div>
    </section>
  );
}
