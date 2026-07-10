"use client";

import { useEffect, useState } from "react";
import { buildMarketConsensus, MARKET_SIDES, type SourceLine } from "../lib/marketConsensus";
import type { KalshiMarketState, MarketSide } from "../lib/types";
import type { MatchMarketState } from "../lib/useMatchMarket";
import { zh } from "../lib/wc";

const SIDE_COLOR: Record<MarketSide, string> = { home: "#34d399", draw: "#a1a1aa", away: "#f43f5e" };
const SIDE_SHORT: Record<MarketSide, string> = { home: "H", draw: "D", away: "A" };
const SEVERITY_CLASS = { normal: "text-zinc-500", warning: "text-amber-300", critical: "text-rose-300" } as const;
const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
const quote = (value: number | null | undefined) => value == null ? "—" : `${(value * 100).toFixed(0)}¢`;
const volume = (value: number | null | undefined) => {
  if (value == null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
};

function validLine(values: Record<MarketSide, number | null | undefined>, updatedAt: number | null): SourceLine | null {
  if (updatedAt == null || !Number.isFinite(updatedAt)) return null;
  if (MARKET_SIDES.some((side) => !Number.isFinite(values[side]) || values[side]! <= 0 || values[side]! >= 1)) return null;
  return { home: values.home!, draw: values.draw!, away: values.away!, updatedAt };
}

function polymarketLine(market: MatchMarketState): SourceLine | null {
  return validLine({
    home: market.books.home?.mid,
    draw: market.books.draw?.mid,
    away: market.books.away?.mid,
  }, market.updatedAt);
}

function kalshiLine(market: KalshiMarketState): SourceLine | null {
  if (market.status !== "live") return null;
  return validLine({
    home: market.outcomes.home?.mid,
    draw: market.outcomes.draw?.mid,
    away: market.outcomes.away?.mid,
  }, market.updatedAt);
}

function sideLabel(side: MarketSide, home: string, away: string) {
  return side === "home" ? zh(home) : side === "draw" ? "平局" : zh(away);
}

export function MarketConsensusPanel({ home, away, polymarket, kalshi }: {
  home: string;
  away: string;
  polymarket: MatchMarketState;
  kalshi: KalshiMarketState;
}) {
  const poly = polymarketLine(polymarket);
  const kal = kalshiLine(kalshi);
  const [, refreshAtExpiry] = useState(0);

  useEffect(() => {
    const expiries = [...new Set([poly?.updatedAt, kal?.updatedAt]
      .filter((updatedAt): updatedAt is number => updatedAt != null)
      .map((updatedAt) => updatedAt + 15_001)
      .filter((expiry) => expiry > Date.now()))]
      .sort((a, b) => a - b);
    let timer: ReturnType<typeof setTimeout> | undefined;
    let next = 0;
    const schedule = () => {
      const expiry = expiries[next++];
      if (expiry == null) return;
      timer = setTimeout(() => {
        refreshAtExpiry((version) => version + 1);
        schedule();
      }, Math.max(0, expiry - Date.now()));
    };
    schedule();
    return () => clearTimeout(timer);
  }, [poly?.updatedAt, kal?.updatedAt]);

  const result = buildMarketConsensus(poly, kal);
  const polyFresh = result.sourceNames.includes("polymarket");
  const kalFresh = result.sourceNames.includes("kalshi");
  const polyMode = polymarket.wsUp ? "WS" : "REST";
  const status = result.status === "dual"
    ? `PM ${polyMode} · KAL REST 1S · 2/2 LIVE`
    : result.status === "single" ? "1/2 SINGLE SOURCE" : "MARKETS UNAVAILABLE";
  const kalStale = kal != null && !kalFresh;
  const kalStatus = kalFresh ? "KAL LIVE" : kalStale ? "KAL STALE" : "KAL UNAVAILABLE";
  const hasCritical = MARKET_SIDES.some((side) => result.severity[side] === "critical");
  const hasWarning = MARKET_SIDES.some((side) => result.severity[side] === "warning");

  return (
    <>
      <section data-market-consensus-state={result.status} aria-label="聚合市场共识" className="border border-zinc-800 bg-zinc-950/55">
        <header className="flex min-h-8 items-center gap-2 border-b border-zinc-800 px-3 py-1.5">
          <span className="text-[10px] font-semibold tracking-[0.16em] text-zinc-300">MARKET CONSENSUS</span>
          <span className="h-3 w-px bg-zinc-800" />
          <span className="text-[10px] tabular-nums text-zinc-500">REGULATION 1X2</span>
          <span className={`ml-auto text-[10px] font-semibold tracking-[0.08em] ${result.status === "dual" ? "text-emerald-300" : result.status === "single" ? "text-amber-300" : "text-zinc-500"}`}>
            {status}
          </span>
        </header>

        <div className="px-3 py-2">
          <div className="mb-2 flex h-2 overflow-hidden bg-zinc-900" aria-label="共识概率分布">
            {MARKET_SIDES.map((side) => (
              <span key={side} className="h-full" style={{ width: `${result.consensus[side] * 100}%`, backgroundColor: SIDE_COLOR[side] }} />
            ))}
          </div>
          <div className="grid grid-cols-[minmax(76px,1.2fr)_72px_64px_64px_64px] items-center border-b border-zinc-800/80 pb-1 text-right text-[9px] uppercase tracking-[0.08em] text-zinc-600">
            <span className="text-left">Outcome</span><span>{result.status === "dual" ? "Consensus" : "Line"}</span><span>PM</span><span>Kalshi</span><span>Δ pp</span>
          </div>
          {MARKET_SIDES.map((side) => (
            <div key={side} data-market-side={side} data-market-consensus-probability={result.consensus[side].toFixed(6)} data-market-severity={result.severity[side]} className="grid min-h-7 grid-cols-[minmax(76px,1.2fr)_72px_64px_64px_64px] items-center border-b border-zinc-900 text-right text-[11px] tabular-nums last:border-b-0">
              <span className="flex min-w-0 items-center gap-2 text-left font-medium text-zinc-300"><span className="h-1.5 w-1.5 shrink-0" style={{ backgroundColor: SIDE_COLOR[side] }} /><span className="truncate">{sideLabel(side, home, away)}</span></span>
              <strong className="font-semibold text-zinc-100">{result.sources ? pct(result.consensus[side]) : "—"}</strong>
              <span className={polyFresh ? "text-zinc-300" : "text-zinc-700"}>{result.normalized.polymarket ? pct(result.normalized.polymarket[side]) : "—"}</span>
              <span className={kalFresh ? "text-zinc-300" : "text-zinc-700"}>{result.normalized.kalshi ? pct(result.normalized.kalshi[side]) : "—"}</span>
              <span className={`font-medium ${SEVERITY_CLASS[result.severity[side]]}`}>{result.status === "dual" ? `${(result.divergence[side] * 100).toFixed(1)}pp` : "—"}</span>
            </div>
          ))}
        </div>

        <div className="grid border-t border-zinc-800 text-[10px] tabular-nums text-zinc-500 lg:grid-cols-2">
          <div data-market-source="polymarket" className="flex min-h-8 items-center gap-2 px-3 py-1.5">
            <span className={`h-1.5 w-1.5 ${polyFresh ? "bg-emerald-400" : "bg-zinc-700"}`} /><b className="font-semibold text-zinc-300">PM</b><span>{polyFresh ? `${polyMode} LIVE` : "UNAVAILABLE"}</span><span className="ml-auto">3-WAY MID</span>
          </div>
          <div data-market-source="kalshi" className="border-t border-zinc-800 px-3 py-1.5 lg:border-l lg:border-t-0">
            <div className="mb-1 flex items-center gap-2"><span className={`h-1.5 w-1.5 ${kalFresh ? "bg-emerald-400" : kalStale ? "bg-amber-400" : "bg-zinc-700"}`} /><b className="font-semibold text-zinc-300">KAL</b><span className={kalStatus === "KAL STALE" ? "font-semibold text-amber-300" : ""}>{kalStatus}</span><span className="ml-auto text-zinc-600">BID / ASK / LAST / VOL</span></div>
            <div className="grid grid-cols-3 gap-2">
              {MARKET_SIDES.map((side) => { const outcome = kalshi.outcomes[side]; return <span key={side} className="whitespace-nowrap text-zinc-500"><b className="mr-1 text-zinc-400">{SIDE_SHORT[side]}</b>{quote(outcome?.bid)}/{quote(outcome?.ask)}/{quote(outcome?.last)} · {volume(outcome?.volume)}</span>; })}
            </div>
          </div>
        </div>

        {(hasCritical || hasWarning) && (
          <div data-market-divergence-alert={hasCritical ? "critical" : "warning"} role="status" className={`border-t px-3 py-1.5 text-[10px] font-semibold ${hasCritical ? "border-rose-400/30 bg-rose-400/10 text-rose-300" : "border-amber-400/30 bg-amber-400/10 text-amber-300"}`}>
            VENUE DIVERGENCE · {MARKET_SIDES.filter((side) => result.severity[side] !== "normal").map((side) => sideLabel(side, home, away)).join(" / ")}
          </div>
        )}
      </section>
      <div className="flex items-center gap-2 py-1" aria-label="Polymarket 微观结构分区"><span className="h-px flex-1 bg-zinc-800" /><span className="text-[9px] font-semibold tracking-[0.16em] text-zinc-600">POLY MICROSTRUCTURE</span><span className="h-px flex-1 bg-zinc-800" /></div>
    </>
  );
}
