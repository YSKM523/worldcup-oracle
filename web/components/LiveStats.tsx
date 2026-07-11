"use client";

import { useMatchStats } from "@/lib/useMatchStats";
import { zh } from "@/lib/wc";

/** Curated stat rows: ESPN boxscore stat name → Chinese label + formatting. */
const ROWS: { name: string; label: string; pct?: boolean; scale?: number }[] = [
  { name: "possessionPct", label: "控球", pct: true },
  { name: "totalShots", label: "射门" },
  { name: "shotsOnTarget", label: "射正" },
  { name: "wonCorners", label: "角球" },
  { name: "foulsCommitted", label: "犯规" },
  { name: "offsides", label: "越位" },
  { name: "yellowCards", label: "黄牌" },
  { name: "redCards", label: "红牌" },
  { name: "saves", label: "扑救" },
  { name: "passPct", label: "传球成功", pct: true, scale: 100 },
];

const fmt = (v: number, pct?: boolean, scale = 1) =>
  pct ? `${Math.round(v * scale)}%` : `${v}`;

export function LiveStats({
  espnId,
  home,
  away,
  live,
  compact = false,
  variant = "card",
}: {
  espnId: string;
  home: string;
  away: string;
  /** true when the schedule/live feed marks this match as in-play or done. */
  live: boolean;
  compact?: boolean;
  variant?: "card" | "console";
}) {
  const stats = useMatchStats(espnId, true);
  const started = !!stats && stats.state !== "pre";
  const state = started ? "started" : live ? "loading" : "pre";

  const inPlay = stats?.state === "in";
  const consoleMode = variant === "console";
  const surfaceClass = consoleMode
    ? "flex h-full min-h-full flex-col rounded-none border-0 bg-transparent p-0"
    : `border border-zinc-800/80 bg-zinc-950/60 ${compact ? "rounded-[3px] p-2" : "rounded-xl p-3"}`;

  if (compact && !started) {
    return (
      <div
        data-live-stats-mode={compact ? "compact" : "default"}
        data-live-stats-state={state}
        data-console-surface={consoleMode ? "stats" : undefined}
        className={surfaceClass}
      >
        <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1">
          <span className="lbl lbl-faint">04</span>
          <span className="lbl text-[var(--ink)]">LIVE STATS · 实时数据</span>
          <span className="lbl lbl-faint ml-auto">{live ? "加载中…" : "开赛后更新"}</span>
          <span className="mono basis-full text-[10px] text-[var(--ink-faint)] sm:ml-auto sm:basis-auto">
            控球 · 射门 · 角球 · 牌
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      data-live-stats-mode={compact ? "compact" : "default"}
      data-live-stats-state={state}
      data-console-surface={consoleMode ? "stats" : undefined}
      className={surfaceClass}
    >
      <div className={`${consoleMode ? "mb-3 min-h-8 border-b border-[var(--line)] pb-2" : "mb-2.5"} flex items-center gap-2`}>
        <span className="lbl lbl-faint">04</span>
        <span className="lbl" style={{ color: "var(--ink)" }}>
          LIVE STATS · 实时数据
        </span>
        {started ? (
          <span
            className="mono ml-auto inline-flex items-center gap-1.5 text-[11px]"
            style={{ color: inPlay ? "var(--down)" : "var(--ink-dim)" }}
          >
            {inPlay && (
              <span
                className="live-dot h-1.5 w-1.5 rounded-full"
                style={{ background: "var(--down)" }}
              />
            )}
            {inPlay ? stats!.detail || "进行中" : "完场 FT"}
          </span>
        ) : (
          <span className="lbl lbl-faint ml-auto">
            {live ? "加载中…" : "开赛后更新"}
          </span>
        )}
      </div>

      {started ? (
        <div className={compact ? "grid gap-x-4 gap-y-1.5 sm:grid-cols-2" : consoleMode ? "flex flex-1 flex-col justify-between gap-2" : "space-y-2"}>
          {ROWS.map((r) => {
            const h = stats!.home[r.name];
            const a = stats!.away[r.name];
            if (h == null && a == null) return null;
            const hv = h ?? 0;
            const av = a ?? 0;
            const total = hv + av;
            // possession-style pct bars split by their own values; counts split by share
            const hShare = total > 0 ? (hv / total) * 100 : 50;
            const hLead = hv > av;
            const aLead = av > hv;
            return (
              <div key={r.name}>
                <div className="mono flex items-center justify-between text-[12px] tabular-nums">
                  <span style={{ color: hLead ? "var(--up)" : "var(--ink-dim)", fontWeight: hLead ? 700 : 400 }}>
                    {fmt(hv, r.pct, r.scale)}
                  </span>
                  <span className="lbl lbl-faint">{r.label}</span>
                  <span style={{ color: aLead ? "var(--down)" : "var(--ink-dim)", fontWeight: aLead ? 700 : 400 }}>
                    {fmt(av, r.pct, r.scale)}
                  </span>
                </div>
                <div className="mt-1 flex h-1 overflow-hidden rounded-sm bg-[rgba(255,255,255,.05)]">
                  <div style={{ width: `${hShare}%`, background: "var(--up)" }} />
                  <div style={{ width: `${100 - hShare}%`, background: "var(--down)" }} />
                </div>
              </div>
            );
          })}
          <div
            className={`${compact ? "sm:col-span-2 " : ""}mono flex items-center justify-between pt-1 text-[10px]`}
            style={{ color: "var(--ink-faint)" }}
          >
            <span>{zh(home)}</span>
            <span>数据来源 ESPN</span>
            <span>{zh(away)}</span>
          </div>
        </div>
      ) : (
        <div className="mono py-3 text-center text-[12px]" style={{ color: "var(--ink-faint)" }}>
          {live ? "正在获取实时比赛数据…" : "比赛未开始 — 实时数据（控球 / 射门 / 角球 / 牌）将在开赛后显示"}
        </div>
      )}
    </div>
  );
}
