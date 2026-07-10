"use client";

import { useEffect, useState } from "react";
import { CheckIcon, Flag, LogoMark, StarIcon, XIcon } from "@/components/icons";
import { FocusCard } from "@/components/MatchCards";
import { LiveStats } from "@/components/LiveStats";
import { MatchDetail } from "@/components/MatchDetail";
import { MatchTelemetry } from "@/components/MatchTelemetry";
import { KnockoutMap } from "@/components/KnockoutMap";
import { ChampionsView, GroupsView, RecordView } from "@/components/Views";
import { WeatherLabView } from "@/components/WeatherLab";
import { useKalshiMarket } from "@/lib/useKalshiMarket";
import { shouldEnableKalshiMarket } from "@/lib/kalshiMarketEligibility";
import type {
  Champion,
  Data,
  LiveMap,
  Match,
  Meta,
  PolyLive,
  WeatherData,
} from "@/lib/types";
import {
  KO_STAGES,
  STAGE_ZH,
  fmtTime,
  kickoffEpoch,
  liveEdge,
  oddsFmt,
  pct,
  venueDayKey,
  zh,
} from "@/lib/wc";

/* ── tiny utilities ─────────────────────────────────────────── */

const engCode = (name: string) => name.toUpperCase();

/** Ticking clock for the header live readout. */
function useClock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

const utcClock = (d: Date | null) =>
  d
    ? `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}:${String(d.getUTCSeconds()).padStart(2, "0")}`
    : "--:--:--";

const syncStamp = (iso: string) => {
  const d = new Date(iso);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};

const dayLabel = (key: string) => {
  const [y, mo, da] = key.split("-").map(Number);
  const wd = "日一二三四五六"[new Date(y, mo - 1, da).getDay()];
  return `${String(mo).padStart(2, "0")}-${String(da).padStart(2, "0")} · 周${wd}`;
};

/* ── shared bits ────────────────────────────────────────────── */

function Panel({
  idx,
  title,
  aside,
  children,
  className = "",
}: {
  idx: string;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel reveal ${className}`}>
      <div className="panel-head">
        <span className="lbl lbl-faint">{idx}</span>
        <span className="lbl" style={{ color: "var(--ink)" }}>
          {title}
        </span>
        <div className="ml-auto flex items-center gap-3">{aside}</div>
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

const Div = () => <span className="h-3 w-px bg-[var(--line-strong)]" />;

function EdgeFlag({
  dir,
  strong,
  txt,
}: {
  dir: "BUY" | "SELL";
  strong?: boolean;
  txt: string;
}) {
  const buy = dir === "BUY";
  return (
    <span
      className="mono inline-flex shrink-0 items-center gap-0.5 rounded-[3px] border px-1 text-[10px] font-bold leading-[14px]"
      style={{
        color: buy ? "var(--up)" : "var(--down)",
        borderColor: buy ? "rgba(52,211,153,.32)" : "rgba(251,113,133,.32)",
        background: buy ? "var(--up-soft)" : "var(--down-soft)",
      }}
    >
      {strong && <StarIcon className="h-2.5 w-2.5" />}
      {txt}
    </span>
  );
}

/* ═══════════════════════ TOP BAR ═══════════════════════════ */

function TopBar({ data, poly }: { data: Data; poly: PolyLive }) {
  const now = useClock();
  const m = data.meta;
  const prog = m.n_matches ? m.n_completed / m.n_matches : 0;
  const ws = poly.wsConnected;
  return (
    <header className="panel reveal flex-none">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-3 py-2">
        <div className="flex items-center gap-2.5">
          <span style={{ color: "var(--up)" }}>
            <LogoMark className="h-5 w-5" />
          </span>
          <div className="leading-none">
            <div
              className="text-[15px] font-bold tracking-[0.16em]"
              style={{ fontFamily: "var(--mono)" }}
            >
              WORLDCUP<span style={{ color: "var(--up)" }}>·</span>ORACLE
            </div>
            <div className="lbl mt-1" style={{ fontSize: 10 }}>
              FIFA 2026 // AI × POLYMARKET
            </div>
          </div>
        </div>

        <div className="hidden items-center gap-2.5 md:flex">
          <span className="lbl lbl-faint">SIM</span>
          <span className="mono text-[12px] font-semibold">
            {m.n_completed}
            <span style={{ color: "var(--ink-faint)" }}>/{m.n_matches}</span>
          </span>
          <div className="h-1 w-16 rounded-sm bg-[rgba(255,255,255,.08)]">
            <div
              className="h-full rounded-sm"
              style={{ width: `${prog * 100}%`, background: "var(--up)" }}
            />
          </div>
        </div>

        <div className="ml-auto flex items-center gap-x-4 gap-y-1">
          <span className="hidden items-center gap-2 lg:flex">
            <span className="lbl lbl-faint">MODELS</span>
            <span className="mono text-[12px]">{m.models.length}</span>
            <Div />
            <span className="lbl lbl-faint">MC</span>
            <span className="mono text-[12px]">50K</span>
          </span>
          {m.volume ? (
            <>
              <Div />
              <span className="hidden items-center gap-2 sm:flex">
                <span className="lbl lbl-faint">MKT</span>
                <span className="mono text-[12px] font-semibold" style={{ color: "var(--mkt)" }}>
                  ${(m.volume / 1e9).toFixed(2)}B
                </span>
              </span>
            </>
          ) : null}
          <Div />
          <span className="flex items-center gap-2">
            <span className="lbl lbl-faint">SYNC</span>
            <span className="mono text-[12px]">{syncStamp(m.generated_at)}</span>
          </span>
          <Div />
          <span className="flex items-center gap-2">
            <span
              className={`h-1.5 w-1.5 rounded-full ${ws ? "live-dot" : ""}`}
              style={{ background: ws ? "var(--up)" : "var(--ink-ghost)" }}
            />
            <span className="mono text-[12px] tabular-nums" style={{ minWidth: 66 }}>
              {utcClock(now)}
              <span style={{ color: "var(--ink-faint)" }}>Z</span>
            </span>
          </span>
        </div>
      </div>
    </header>
  );
}

/* ═══════════════════ PERFORMANCE (left) ════════════════════ */

function PerformancePanel({
  data,
  onOpen,
  className,
}: {
  data: Data;
  onOpen: () => void;
  className?: string;
}) {
  const p = data.performance;
  const me = data.meta.match_edge;
  const cal = data.meta.calibration;

  const winPct = p.winner_hit_rate != null ? `${(p.winner_hit_rate * 100).toFixed(0)}%` : "—";
  const brier = p.mean_brier != null ? p.mean_brier.toFixed(3).replace(/^0/, "") : "—";
  const brierBar = p.mean_brier != null ? Math.min(1, p.mean_brier / 0.667) : 0;

  // per-stage winner hit-rate, computed from the real scored ledger
  const STAGE_ORDER = ["group", "r32", "r16", "qf", "sf", "third", "final"];
  const stageAcc = (() => {
    const acc: Record<string, { hit: number; n: number }> = {};
    for (const d of p.details) {
      const s = (acc[d.stage] ??= { hit: 0, n: 0 });
      s.n += 1;
      if (d.winner_hit) s.hit += 1;
    }
    return STAGE_ORDER.filter((s) => acc[s]?.n).map((s) => ({
      stage: s,
      hit: acc[s].hit,
      n: acc[s].n,
      rate: acc[s].hit / acc[s].n,
    }));
  })();

  return (
    <Panel
      idx="01"
      title="AI PERFORMANCE"
      className={className}
      aside={<span className="lbl lbl-faint">{p.n_scored} SCORED</span>}
    >
      <div className="flex h-full flex-col gap-3 p-3">
        {/* compact primary metrics — one analytical group, not nested cards */}
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(104px,.72fr)] border-b border-[var(--line)] pb-3">
          <div className="pr-3">
            <div className="flex items-end justify-between gap-2">
              <span
                className="mono text-3xl font-bold leading-none"
                style={{ color: "var(--up)" }}
              >
                {winPct}
              </span>
              <span className="lbl text-right leading-[1.25]">
                胜平负
                <br />
                判对率
              </span>
            </div>
            <div className="lbl lbl-faint mt-2">WINNER HIT · {p.details.length} MATCHES</div>
          </div>
          <div className="border-l border-[var(--line)] pl-3">
            <div className="flex items-baseline justify-between gap-2">
              <span className="lbl">BRIER</span>
              <span className="mono text-[15px] font-semibold">{brier}</span>
            </div>
            <div className="bar-track mt-2">
              <div
                className="bar-fill"
                style={{ width: `${brierBar * 100}%`, background: "var(--up)" }}
              />
            </div>
            <div className="lbl lbl-faint mt-2">基线 .667</div>
          </div>
        </div>

        {/* AI vs market head-to-head */}
        <div className="grid grid-cols-2 gap-2">
          {p.scoreboard && (
            <div className="rounded-md border border-[var(--line)] bg-[var(--panel-2)] p-2.5">
              <div className="lbl">冠军盘 BRIER</div>
              <div
                className="mono mt-1.5 text-[13px] font-bold"
                style={{ color: p.scoreboard.leader === "AI" ? "var(--up)" : "var(--mkt)" }}
              >
                {p.scoreboard.leader === "AI" ? "AI ▸ 领先" : "市场 ▸ 领先"}
              </div>
              <div className="mono mt-1 text-[11px]" style={{ color: "var(--ink-dim)" }}>
                {p.scoreboard.ai_brier} · {p.scoreboard.pm_brier}
              </div>
            </div>
          )}
          {me && me.n_scored > 0 && (
            <div className="rounded-md border border-[var(--line)] bg-[var(--panel-2)] p-2.5">
              <div className="lbl">单场盘 BRIER</div>
              <div
                className="mono mt-1.5 text-[13px] font-bold"
                style={{
                  color:
                    (me.ai_brier ?? 1) < (me.pm_brier ?? 1) ? "var(--up)" : "var(--mkt)",
                }}
              >
                {(me.ai_brier ?? 1) < (me.pm_brier ?? 1) ? "AI ▸ 领先" : "市场 ▸ 领先"}
              </div>
              <div className="mono mt-1 text-[11px]" style={{ color: "var(--ink-dim)" }}>
                {me.ai_brier} · {me.pm_brier}
              </div>
            </div>
          )}
        </div>

        {/* per-stage hit-rate — real ledger, fills the column with signal */}
        {stageAcc.length > 1 && (
          <div className="border-t border-[var(--line)] pt-3">
            <div className="lbl mb-2">分阶段判对率 BY STAGE</div>
            <div className="space-y-1.5">
              {stageAcc.map((s) => (
                <div key={s.stage} className="flex items-center gap-2">
                  <span className="lbl lbl-faint w-16 shrink-0">{STAGE_ZH[s.stage] ?? s.stage}</span>
                  <div className="bar-track flex-1" style={{ height: 5 }}>
                    <div
                      className="bar-fill"
                      style={{ width: `${s.rate * 100}%`, background: "var(--up)" }}
                    />
                  </div>
                  <span
                    className="mono w-16 shrink-0 text-right text-[11px]"
                    style={{ color: "var(--ink-dim)" }}
                  >
                    {(s.rate * 100).toFixed(0)}%{" "}
                    <span style={{ color: "var(--ink-faint)" }}>
                      {s.hit}/{s.n}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* recent verdicts strip */}
        <div className="flex flex-col">
          <div className="mb-2 flex items-center justify-between">
            <span className="lbl">RECENT VERDICTS 近期战绩</span>
            <button onClick={onOpen} className="lbl transition-colors hover:text-[var(--ink)]">
              全部 →
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {p.details.slice(0, 48).map((d, i) => (
              <span
                key={i}
                title={`${zh(d.home)} ${d.score} ${zh(d.away)} · ${STAGE_ZH[d.stage] ?? d.stage} · ${d.winner_hit ? "判对" : "判错"}`}
                className="flex h-5 w-5 items-center justify-center rounded-[3px]"
                style={{
                  background: d.winner_hit ? "var(--up-soft)" : "var(--down-soft)",
                  color: d.winner_hit ? "var(--up)" : "var(--down)",
                }}
              >
                {d.winner_hit ? (
                  <CheckIcon className="h-3 w-3" />
                ) : (
                  <XIcon className="h-3 w-3" />
                )}
              </span>
            ))}
          </div>
          {p.n_score_preds > 0 && (
            <div className="mono mt-3 text-[11px]" style={{ color: "var(--ink-dim)" }}>
              精确比分命中{" "}
              <b style={{ color: "var(--ink)" }}>
                {p.score_hits}/{p.n_score_preds}
              </b>
              {me?.edge_hit_rate != null && (
                <>
                  {"　"}盘口 edge 命中{" "}
                  <b style={{ color: "var(--ink)" }}>{(me.edge_hit_rate * 100).toFixed(0)}%</b>
                </>
              )}
            </div>
          )}
        </div>

        {/* model ensemble roster — the models behind every call */}
        <div
          className="mono flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-[var(--line)] pt-2.5 text-[10px]"
          style={{ color: "var(--ink-faint)" }}
        >
          <span className="lbl lbl-faint">ENSEMBLE</span>
          {data.meta.models.map((mdl) => (
            <span
              key={mdl}
              className="rounded-[3px] border border-[var(--line)] px-1.5 py-0.5"
              style={{ color: "var(--ink-dim)" }}
            >
              {mdl}
            </span>
          ))}
        </div>

        {cal && (Math.abs(cal.T - 1) > 0.02 || Math.abs(cal.delta) > 0.02) && (
          <div className="mono border-t-0 pt-1 text-[10px]" style={{ color: "var(--ink-faint)" }}>
            CALIB · T={cal.T.toFixed(2)}
            {cal.delta > 0 ? ` · DRAW+${cal.delta.toFixed(2)}` : ""} · n={cal.n_wc}
          </div>
        )}
      </div>
    </Panel>
  );
}

/* ═══════════════════ MATCHDAY (center) ═════════════════════ */

function TeamLine({
  name,
  right = false,
  dim = false,
}: {
  name: string;
  right?: boolean;
  dim?: boolean;
}) {
  return (
    <div
      className={`flex min-w-0 flex-1 items-center gap-2.5 ${right ? "flex-row-reverse text-right" : ""} ${dim ? "opacity-45" : ""}`}
    >
      <Flag name={name} className="h-6 w-8 shrink-0" />
      <div className="min-w-0">
        <div className="truncate text-[15px] font-bold leading-tight">{zh(name)}</div>
        <div className="lbl lbl-faint mt-0.5 truncate" style={{ fontSize: 10 }}>
          {engCode(name)}
        </div>
      </div>
    </div>
  );
}

function ProbBar({
  segs,
  tall,
}: {
  segs: { w: number; color: string }[];
  tall?: boolean;
}) {
  return (
    <div className={`flex ${tall ? "h-2.5" : "h-1.5"} overflow-hidden rounded-sm`}>
      {segs.map((s, i) => (
        <div key={i} style={{ width: `${s.w * 100}%`, background: s.color }} />
      ))}
    </div>
  );
}

function MatchOddsRow({ m, poly }: { m: Match; poly: PolyLive }) {
  const live = poly.matches[kickoffEpoch(m.kickoff_utc)];
  const snap = m.market;
  const prices = live ?? (snap ? { home: snap.home, draw: snap.draw, away: snap.away } : null);
  if (!prices) return null;
  const isWs = live?.src === "ws" && live.ts != null && Date.now() - live.ts < 120e3;
  const top =
    m.edge && m.edge.length
      ? [...m.edge].sort((a, b) => Math.abs(b.edge_pct) - Math.abs(a.edge_pct))[0]
      : null;
  return (
    <div className="mono flex items-center gap-x-3 text-[11px]" style={{ color: "var(--ink-dim)" }}>
      <span className="flex items-center gap-1">
        {live && (
          <span
            className={`inline-block h-1 w-1 rounded-full ${isWs ? "live-dot" : ""}`}
            style={{ background: isWs ? "var(--up)" : "var(--ink-faint)" }}
          />
        )}
        <span className="lbl lbl-faint" style={{ color: isWs ? "var(--up)" : undefined }}>
          {isWs ? "PM·LIVE" : "PM"}
        </span>
      </span>
      <span>
        主 <b style={{ color: "var(--ink)" }}>{oddsFmt(prices.home)}</b>
      </span>
      <span>
        平 <b style={{ color: "var(--ink)" }}>{oddsFmt(prices.draw)}</b>
      </span>
      <span>
        客 <b style={{ color: "var(--ink)" }}>{oddsFmt(prices.away)}</b>
      </span>
      {top && (
        <EdgeFlag
          dir={top.direction}
          strong={top.strength === "STRONG EDGE"}
          txt={`${top.direction === "BUY" ? "低估" : "高估"}${top.side === "home" ? "主" : top.side === "draw" ? "平" : "客"} ${top.edge_pct > 0 ? "+" : ""}${top.edge_pct.toFixed(1)}`}
        />
      )}
    </div>
  );
}

function TodayCard({
  m,
  live,
  poly,
  onOpen,
}: {
  m: Match;
  live: LiveMap;
  poly: PolyLive;
  onOpen: (m: Match) => void;
}) {
  const p = m.pred;
  const lv = live[m.espn_id];
  const ko = KO_STAGES.has(m.stage);
  const venue = [m.city].filter(Boolean).join("");
  const stageLbl =
    m.stage === "group" && m.group ? `${m.group}组` : STAGE_ZH[m.stage] ?? m.stage;

  const finished = m.completed || lv?.completed;
  const inPlay = lv?.state === "in";
  const loser =
    m.completed && m.winner ? (m.winner === m.home ? "away" : "home") : null;

  const mid = inPlay ? (
    <div className="text-center">
      <div className="mono text-2xl font-bold leading-none">
        {lv.home_score}<span style={{ color: "var(--ink-faint)" }}>-</span>{lv.away_score}
      </div>
      <div
        className="mono mt-1 flex items-center justify-center gap-1 text-[11px] font-medium"
        style={{ color: "var(--down)" }}
      >
        <span className="live-dot h-1.5 w-1.5 rounded-full" style={{ background: "var(--down)" }} />
        {lv.clock || "LIVE"}
      </div>
    </div>
  ) : finished ? (
    <div className="text-center">
      <div className="mono text-2xl font-bold leading-none">
        {m.home_score ?? lv?.home_score}
        <span style={{ color: "var(--ink-faint)" }}>-</span>
        {m.away_score ?? lv?.away_score}
      </div>
      <div className="lbl lbl-faint mt-1">完场 FT</div>
    </div>
  ) : (
    <div className="text-center">
      <div className="mono text-[15px] font-semibold" style={{ color: "var(--ink-dim)" }}>
        {fmtTime(m.kickoff_utc)}
      </div>
      {p && (
        <div className="lbl lbl-faint mt-1">预测 {p.scoreline.most_likely}</div>
      )}
    </div>
  );

  return (
    <button
      onClick={() => onOpen(m)}
      className="block w-full rounded-md border border-[var(--line)] bg-[var(--panel-2)] p-3 text-left transition-colors hover:border-[var(--line-strong)]"
    >
      <div className="mb-2.5 flex items-center justify-between">
        <span className="mono inline-flex items-center rounded-[3px] bg-[rgba(255,255,255,.05)] px-1.5 py-0.5 text-[10px] font-semibold tracking-wide">
          {stageLbl}
        </span>
        <span className="lbl lbl-faint truncate">{venue}</span>
      </div>

      <div className="flex items-center gap-3">
        <TeamLine name={m.home} dim={loser === "home"} />
        <div className="shrink-0 px-1">{mid}</div>
        <TeamLine name={m.away} right dim={loser === "away"} />
      </div>

      {!finished && p && (
        <div className="mt-3.5 space-y-3">
          {ko ? (
            <div className="space-y-1.5">
              <ProbBar
                tall
                segs={[
                  { w: p.p_adv_home ?? 0, color: "var(--up)" },
                  { w: p.p_adv_away ?? 0, color: "var(--down)" },
                ]}
              />
              <div className="mono flex justify-between text-[11px]">
                <span style={{ color: "var(--up)" }}>晋级 {pct(p.p_adv_home ?? 0)}</span>
                <span style={{ color: "var(--ink-faint)" }}>
                  90′ {pct(p.p_home)}/{pct(p.p_draw)}/{pct(p.p_away)}
                </span>
                <span style={{ color: "var(--down)" }}>{pct(p.p_adv_away ?? 0)} 晋级</span>
              </div>
            </div>
          ) : (
            <div className="space-y-1.5">
              <ProbBar
                tall
                segs={[
                  { w: p.p_home, color: "var(--up)" },
                  { w: p.p_draw, color: "var(--neutral)" },
                  { w: p.p_away, color: "var(--down)" },
                ]}
              />
              <div className="mono flex justify-between text-[11px]">
                <span style={{ color: "var(--up)" }}>主胜 {pct(p.p_home)}</span>
                <span style={{ color: "var(--ink-dim)" }}>平 {pct(p.p_draw)}</span>
                <span style={{ color: "var(--down)" }}>{pct(p.p_away)} 客胜</span>
              </div>
            </div>
          )}

          {/* predicted scorelines */}
          <div>
            <div className="lbl lbl-faint mb-1.5">SCORELINE 预测比分</div>
            <div className="flex flex-wrap gap-1.5">
              {p.scoreline.top_scores.slice(0, 6).map((s) => {
                const top = s.score === p.scoreline.most_likely;
                return (
                  <span
                    key={s.score}
                    className="mono rounded-[3px] border px-2 py-1 text-[13px] font-semibold"
                    style={{
                      color: top ? "var(--mkt)" : "var(--ink)",
                      borderColor: top ? "rgba(216,161,58,.4)" : "var(--line)",
                      background: top ? "var(--mkt-soft)" : "var(--panel)",
                    }}
                  >
                    {s.score}
                    <span className="ml-1 text-[10px]" style={{ color: "var(--ink-faint)" }}>
                      {pct(s.p, 1)}
                    </span>
                  </span>
                );
              })}
            </div>
          </div>

          {/* expected-goals / market microstructure */}
          <div className="mono flex flex-wrap gap-x-5 gap-y-1 text-[11px]" style={{ color: "var(--ink-dim)" }}>
            <span>
              xG <b style={{ color: "var(--ink)" }}>{p.scoreline.xg_home}-{p.scoreline.xg_away}</b>
            </span>
            <span>
              大2.5 <b style={{ color: "var(--ink)" }}>{pct(p.scoreline.p_over25)}</b>
            </span>
            <span>
              双方进球 <b style={{ color: "var(--ink)" }}>{pct(p.scoreline.p_btts)}</b>
            </span>
            <span>
              模型 <b style={{ color: "var(--ink)" }}>
                {p.per_model
                  .map((pm) => pct(ko ? (pm.p_adv_home ?? 0) : pm.p_home))
                  .join("/")}
              </b>
            </span>
            {p.elo_home ? (
              <span>
                Elo <b style={{ color: "var(--ink)" }}>{p.elo_home}·{p.elo_away}</b>
              </span>
            ) : null}
          </div>

          <MatchOddsRow m={m} poly={poly} />

          {(() => {
            const d = m.detail;
            if (!d) return null;
            const h2h = d.h2h;
            const h2hLine = h2h?.n
              ? `交锋 ${h2h.n} 次 · ${zh(m.home).slice(0, 4)} ${h2h.w}胜${h2h.d}平${h2h.l}负`
              : "无近代交手";
            const stakes =
              m.stage === "group"
                ? `出线 ${zh(m.home).slice(0, 4)} ${pct(d.advance_home)} · ${zh(m.away).slice(0, 4)} ${pct(d.advance_away)}`
                : `夺冠 ${zh(m.home).slice(0, 4)} ${pct(d.champion_home, 1)} · ${zh(m.away).slice(0, 4)} ${pct(d.champion_away, 1)}`;
            return (
              <div className="space-y-2 border-t border-[var(--line)] pt-2.5">
                <div className="mono flex flex-wrap gap-x-4 text-[11px]" style={{ color: "var(--ink-faint)" }}>
                  <span>{h2hLine}</span>
                  <span>{stakes}</span>
                </div>
                {d.analysis && (
                  <p
                    className="line-clamp-2 border-l-2 pl-2.5 text-[12px] leading-5"
                    style={{ borderColor: "var(--up)", color: "var(--ink-dim)" }}
                  >
                    {d.analysis}
                  </p>
                )}
              </div>
            );
          })()}
        </div>
      )}
      {finished && m.locked && (() => {
        const lk = m.locked;
        const hs = m.home_score ?? lv?.home_score;
        const as = m.away_score ?? lv?.away_score;
        const probs = [lk.p_home, lk.p_draw, lk.p_away];
        const aiIdx = probs.indexOf(Math.max(...probs));
        const aiLbl = ["主胜", "平局", "客胜"][aiIdx];
        // decided in regulation → unambiguous verdict; equal score (pens) → don't force a call
        const decided = hs != null && as != null && hs !== as;
        const hit = decided ? aiIdx === (hs! > as! ? 0 : 2) : null;
        return (
          <div className="mt-3 space-y-2.5 border-t border-[var(--line)] pt-3">
            <div className="space-y-1.5">
              <ProbBar
                segs={[
                  { w: lk.p_home, color: "var(--up)" },
                  { w: lk.p_draw, color: "var(--neutral)" },
                  { w: lk.p_away, color: "var(--down)" },
                ]}
              />
              <div
                className="mono flex justify-between text-[10px]"
                style={{ color: "var(--ink-faint)" }}
              >
                <span>赛前 主 {pct(lk.p_home)}</span>
                <span>平 {pct(lk.p_draw)}</span>
                <span>{pct(lk.p_away)} 客</span>
              </div>
            </div>
            <div
              className="mono flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]"
              style={{ color: "var(--ink-dim)" }}
            >
              <span>
                AI 预测 <b style={{ color: "var(--ink)" }}>{aiLbl}</b>
                {lk.pred_score && (
                  <span style={{ color: "var(--ink-faint)" }}> · 比分 {lk.pred_score}</span>
                )}
              </span>
              {hit != null && (
                <span
                  className="rounded-[3px] px-1.5 py-0.5 text-[10px] font-bold"
                  style={{
                    color: hit ? "var(--up)" : "var(--down)",
                    background: hit ? "var(--up-soft)" : "var(--down-soft)",
                  }}
                >
                  {hit ? "判对" : "判错"}
                </span>
              )}
              {!decided && <span className="lbl lbl-faint">点球决胜</span>}
              {lk.brier != null && (
                <span style={{ color: "var(--ink-faint)" }}>Brier {lk.brier.toFixed(3)}</span>
              )}
            </div>
          </div>
        );
      })()}
    </button>
  );
}

function NextUpRow({
  m,
  onOpen,
}: {
  m: Match;
  onOpen: (m: Match) => void;
}) {
  const p = m.pred;
  const ph = p?.p_adv_home ?? p?.p_home ?? 0.5;
  const pa = p?.p_adv_away ?? p?.p_away ?? 0.5;
  const favHome = ph >= pa;
  const stageLbl = STAGE_ZH[m.stage] ?? m.stage;
  const dk = venueDayKey(m.kickoff_utc);
  return (
    <button
      onClick={() => onOpen(m)}
      className="flex w-full items-center gap-3 border-t border-[var(--line)] px-3 py-1.5 text-left transition-colors hover:bg-[var(--panel-2)]"
    >
      <span className="mono w-12 shrink-0 text-[10px]" style={{ color: "var(--ink-faint)" }}>
        {dk.slice(5)}
      </span>
      <span className="lbl lbl-faint w-12 shrink-0">{stageLbl}</span>
      <span className="flex min-w-0 flex-1 items-center gap-2">
        <Flag name={m.home} className="h-3.5 w-5 shrink-0" />
        <span className={`truncate text-[13px] ${favHome ? "font-semibold" : ""}`}>{zh(m.home)}</span>
        <span className="lbl lbl-faint">vs</span>
        <Flag name={m.away} className="h-3.5 w-5 shrink-0" />
        <span className={`truncate text-[13px] ${!favHome ? "font-semibold" : ""}`}>{zh(m.away)}</span>
      </span>
      {p && (
        <span className="mono shrink-0 text-[11px]" style={{ color: "var(--ink-dim)" }}>
          晋级{" "}
          <b style={{ color: favHome ? "var(--up)" : "var(--down)" }}>
            {zh(favHome ? m.home : m.away).slice(0, 4)} {pct(Math.max(ph, pa))}
          </b>
        </span>
      )}
    </button>
  );
}

function MatchdayPanel({
  data,
  live,
  poly,
  onOpenMatch,
  className,
}: {
  data: Data;
  live: LiveMap;
  poly: PolyLive;
  onOpenMatch: (m: Match) => void;
  className?: string;
}) {
  // Center shows ONLY unfinished fixtures (upcoming or in-play). Completed
  // matches are hidden entirely — no FT cards here. We deliberately ignore
  // data.meta.matchday (it lags on the last *played* day, e.g. it stays on 07-06
  // after those games finish); the focus day is derived from the earliest match
  // that hasn't finished, so the panel rolls forward on its own once a day's
  // games are all played. The earliest unfinished day fills the focus cards;
  // anything later drops to NEXT UP.
  // "Finished" must consider BOTH the static pipeline flag (m.completed, which
  // lags) AND the live ESPN feed (live[id].completed) — a match can be FT on the
  // wire while data.json still says false. Filter on the live-aware status so a
  // just-finished game disappears from the focus immediately.
  const isFinished = (m: Match) => m.completed || live[m.espn_id]?.completed;
  const notFinished = data.matches
    .filter((m) => !m.tbd && !isFinished(m))
    .sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
  const focusDay = notFinished.length
    ? venueDayKey(notFinished[0].kickoff_utc)
    : null;
  const focusCards = notFinished.filter(
    (m) => venueDayKey(m.kickoff_utc) === focusDay
  );
  const nextUp = notFinished.filter(
    (m) => venueDayKey(m.kickoff_utc) !== focusDay
  );

  return (
    <Panel
      idx="02"
      title="MATCHDAY 焦点赛程"
      className={className}
      aside={
        focusDay ? (
          <span className="mono text-[11px]" style={{ color: "var(--mkt)" }}>
            {dayLabel(focusDay)}
          </span>
        ) : (
          <span className="lbl lbl-faint">赛事收官</span>
        )
      }
    >
      <div className="flex h-full flex-col">
        <div className="flex flex-col gap-2 p-3">
          {focusCards.length ? (
            focusCards.map((m) => (
              <TodayCard key={m.espn_id} m={m} live={live} poly={poly} onOpen={onOpenMatch} />
            ))
          ) : (
            <div className="mono py-6 text-center text-[12px]" style={{ color: "var(--ink-faint)" }}>
              赛事收官 — 感谢关注
            </div>
          )}
        </div>
        {nextUp.length > 0 && (
          <div className="flex-none border-t border-[var(--line)]">
            <div className="flex items-center justify-between px-3 py-1.5">
              <span className="lbl">NEXT UP 后续赛程</span>
              <span className="lbl lbl-faint">{nextUp.length} 场</span>
            </div>
            {nextUp.slice(0, 6).map((m) => (
              <NextUpRow key={m.espn_id} m={m} onOpen={onOpenMatch} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

/* ═══════════════════ CHAMPIONS (right) ═════════════════════ */

function ChampionRow({
  c,
  rank,
  maxP,
  liveRaw,
  liveSum,
}: {
  c: Champion;
  rank: number;
  maxP: number;
  liveRaw: Record<string, number> | null;
  liveSum: number;
}) {
  const rawPrice = liveRaw?.[c.team] ?? c.market_raw;
  const marketProb = liveRaw && liveSum > 0 ? rawPrice / liveSum : c.market;
  const e = liveRaw ? liveEdge(c.ai, marketProb, c.edge?.models_agree ?? 0) : c.edge;
  return (
    <div className="flex items-center gap-2.5 border-t border-[var(--line)] px-3 py-1.5">
      <span className="mono w-4 shrink-0 text-[11px]" style={{ color: "var(--ink-faint)" }}>
        {rank}
      </span>
      <Flag name={c.team} className="h-3.5 w-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-semibold">{zh(c.team)}</span>
          {e && (
            <EdgeFlag
              dir={e.direction}
              strong={e.strength === "STRONG EDGE"}
              txt={`${e.edge_pct > 0 ? "+" : ""}${e.edge_pct.toFixed(1)}`}
            />
          )}
        </div>
        <div className="mt-0.5 space-y-0.5">
          <div className="bar-track" style={{ height: 4 }}>
            <div
              className="bar-fill"
              style={{ width: `${Math.min(100, (c.ai / maxP) * 100)}%`, background: "var(--up)" }}
            />
          </div>
          <div className="bar-track" style={{ height: 4 }}>
            <div
              className="bar-fill"
              style={{
                width: `${Math.min(100, (marketProb / maxP) * 100)}%`,
                background: "var(--mkt)",
              }}
            />
          </div>
        </div>
      </div>
      <div className="shrink-0 text-right leading-tight">
        <div className="mono text-[13px] font-bold" style={{ color: "var(--up)" }}>
          {pct(c.ai, 1)}
        </div>
        <div className="mono text-[10px]" style={{ color: "var(--ink-faint)" }}>
          {oddsFmt(rawPrice)}
        </div>
      </div>
    </div>
  );
}

function KnockoutMapPanel({
  data,
  live,
  onOpenMatch,
  className,
}: {
  data: Data;
  live: LiveMap;
  onOpenMatch: (match: Match) => void;
  className?: string;
}) {
  return (
    <Panel
      idx="04"
      title="KNOCKOUT MAP 淘汰赛态势"
      className={className}
      aside={<span className="lbl lbl-faint">FT · LIVE/KICKOFF · AI ADV%</span>}
    >
      <KnockoutMap matches={data.matches} live={live} onOpen={onOpenMatch} />
    </Panel>
  );
}

function ChampionPanel({
  data,
  poly,
  onOpen,
  className,
}: {
  data: Data;
  poly: PolyLive;
  onOpen: () => void;
  className?: string;
}) {
  const rows = data.champions.filter((c) => c.ai > 0.0005 || c.market > 0.0005);
  const liveRaw = poly.championFresh ? poly.champion : null;
  const liveSum = liveRaw ? Object.values(liveRaw).reduce((a, b) => a + b, 0) : 0;
  const maxP = Math.max(rows[0]?.ai ?? 0.01, rows[0]?.market ?? 0.01);
  // biggest AI-vs-market divergences — fills the tail as the field narrows
  const edgeLeaders = rows
    .filter((c) => c.edge && Math.abs(c.edge.edge_pct) >= 1)
    .sort((a, b) => Math.abs(b.edge!.edge_pct) - Math.abs(a.edge!.edge_pct))
    .slice(0, 3);
  return (
    <Panel
      idx="03"
      title="CHAMPION RACE 夺冠概率"
      className={className}
      aside={
        <>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-[2px]" style={{ background: "var(--up)" }} />
            <span className="lbl lbl-faint">AI</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-[2px]" style={{ background: "var(--mkt)" }} />
            <span className="lbl lbl-faint">MKT</span>
          </span>
          {poly.championFresh && (
            <span className="flex items-center gap-1">
              <span className="live-dot h-1.5 w-1.5 rounded-full" style={{ background: "var(--up)" }} />
              <span className="lbl" style={{ color: "var(--up)" }}>LIVE</span>
            </span>
          )}
        </>
      }
    >
      <div className="flex h-full flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          {rows.slice(0, 20).map((c, i) => (
            <ChampionRow
              key={c.team}
              c={c}
              rank={i + 1}
              maxP={maxP}
              liveRaw={liveRaw}
              liveSum={liveSum}
            />
          ))}
        </div>
        {edgeLeaders.length > 0 && (
          <div className="flex-none border-t border-[var(--line)] bg-[var(--panel-2)] p-2">
            <div className="lbl mb-1.5">最大分歧 AI vs 市场</div>
            <div className="space-y-1.5">
              {edgeLeaders.map((c) => (
                <div key={c.team} className="flex items-center gap-2">
                  <Flag name={c.team} className="h-3.5 w-5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate text-[12px]">{zh(c.team)}</span>
                  <span className="mono shrink-0 text-[10px]" style={{ color: "var(--ink-faint)" }}>
                    AI {pct(c.ai, 1)} · 市 {pct(c.market, 1)}
                  </span>
                  <EdgeFlag
                    dir={c.edge!.direction}
                    strong={c.edge!.strength === "STRONG EDGE"}
                    txt={`${c.edge!.edge_pct > 0 ? "+" : ""}${c.edge!.edge_pct.toFixed(1)}`}
                  />
                </div>
              ))}
            </div>
          </div>
        )}
        <button
          onClick={onOpen}
          className="lbl flex-none border-t border-[var(--line)] py-2 text-center transition-colors hover:text-[var(--ink)]"
        >
          全部 {rows.length} 队 · 分阶段概率 →
        </button>
      </div>
    </Panel>
  );
}

/* ═══════════════════ TICKER (footer) ═══════════════════════ */

function Ticker({
  data,
  onNav,
}: {
  data: Data;
  onNav: (v: "groups" | "record" | "weather") => void;
}) {
  return (
    <footer className="panel reveal flex-none">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 py-1.5">
        <span className="mono hidden text-[10px] lg:inline" style={{ color: "var(--ink-faint)" }}>
          PIPELINE: {data.meta.models.join(" · ")} → Elo → Bradley-Terry(Davidson) → 50K Monte-Carlo
        </span>
        <span className="lbl lbl-faint hidden md:inline">仅供研究娱乐 · 非投注建议</span>
        <div className="ml-auto flex items-center gap-1.5">
          {(
            [
              ["groups", "小组积分"],
              ["record", "完整战绩"],
              ["weather", "天气研究"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              onClick={() => onNav(k)}
              className="lbl rounded-[3px] border border-[var(--line)] px-2 py-1 transition-colors hover:border-[var(--line-strong)] hover:text-[var(--ink)]"
            >
              {label}
            </button>
          ))}
          <a
            href="https://github.com/YSKM523/worldcup-oracle"
            target="_blank"
            rel="noopener noreferrer"
            className="lbl rounded-[3px] border border-[var(--line)] px-2 py-1 transition-colors hover:border-[var(--line-strong)] hover:text-[var(--ink)]"
          >
            GITHUB ↗
          </a>
        </div>
      </div>
    </footer>
  );
}

/* ═══════════════════ DRAWER (overlay) ══════════════════════ */

function Drawer({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", h);
      document.body.style.overflow = "";
    };
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/60 backdrop-blur-sm sm:items-center sm:justify-center sm:p-6"
      onClick={onClose}
    >
      <div
        className="panel reveal flex max-h-full w-full flex-col"
        style={{ maxWidth: wide ? 1000 : 720 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-head">
          <span className="lbl lbl-faint">▚</span>
          <span className="lbl" style={{ color: "var(--ink)" }}>{title}</span>
          <button
            onClick={onClose}
            className="ml-auto flex h-6 w-6 items-center justify-center rounded-[3px] border border-[var(--line)] transition-colors hover:border-[var(--line-strong)]"
            aria-label="关闭"
          >
            <XIcon className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="drawer-scroll overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}

/* ═══════════════════ MATCH MODAL (two-pane, large) ═════════ */

function MatchModal({
  m,
  meta,
  live,
  poly,
  weather,
  onClose,
}: {
  m: Match;
  meta: Meta;
  live: LiveMap;
  poly: PolyLive;
  weather: WeatherData | null;
  onClose: () => void;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", h);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const slug = m.market?.slug;
  const kalshi = useKalshiMarket({
    home: m.home,
    away: m.away,
    kickoffUtc: m.kickoff_utc,
    enabled: shouldEnableKalshiMarket(m),
  });
  const liveEntry = live[m.espn_id];
  const isStarted = m.completed || liveEntry?.state === "in" || liveEntry?.state === "post" || !!liveEntry?.completed;
  const titleId = `match-dialog-title-${m.espn_id}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/72 p-2 backdrop-blur-sm sm:items-center sm:p-6"
      onClick={onClose}
    >
      <div
        className="panel reveal flex max-h-[calc(100dvh-16px)] w-full max-w-[1600px] flex-col xl:max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="panel-head">
          <span className="lbl lbl-faint">▚</span>
          <span id={titleId} className="lbl text-[var(--ink)]">MATCH DETAIL · {zh(m.home)} vs {zh(m.away)}</span>
          <span className="lbl lbl-faint ml-2 hidden sm:inline">
            {(m.stage === "group" && m.group ? `${m.group}组` : STAGE_ZH[m.stage] ?? m.stage)}
            {m.city ? ` · ${m.city}` : ""}
          </span>
          <button
            onClick={onClose}
            className="ml-auto flex h-11 w-11 items-center justify-center rounded-[3px] border border-[var(--line)] transition-colors hover:border-[var(--line-strong)]"
            aria-label="关闭"
          >
            <XIcon className="h-3.5 w-3.5" />
          </button>
        </div>

        <div
          data-match-modal-grid
          className="grid min-h-0 max-h-[calc(100dvh-54px)] grid-cols-1 grid-rows-[max-content_max-content_max-content] overflow-y-auto xl:max-h-[calc(90vh-37px)] xl:grid-cols-[270px_minmax(0,1fr)_minmax(440px,500px)] xl:grid-rows-none xl:overflow-hidden"
        >
          <section data-match-column="prediction" className="drawer-scroll order-1 min-h-0 border-b border-[var(--line)] p-3 xl:order-2 xl:overflow-y-auto xl:border-b-0 xl:border-r">
            <FocusCard m={m} meta={meta} live={live} poly={poly} weather={weather} hideBook variant="console" />
          </section>
          <section data-match-column="stats" className="drawer-scroll order-2 min-h-0 border-b border-[var(--line)] p-3 xl:order-1 xl:overflow-y-auto xl:border-b-0 xl:border-r">
            {isStarted ? (
              <LiveStats espnId={m.espn_id} home={m.home} away={m.away} live variant="console" />
            ) : (
              <MatchTelemetry match={m} weather={weather} poly={poly} kalshi={kalshi} />
            )}
          </section>
          <section data-match-column="market" className="drawer-scroll order-3 min-h-0 p-3 xl:overflow-y-auto">
            <MatchDetail
              slug={slug ?? null}
              kickoffUtc={m.kickoff_utc}
              home={m.home}
              away={m.away}
              pred={m.pred}
              liveEntry={live[m.espn_id]}
              kalshi={kalshi}
              variant="console"
            />
          </section>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════ BOOT LOADER ═══════════════════════════ */

function BootLoader({ error }: { error?: boolean }) {
  const lines = [
    "ORACLE // FIFA 2026 WORLD CUP",
    "▸ fetching data.json",
    "▸ connecting Polymarket CLOB WS",
    "▸ hydrating 50K Monte-Carlo snapshot",
  ];
  return (
    <div className="flex h-dvh flex-col items-center justify-center">
      <div className="mono text-[13px] leading-7" style={{ color: "var(--ink-dim)" }}>
        {error ? (
          <div style={{ color: "var(--down)" }}>× 数据加载失败 — 请刷新重试</div>
        ) : (
          <>
            {lines.map((l, i) => (
              <div key={i} style={{ color: i === 0 ? "var(--up)" : undefined }}>
                {l}
              </div>
            ))}
            <div className="cursor mt-1" style={{ color: "var(--ink-faint)" }}>
              booting
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════ ROOT DASHBOARD ════════════════════════ */

type DrawerState =
  | { kind: "match"; m: Match }
  | { kind: "groups" | "record" | "weather" | "champions" }
  | null;

export function Dashboard({
  data,
  live,
  poly,
  weather,
  error,
}: {
  data: Data | null;
  live: LiveMap;
  poly: PolyLive;
  weather: WeatherData | null;
  error?: boolean;
}) {
  const [drawer, setDrawer] = useState<DrawerState>(null);

  if (!data) return <BootLoader error={error} />;

  return (
    <div className="dash-root flex min-h-dvh flex-col gap-2 p-2 xl:grid xl:h-dvh xl:grid-rows-[auto_minmax(0,1fr)_auto] xl:overflow-hidden">
      <TopBar data={data} poly={poly} />

      {/*
        Responsive tiers:
          • phone  (<768px): single column, natural scroll — MATCHDAY first.
          • tablet / compact desktop (768–1279px): two columns — MATCHDAY spans the top row,
            PERFORMANCE + CHAMPION share the row beneath it.
          • large desktop (≥1280px): the three-column fill-screen mission-control grid.
        order-* handles the mobile/tablet reflow; xl:* restores DOM order.
      */}
      <div className="grid min-h-0 grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(260px,22%)_minmax(0,1fr)_minmax(340px,26%)] xl:grid-rows-[minmax(360px,.9fr)_minmax(260px,.7fr)]">
        <PerformancePanel
          data={data}
          onOpen={() => setDrawer({ kind: "record" })}
          className="order-3 xl:col-start-1 xl:row-start-1 xl:order-none"
        />
        <MatchdayPanel
          data={data}
          live={live}
          poly={poly}
          onOpenMatch={(m) => setDrawer({ kind: "match", m })}
          className="order-1 md:col-span-2 xl:col-span-1 xl:col-start-2 xl:row-start-1 xl:order-none"
        />
        <KnockoutMapPanel
          data={data}
          live={live}
          onOpenMatch={(m) => setDrawer({ kind: "match", m })}
          className="order-2 md:col-span-2 xl:col-span-2 xl:col-start-1 xl:row-start-2 xl:order-none"
        />
        <ChampionPanel
          data={data}
          poly={poly}
          onOpen={() => setDrawer({ kind: "champions" })}
          className="order-4 xl:col-start-3 xl:row-span-2 xl:row-start-1 xl:order-none"
        />
      </div>

      <Ticker data={data} onNav={(v) => setDrawer({ kind: v })} />

      {drawer?.kind === "match" && (
        <MatchModal
          m={drawer.m}
          meta={data.meta}
          live={live}
          poly={poly}
          weather={weather}
          onClose={() => setDrawer(null)}
        />
      )}
      {drawer?.kind === "record" && (
        <Drawer title="AI PERFORMANCE · 完整战绩" wide onClose={() => setDrawer(null)}>
          <RecordView data={data} />
        </Drawer>
      )}
      {drawer?.kind === "champions" && (
        <Drawer title="CHAMPION RACE · 全部球队" wide onClose={() => setDrawer(null)}>
          <ChampionsView data={data} poly={poly} />
        </Drawer>
      )}
      {drawer?.kind === "groups" && (
        <Drawer title="GROUP STANDINGS · 小组积分" wide onClose={() => setDrawer(null)}>
          <GroupsView data={data} />
        </Drawer>
      )}
      {drawer?.kind === "weather" && (
        <Drawer title="WEATHER LAB · 天气研究" wide onClose={() => setDrawer(null)}>
          {weather ? (
            <WeatherLabView wx={weather} />
          ) : (
            <div className="mono py-10 text-center text-[12px]" style={{ color: "var(--ink-faint)" }}>
              天气研究数据加载中…
            </div>
          )}
        </Drawer>
      )}
    </div>
  );
}
