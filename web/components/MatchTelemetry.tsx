"use client";

import { useEffect, useState } from "react";
import type { KalshiMarketState, Match, PolyLive, WeatherData } from "../lib/types";
import { kickoffEpoch, STAGE_ZH } from "../lib/wc";

type MatchTelemetryProps = {
  match: Match;
  weather: WeatherData | null;
  poly: PolyLive;
  kalshi: KalshiMarketState;
};

const pad = (n: number) => String(n).padStart(2, "0");

function countdown(kickoff: number, now: number) {
  const seconds = Math.max(0, Math.floor((kickoff - now) / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return days ? `${days}D ${pad(hours)}:${pad(minutes)}:${pad(rest)}` : `${pad(hours)}:${pad(minutes)}:${pad(rest)}`;
}

const stamp = (value: number | null | undefined) =>
  value ? new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "—";

export function MatchTelemetry({ match, weather, poly, kalshi }: MatchTelemetryProps) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const kickoff = new Date(match.kickoff_utc).getTime();
  const kickoffReached = kickoff <= now;
  const wx = weather?.matches[match.espn_id];
  const polyMatch = poly.matches[kickoffEpoch(match.kickoff_utc)];
  const polyUpdated = polyMatch?.ts ?? poly.updatedAt;
  const polyFresh = !!polyMatch && !!polyUpdated && now - polyUpdated <= 15_000;
  const polyLabel = poly.wsConnected && polyFresh ? "POLY LIVE" : polyMatch ? "POLY STALE" : "POLY UNAVAILABLE";
  const kalshiLabel = kalshi.status !== "live" ? "KAL UNAVAILABLE" : kalshi.stale ? "KAL STALE" : "KAL LIVE";
  const stage = match.stage === "group" && match.group ? `${match.group}组 · 小组赛` : STAGE_ZH[match.stage] ?? match.stage;

  return (
    <div data-match-telemetry className="mono min-h-full text-[11px] text-[var(--ink-dim)]">
      <div className="flex items-center gap-2 border-b border-[var(--line)] pb-2">
        <span className="lbl lbl-faint">04</span>
        <span className="lbl text-[var(--ink)]">LIVE STATS · 赛前遥测</span>
      </div>

      <div className="border-b border-[var(--line)] py-3">
        <div className="lbl lbl-faint">KICKOFF COUNTDOWN</div>
        <div className="mt-1 text-[22px] font-bold tabular-nums tracking-tight text-[var(--ink)]">
          {kickoffReached ? "KICKOFF REACHED" : <>T−{countdown(kickoff, now)}</>}
        </div>
        {kickoffReached && <div className="mt-1 text-[var(--mkt)]">等待实时源</div>}
        <div className="mt-1 text-[var(--ink-faint)]">
          {new Date(kickoff).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" })} UTC
        </div>
      </div>

      <dl className="grid grid-cols-[76px_minmax(0,1fr)] gap-x-2 gap-y-2 border-b border-[var(--line)] py-3">
        <dt className="lbl lbl-faint">STAGE</dt><dd className="text-[var(--ink)]">{stage}</dd>
        <dt className="lbl lbl-faint">VENUE</dt><dd className="text-[var(--ink)]">{[match.venue, match.city].filter(Boolean).join(" · ") || "待定"}</dd>
        <dt className="lbl lbl-faint">WEATHER</dt>
        <dd className="text-[var(--ink)]">{wx ? `${wx.temp_c}°C · 湿度 ${wx.humidity_pct}%` : "等待气象数据"}</dd>
        <dt className="lbl lbl-faint">ESPN</dt><dd className="text-[var(--ink-faint)]">{kickoffReached ? "等待比赛状态" : "等待开赛"}</dd>
      </dl>

      <div className="space-y-2 border-b border-[var(--line)] py-3">
        <div className="flex items-center justify-between gap-2">
          <span>POLYMARKET</span>
          <span className={polyLabel === "POLY LIVE" ? "text-[var(--up)]" : polyLabel.includes("STALE") ? "text-[var(--mkt)]" : "text-[var(--ink-faint)]"}>{polyLabel}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span>LAST SNAPSHOT</span><span className="tabular-nums text-[var(--ink-faint)]">{stamp(polyUpdated)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span>KALSHI</span>
          <span className={kalshiLabel === "KAL LIVE" ? "text-[var(--up)]" : kalshiLabel === "KAL STALE" ? "text-[var(--mkt)]" : "text-[var(--ink-faint)]"}>{kalshiLabel}</span>
        </div>
      </div>

      <div className="py-3">
        <div className="lbl lbl-faint">MATCH FEED PREVIEW</div>
        <div className="mt-2 leading-5 text-[var(--ink-faint)]">控球 · 射门 · 射正 · 角球 · 牌</div>
        <div className="mt-1 text-[var(--ink-faint)]">开赛后自动切换 ESPN 实时数据</div>
      </div>
    </div>
  );
}
