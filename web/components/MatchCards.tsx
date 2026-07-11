"use client";

import { useState } from "react";
import { CheckIcon, Flag, StarIcon, XIcon } from "@/components/icons";
import { MatchDetail } from "@/components/MatchDetail";
import type { FormEntry, LiveMap, Match, MatchWeather, Meta, PolyLive, WeatherData } from "@/lib/types";
import {
  KO_STAGES,
  MODEL_SHORT,
  STAGE_ZH,
  fmtTime,
  kickoffEpoch,
  oddsFmt,
  pct,
  zh,
} from "@/lib/wc";

/* ── Shared bits ───────────────────────────────────────────────── */

/** 开球时天气小徽章：温度+湿度，≥27°C 标酷热。预报值加 ~ 前缀。 */
function WeatherChip({ w }: { w?: MatchWeather }) {
  if (!w) return null;
  return (
    <span
      className={`shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-medium tabular-nums ${
        w.hot ? "bg-orange-500/15 text-orange-300" : "bg-zinc-800/80 text-zinc-400"
      }`}
      title={`开球时${w.forecast ? "预报" : "实测"}：气温 ${w.temp_c}°C · 湿度 ${w.humidity_pct}% · 体感 ${w.apparent_c}°C`}
    >
      {w.hot ? "🔥" : "🌡"} {w.forecast ? "~" : ""}
      {Math.round(w.temp_c)}°C {w.humidity_pct}%
    </span>
  );
}

/** 天气实验室：实验性 favorite 修正行（仅未开赛且 |Δ|≥0.5pp 时展示，不改官方预测）。 */
function WeatherLabLine({ m, w }: { m: Match; w?: MatchWeather }) {
  const p = m.pred;
  if (!w || !p || m.completed || Math.abs(w.exp_delta_pp) < 0.5) return null;
  const ko = KO_STAGES.has(m.stage);
  const pHome = ko ? (p.p_adv_home ?? p.p_home) : p.p_home;
  const pAway = ko ? (p.p_adv_away ?? p.p_away) : p.p_away;
  const favHome = pHome >= pAway;
  const pFav = favHome ? pHome : pAway;
  const adj = Math.min(0.97, Math.max(0.03, pFav + w.exp_delta_pp / 100));
  return (
    <div className="mt-2 text-[11px] leading-4 text-zinc-600">
      🌡️ 天气实验室（实验性·不计官方）：{w.hot ? "酷热" : w.temp_c < 22 ? "凉爽" : "温和"}场{" "}
      {zh(favHome ? m.home : m.away)}
      {ko ? "晋级" : "胜"}率 {pct(pFav)} → <b className="text-zinc-400">{pct(adj)}</b>{" "}
      <span className="tabular-nums">
        ({w.exp_delta_pp > 0 ? "+" : ""}
        {w.exp_delta_pp}pp)
      </span>
    </div>
  );
}

function StageBadge({ m }: { m: Match }) {
  const label =
    m.stage === "group" && m.group ? `小组赛 · ${m.group} 组` : (STAGE_ZH[m.stage] ?? m.stage);
  return (
    <span className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-[11px] font-medium text-zinc-300">
      {label}
    </span>
  );
}

function WdlBar({ h, d, a }: { h: number; d: number; a: number }) {
  return (
    <div>
      <div className="flex h-1.5 overflow-hidden rounded-full">
        <div className="bg-emerald-400" style={{ width: `${h * 100}%` }} />
        <div className="bg-zinc-700" style={{ width: `${d * 100}%` }} />
        <div className="bg-rose-500" style={{ width: `${a * 100}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-xs tabular-nums text-zinc-400">
        <span>
          主胜 <b className="text-emerald-400">{pct(h)}</b>
        </span>
        <span>
          平 <b className="text-zinc-300">{pct(d)}</b>
        </span>
        <span>
          客胜 <b className="text-rose-400">{pct(a)}</b>
        </span>
      </div>
    </div>
  );
}

function AdvBar({ m }: { m: Match }) {
  const p = m.pred!;
  return (
    <div>
      <div className="flex h-1.5 overflow-hidden rounded-full">
        <div className="bg-emerald-400" style={{ width: `${(p.p_adv_home ?? 0) * 100}%` }} />
        <div className="bg-rose-500" style={{ width: `${(p.p_adv_away ?? 0) * 100}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-xs tabular-nums text-zinc-400">
        <span>
          晋级 <b className="text-emerald-400">{pct(p.p_adv_home ?? 0)}</b>
        </span>
        <span className="text-zinc-500">
          90 分钟 {pct(p.p_home)} / {pct(p.p_draw)} / {pct(p.p_away)}
        </span>
        <span>
          晋级 <b className="text-rose-400">{pct(p.p_adv_away ?? 0)}</b>
        </span>
      </div>
    </div>
  );
}

function ScoreMid({ m, live }: { m: Match; live: LiveMap }) {
  const lv = live[m.espn_id];
  if (lv && lv.state === "in") {
    return (
      <div className="shrink-0 text-center">
        <div className="text-xl font-bold tabular-nums">
          {lv.home_score} - {lv.away_score}
        </div>
        <div className="mt-0.5 flex items-center justify-center gap-1.5 text-xs font-medium text-rose-400">
          <span className="live-dot h-1.5 w-1.5 rounded-full bg-rose-500" />
          {lv.clock || "进行中"}
        </div>
      </div>
    );
  }
  const fin = m.completed ? m : lv?.completed ? lv : null;
  if (fin) {
    return (
      <div className="shrink-0 text-center">
        <div className="text-xl font-bold tabular-nums">
          {fin.home_score} - {fin.away_score}
        </div>
        <div className="mt-0.5 text-xs text-zinc-500">完场</div>
      </div>
    );
  }
  return (
    <div className="shrink-0 text-center">
      <div className="text-sm font-medium tabular-nums text-zinc-400">{fmtTime(m.kickoff_utc)}</div>
      {m.pred && (
        <div className="mt-0.5 text-xs text-zinc-500">
          预测 <span className="font-semibold text-zinc-300">{m.pred.scoreline.most_likely}</span>
        </div>
      )}
    </div>
  );
}

function ResultLine({ m }: { m: Match }) {
  const lk = m.locked;
  if (!lk)
    return <div className="mt-3 text-xs text-zinc-500">该场无赛前预测存档</div>;

  let outcome: string;
  let hit: boolean;
  if (KO_STAGES.has(m.stage)) {
    const side = lk.p_home >= lk.p_away ? m.home : m.away;
    outcome = `赛前预测晋级方：${zh(side)}（${pct(Math.max(lk.p_home, lk.p_away))}）`;
    hit = m.winner === side;
  } else {
    const probs: [string, number, boolean][] = [
      ["主胜", lk.p_home, (m.home_score ?? 0) > (m.away_score ?? 0)],
      ["平局", lk.p_draw, m.home_score === m.away_score],
      ["客胜", lk.p_away, (m.home_score ?? 0) < (m.away_score ?? 0)],
    ];
    probs.sort((x, y) => y[1] - x[1]);
    outcome = `赛前预测：${probs[0][0]}（${pct(probs[0][1])}）`;
    hit = probs[0][2];
  }
  const actual = `${m.home_score}-${m.away_score}`;
  const scoreHit = lk.pred_score === actual;
  return (
    <div className="mt-3 text-xs leading-6 text-zinc-400">
      {outcome}{" "}
      <b
        className={`inline-flex items-center gap-1 align-middle ${
          hit ? "text-emerald-400" : "text-rose-400"
        }`}
      >
        {hit ? <CheckIcon className="h-3 w-3" /> : <XIcon className="h-3 w-3" />}
        {hit ? "判对" : "判错"}
      </b>
      {lk.pred_score && (
        <>
          {"　比分预测 "}
          {lk.pred_score}{" "}
          <b
            className={`inline-flex items-center gap-1 align-middle ${
              scoreHit ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {scoreHit && <CheckIcon className="h-3 w-3" />}
            {scoreHit ? "命中" : "未中"}
          </b>
        </>
      )}
      {lk.brier != null && <span className="text-zinc-500">　Brier {lk.brier.toFixed(3)}</span>}
    </div>
  );
}

/** Polymarket per-match decimal odds (W/D/L). WS mid-price when streaming, else gamma/snapshot.
 *  `hideBook` suppresses the inline 盘口 toggle (used when the book has its own pane). */
function MarketOdds({ m, poly, hideBook }: { m: Match; poly: PolyLive; hideBook?: boolean }) {
  const [showBook, setShowBook] = useState(false);
  const live = poly.matches[kickoffEpoch(m.kickoff_utc)];
  const snap = m.market;
  const prices = live ?? (snap ? { home: snap.home, draw: snap.draw, away: snap.away } : null);
  if (!prices) return null;
  const isWs = live?.src === "ws" && live.ts != null && Date.now() - live.ts < 120e3;
  return (
    <>
    <div className="mt-2 flex items-center gap-x-4 gap-y-1 text-[11px] text-zinc-500">
      <span
        className="inline-flex items-center gap-1 text-zinc-600"
        title={
          isWs
            ? "CLOB WebSocket 逐笔推送 · 订单簿中间价"
            : live
              ? "Gamma API 5 分钟快照 · 最新成交价"
              : "每日构建时的快照价"
        }
      >
        {live && (
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              isWs ? "live-dot bg-emerald-400" : "bg-zinc-600"
            }`}
          />
        )}
        Polymarket {isWs ? <b className="font-semibold text-emerald-400">实时</b> : "赔率"}
      </span>
      <span className="tabular-nums">
        主 <b className="text-zinc-300">{oddsFmt(prices.home)}</b>
      </span>
      <span className="tabular-nums">
        平 <b className="text-zinc-300">{oddsFmt(prices.draw)}</b>
      </span>
      <span className="tabular-nums">
        客 <b className="text-zinc-300">{oddsFmt(prices.away)}</b>
      </span>
      {m.edge && m.edge.length > 0 && (() => {
        const top = [...m.edge].sort((a, b) => Math.abs(b.edge_pct) - Math.abs(a.edge_pct))[0];
        const sideZh = top.side === "home" ? "主" : top.side === "draw" ? "平" : "客";
        return (
          <span
            className={`inline-flex items-center gap-0.5 rounded-md border px-1.5 py-px font-bold ${
              top.direction === "BUY"
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : "border-rose-500/30 bg-rose-500/10 text-rose-400"
            }`}
          >
            {top.strength === "STRONG EDGE" && <StarIcon className="h-2.5 w-2.5" />}
            {top.direction === "BUY" ? "低估" : "高估"}
            {sideZh} {top.edge_pct > 0 ? "+" : ""}
            {top.edge_pct.toFixed(1)}
          </span>
        );
      })()}
      {!hideBook && snap?.slug && (
        <button
          onClick={() => setShowBook((v) => !v)}
          className={`ml-auto shrink-0 rounded-md border px-1.5 py-px font-medium transition-colors ${
            showBook
              ? "border-zinc-600 bg-zinc-800 text-zinc-200"
              : "border-zinc-800 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300"
          }`}
        >
          盘口 {showBook ? "▴" : "▾"}
        </button>
      )}
    </div>
    {!hideBook && showBook && snap?.slug && (
      <MatchDetail slug={snap.slug} kickoffUtc={m.kickoff_utc} home={m.home} away={m.away} />
    )}
    </>
  );
}

/* ── Compact schedule card ─────────────────────────────────────── */

export function CompactCard({
  m,
  meta,
  live,
  poly,
  weather,
}: {
  m: Match;
  meta: Meta;
  live: LiveMap;
  poly: PolyLive;
  weather?: WeatherData | null;
}) {
  const p = m.pred;
  const wx = weather?.matches[m.espn_id];
  const venue = [m.venue, m.city].filter(Boolean).join(" · ");
  const loser =
    m.completed && m.winner ? (m.winner === m.home ? "away" : "home")
    : m.completed && m.home_score !== m.away_score
      ? (m.home_score ?? 0) < (m.away_score ?? 0) ? "home" : "away"
      : null;

  return (
    <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <StageBadge m={m} />
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[11px] text-zinc-500">{venue}</span>
          <WeatherChip w={wx} />
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className={`flex min-w-0 flex-1 items-center gap-2.5 ${loser === "home" ? "opacity-50" : ""}`}>
          <Flag name={m.home} className="h-5 w-7 shrink-0" />
          <span className="truncate font-semibold">{zh(m.home)}</span>
        </div>
        <ScoreMid m={m} live={live} />
        <div className={`flex min-w-0 flex-1 flex-row-reverse items-center gap-2.5 ${loser === "away" ? "opacity-50" : ""}`}>
          <Flag name={m.away} className="h-5 w-7 shrink-0" />
          <span className="truncate font-semibold">{zh(m.away)}</span>
        </div>
      </div>
      {m.tbd && <div className="mt-3 text-xs text-zinc-500">对阵待定 — 等待前序比赛结果</div>}
      {m.completed && <ResultLine m={m} />}
      {!m.completed && p && (
        <div className="mt-3.5">
          {KO_STAGES.has(m.stage) ? <AdvBar m={m} /> : <WdlBar h={p.p_home} d={p.p_draw} a={p.p_away} />}
          <div className="mt-2.5 text-xs text-zinc-500">
            比分 <b className="text-zinc-300">{p.scoreline.most_likely}</b>{" "}
            <span className="tabular-nums">({pct(p.scoreline.most_likely_p, 1)})</span>
            {"　"}
            {p.scoreline.top_scores.slice(1, 4).map((s) => `${s.score} ${pct(s.p)}`).join(" · ")}
          </div>
          <ModelRow m={m} meta={meta} />
          <MarketOdds m={m} poly={poly} />
          <WeatherLabLine m={m} w={wx} />
        </div>
      )}
    </div>
  );
}

function ModelRow({ m, meta }: { m: Match; meta: Meta }) {
  const p = m.pred!;
  const ko = KO_STAGES.has(m.stage);
  return (
    <div className="mt-1.5 text-[11px] text-zinc-600">
      {ko ? "晋级率" : "主胜率"}分歧{" "}
      {meta.models
        .map(
          (name, i) =>
            `${MODEL_SHORT[name] ?? name} ${pct(ko ? (p.per_model[i].p_adv_home ?? 0) : p.per_model[i].p_home)}`
        )
        .join(" · ")}
      {p.elo_home ? `　|　Elo ${p.elo_home} vs ${p.elo_away}` : ""}
    </div>
  );
}

/* ── Detailed focus card ───────────────────────────────────────── */

function FormRow({ form }: { form?: FormEntry[] }) {
  if (!form?.length) return null;
  const cls = { W: "bg-emerald-500 text-zinc-950", D: "bg-zinc-700 text-zinc-200", L: "bg-rose-500 text-zinc-950" };
  const label = { W: "胜", D: "平", L: "负" };
  return (
    <div className="mt-2 flex justify-center gap-1">
      {form.map((f, i) => (
        <span
          key={i}
          title={`${f.date} ${f.score} vs ${zh(f.opp)}`}
          className={`flex h-5 w-5 items-center justify-center rounded text-[10px] font-medium ${cls[f.res]}`}
        >
          {label[f.res]}
        </span>
      ))}
    </div>
  );
}

function TeamBig({ m, side }: { m: Match; side: "home" | "away" }) {
  const name = side === "home" ? m.home : m.away;
  const d = m.detail;
  const elo = side === "home" ? d?.elo_home : d?.elo_away;
  const rank = side === "home" ? d?.rank_home : d?.rank_away;
  return (
    <div className="min-w-0 flex-1 text-center">
      <Flag name={name} className="mx-auto h-9 w-[3.25rem]" />
      <div className="mt-1.5 truncate text-base font-bold">{zh(name)}</div>
      {elo ? (
        <div className="mt-0.5 text-[11px] tabular-nums text-zinc-500">
          Elo {elo} · 第 {rank} 位
        </div>
      ) : null}
      <FormRow form={side === "home" ? d?.form_home : d?.form_away} />
    </div>
  );
}

export function FocusCard({
  m,
  meta,
  live,
  poly,
  weather,
  hideBook,
  variant = "card",
}: {
  m: Match;
  meta: Meta;
  live: LiveMap;
  poly: PolyLive;
  weather?: WeatherData | null;
  hideBook?: boolean;
  variant?: "card" | "console";
}) {
  const p = m.pred;
  const d = m.detail;
  const wx = weather?.matches[m.espn_id];
  const venue = [m.venue, m.city].filter(Boolean).join(" · ");
  const h2h = d?.h2h;
  const h2hLine = h2h
    ? h2h.n
      ? `历史交锋 ${h2h.n} 次：${zh(m.home)} ${h2h.w} 胜 ${h2h.d} 平 ${h2h.l} 负` +
        (h2h.last.length
          ? `（最近 ${h2h.last.map((g) => `${g.date.slice(0, 7)} ${g.score}`).join("、")}）`
          : "")
      : "两队 1990 年以来无交手记录"
    : "";
  const stakes = d
    ? m.stage === "group"
      ? `出线概率：${zh(m.home)} ${pct(d.advance_home)} · ${zh(m.away)} ${pct(d.advance_away)}`
      : `夺冠概率：${zh(m.home)} ${pct(d.champion_home, 1)} · ${zh(m.away)} ${pct(d.champion_away, 1)}`
    : "";
  const consoleMode = variant === "console";

  return (
    <div
      data-console-surface={consoleMode ? "prediction" : undefined}
      className={consoleMode ? "flex h-full min-h-full flex-col rounded-none border-0 bg-transparent p-0" : "rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5"}
    >
      {consoleMode && (
        <div className="mb-3 flex min-h-8 items-center gap-2 border-b border-[var(--line)] pb-2">
          <span className="lbl lbl-faint">05</span>
          <span className="lbl text-[var(--ink)]">MATCH FORECAST · 模型预测</span>
          <span className="lbl lbl-faint ml-auto">AI · ELO · MARKET</span>
        </div>
      )}
      <div className={`${consoleMode ? "mb-3" : "mb-4"} flex items-center justify-between gap-2`}>
        <StageBadge m={m} />
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[11px] text-zinc-500">{venue}</span>
          <WeatherChip w={wx} />
        </span>
      </div>

      <div className="flex items-start gap-3">
        <TeamBig m={m} side="home" />
        <div className="mt-3">
          <ScoreMid m={m} live={live} />
        </div>
        <TeamBig m={m} side="away" />
      </div>

      {m.completed ? (
        <ResultLine m={m} />
      ) : p ? (
        <div className="mt-5 space-y-4">
          {KO_STAGES.has(m.stage) ? <AdvBar m={m} /> : <WdlBar h={p.p_home} d={p.p_draw} a={p.p_away} />}

          <div className="flex flex-wrap gap-1.5">
            {p.scoreline.top_scores.map((s) => (
              <span
                key={s.score}
                className={`rounded-lg border px-2.5 py-1 text-sm font-semibold tabular-nums ${
                  s.score === p.scoreline.most_likely
                    ? "border-amber-400/50 bg-amber-400/10 text-amber-300"
                    : "border-zinc-800 bg-zinc-900 text-zinc-300"
                }`}
              >
                {s.score}
                <span className="ml-1.5 text-[11px] font-normal text-zinc-500">{pct(s.p, 1)}</span>
              </span>
            ))}
          </div>

          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-500">
            <span>
              xG{" "}
              <b className="tabular-nums text-zinc-200">
                {p.scoreline.xg_home} - {p.scoreline.xg_away}
              </b>
            </span>
            <span>
              大 2.5 球 <b className="tabular-nums text-zinc-200">{pct(p.scoreline.p_over25)}</b>
            </span>
            <span>
              双方进球 <b className="tabular-nums text-zinc-200">{pct(p.scoreline.p_btts)}</b>
            </span>
          </div>

          <ModelRow m={m} meta={meta} />
          <MarketOdds m={m} poly={poly} hideBook={hideBook} />
          <WeatherLabLine m={m} w={wx} />
        </div>
      ) : null}

      {(h2hLine || stakes) && (
        <div className="mt-4 space-y-1 border-t border-zinc-800/70 pt-3 text-xs leading-5 text-zinc-500">
          {h2hLine && <div>{h2hLine}</div>}
          {stakes && <div>{stakes}</div>}
        </div>
      )}

      {d?.analysis && (
        <div className={`${consoleMode ? "mt-auto pt-4" : "mt-4"} rounded-r-xl border-l-2 border-emerald-500/70 bg-zinc-900/80 p-3.5 text-[13px] leading-6 text-zinc-300`}>
          {d.analysis}
        </div>
      )}
    </div>
  );
}
