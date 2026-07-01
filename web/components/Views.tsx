"use client";

import { useMemo, useState } from "react";
import { CheckIcon, Flag, StarIcon, XIcon } from "@/components/icons";
import { CompactCard, FocusCard } from "@/components/MatchCards";
import type { Data, LiveMap, Match, PolyLive, WeatherData } from "@/lib/types";
import {
  KO_STAGES,
  MODEL_SHORT,
  fmtDay,
  liveEdge,
  localDateKey,
  oddsFmt,
  pct,
  todayKey,
  venueDayKey,
  zh,
} from "@/lib/wc";

/* ── Schedule (focus + filters) ────────────────────────────────── */

const FILTERS = [
  ["focus", "本期预测"],
  ["upcoming", "后续赛程"],
  ["group", "小组赛"],
  ["ko", "淘汰赛"],
  ["done", "已结束"],
  ["all", "全部"],
] as const;
type Filter = (typeof FILTERS)[number][0];

export function ScheduleView({
  data,
  live,
  poly,
  weather,
}: {
  data: Data;
  live: LiveMap;
  poly: PolyLive;
  weather?: WeatherData | null;
}) {
  const [filter, setFilter] = useState<Filter>("focus");
  const [search, setSearch] = useState("");

  const searchOk = (m: Match) =>
    !search ||
    `${m.home} ${m.away} ${zh(m.home)} ${zh(m.away)}`
      .toLowerCase()
      .includes(search.trim().toLowerCase());

  const matchday = data.meta.matchday;
  const visible = useMemo(() => {
    if (filter === "focus") return [];
    return data.matches.filter((m) => {
      if (!searchOk(m)) return false;
      const finished = m.completed || live[m.espn_id]?.completed;
      switch (filter) {
        case "upcoming":
          return !finished && (!matchday || venueDayKey(m.kickoff_utc) > matchday);
        case "group":
          return m.stage === "group";
        case "ko":
          return KO_STAGES.has(m.stage);
        case "done":
          return !!finished;
        default:
          return true;
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, filter, search, live]);

  const focusMatches = data.matches.filter(
    (m) => !m.tbd && matchday && venueDayKey(m.kickoff_utc) === matchday && searchOk(m)
  );

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors ${
                filter === key
                  ? "bg-zinc-100 text-zinc-950"
                  : "bg-zinc-900 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索球队…"
          className="min-w-32 flex-1 rounded-full border border-zinc-800 bg-zinc-900/60 px-4 py-1.5 text-[13px] outline-none placeholder:text-zinc-600 focus:border-zinc-600"
        />
      </div>

      {filter === "focus" ? (
        <FocusList matchday={matchday} matches={focusMatches} data={data} live={live} poly={poly} weather={weather} />
      ) : visible.length ? (
        <DayGroupedList matches={visible} data={data} live={live} poly={poly} weather={weather} />
      ) : (
        <Empty text="没有符合条件的比赛" />
      )}
    </div>
  );
}

function FocusList({
  matchday,
  matches,
  data,
  live,
  poly,
  weather,
}: {
  matchday: string | null;
  matches: Match[];
  data: Data;
  live: LiveMap;
  poly: PolyLive;
  weather?: WeatherData | null;
}) {
  if (!matchday) return <Empty text="本届赛事已结束 — 战绩见「AI 战绩」页" />;
  if (!matches.length) return <Empty text="没有符合条件的比赛" />;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-base font-bold text-amber-300">
          本期详细预测 · {fmtDay(matchday)} · 共 {matches.length} 场
        </h2>
        <span className="text-xs text-zinc-600">每日 06:00 UTC 出新一期 · 比分实时刷新</span>
      </div>
      <div className="space-y-4">
        {matches.map((m) => (
          <FocusCard key={m.espn_id} m={m} meta={data.meta} live={live} poly={poly} weather={weather} />
        ))}
      </div>
    </div>
  );
}

function DayGroupedList({
  matches,
  data,
  live,
  poly,
  weather,
}: {
  matches: Match[];
  data: Data;
  live: LiveMap;
  poly: PolyLive;
  weather?: WeatherData | null;
}) {
  const groups: [string, Match[]][] = [];
  for (const m of matches) {
    const day = localDateKey(m.kickoff_utc);
    const last = groups[groups.length - 1];
    if (last && last[0] === day) last[1].push(m);
    else groups.push([day, [m]]);
  }
  return (
    <div className="space-y-6">
      {groups.map(([day, ms]) => (
        <section key={day}>
          <h3
            className={`mb-3 border-b border-zinc-800/70 pb-2 text-sm font-medium ${
              day === todayKey() ? "text-amber-300" : "text-zinc-500"
            }`}
          >
            {fmtDay(day)}
            {day === todayKey() && "（今天）"}
          </h3>
          <div className="space-y-3">
            {ms.map((m) => (
              <CompactCard key={m.espn_id} m={m} meta={data.meta} live={live} poly={poly} weather={weather} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="py-16 text-center text-sm text-zinc-600">{text}</div>
);

/* ── Groups ────────────────────────────────────────────────────── */

export function GroupsView({ data }: { data: Data }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {Object.entries(data.groups).map(([g, rows]) => (
        <div key={g} className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4">
          <h3 className="mb-3 text-sm font-bold">{g} 组</h3>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-[11px] text-zinc-600">
                <th className="pb-1.5 text-left font-normal">球队</th>
                <th className="pb-1.5 text-right font-normal">赛</th>
                <th className="pb-1.5 text-right font-normal">胜平负</th>
                <th className="pb-1.5 text-right font-normal">净</th>
                <th className="pb-1.5 text-right font-normal">分</th>
                <th className="pb-1.5 text-right font-normal">出线%</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.team} className="border-t border-zinc-800/60">
                  <td className="py-1.5">
                    <span className="flex items-center gap-2">
                      <Flag name={r.team} className="h-3 w-[1.1rem] shrink-0" />
                      {zh(r.team)}
                    </span>
                  </td>
                  <td className="text-right tabular-nums text-zinc-400">{r.played}</td>
                  <td className="text-right tabular-nums text-zinc-400">
                    {r.w}-{r.d}-{r.l}
                  </td>
                  <td className="text-right tabular-nums text-zinc-400">
                    {r.gd > 0 ? "+" : ""}
                    {r.gd}
                  </td>
                  <td className="text-right font-bold tabular-nums">{r.pts}</td>
                  <td
                    className={`text-right tabular-nums ${
                      r.p_advance >= 0.5 ? "font-semibold text-emerald-400" : "text-zinc-400"
                    }`}
                  >
                    {pct(r.p_advance)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

/* ── Champions ─────────────────────────────────────────────────── */

export function ChampionsView({ data, poly }: { data: Data; poly: PolyLive }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const rows = data.champions.filter((c) => c.ai > 0.0005 || c.market > 0.0005);
  const shown = showAll ? rows : rows.slice(0, 20);
  const maxP = Math.max(shown[0]?.ai ?? 0.01, shown[0]?.market ?? 0.01);

  // Live raw price (vig included) per team, de-vig sum for the edge recompute.
  const liveRaw = poly.championFresh ? poly.champion : null;
  const liveSum = liveRaw ? Object.values(liveRaw).reduce((a, b) => a + b, 0) : 0;

  return (
    <div>
      <p className="mb-4 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-zinc-500">
        <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-400" />
        AI 集成概率
        <span className="ml-2 inline-block h-2.5 w-2.5 rounded-sm bg-zinc-600" />
        Polymarket 市场（右侧为小数赔率）
        {data.meta.volume ? `　总量 $${(data.meta.volume / 1e9).toFixed(2)}B` : ""}
        {poly.championFresh && (
          <span className="inline-flex items-center gap-1 text-emerald-400">
            <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
            实时
          </span>
        )}
        <span className="text-zinc-600">·　点击行展开模型明细</span>
      </p>
      <div className="space-y-2">
        {shown.map((c, i) => {
          const rawPrice = liveRaw?.[c.team] ?? c.market_raw;
          const marketProb = liveRaw && liveSum > 0 ? rawPrice / liveSum : c.market;
          const e = liveRaw ? liveEdge(c.ai, marketProb, c.edge?.models_agree ?? 0) : c.edge;
          const open = expanded === c.team;
          return (
            <button
              key={c.team}
              onClick={() => setExpanded(open ? null : c.team)}
              className="block w-full rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4 text-left transition-colors hover:border-zinc-700"
            >
              <div className="flex items-center gap-3">
                <span className="w-5 shrink-0 text-xs tabular-nums text-zinc-600">{i + 1}</span>
                <span className="flex min-w-0 flex-1 items-center gap-2 whitespace-nowrap font-semibold">
                  <Flag name={c.team} className="h-3.5 w-5 shrink-0" />
                  {zh(c.team)}
                  {e && (
                    <span
                      className={`inline-flex items-center gap-0.5 rounded-md border px-1.5 py-px text-[11px] font-bold ${
                        e.direction === "BUY"
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                          : "border-rose-500/30 bg-rose-500/10 text-rose-400"
                      }`}
                    >
                      {e.strength === "STRONG EDGE" && <StarIcon className="h-2.5 w-2.5" />}
                      {e.direction === "BUY" ? "低估" : "高估"} {e.edge_pct > 0 ? "+" : ""}
                      {e.edge_pct.toFixed(1)}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-right text-sm tabular-nums">
                  <b className="text-emerald-400">{pct(c.ai, 1)}</b>
                  <span className="text-zinc-600"> · 赔率 {oddsFmt(rawPrice)}</span>
                </span>
              </div>
              <div className="mt-2.5 space-y-1">
                <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800/80">
                  <div
                    className="h-full bg-emerald-400"
                    style={{ width: `${Math.min(100, (c.ai / maxP) * 100)}%` }}
                  />
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800/80">
                  <div
                    className="h-full bg-zinc-600"
                    style={{ width: `${Math.min(100, (marketProb / maxP) * 100)}%` }}
                  />
                </div>
              </div>
              {open && (
                <div className="mt-3 border-t border-zinc-800/70 pt-3 text-xs leading-6 text-zinc-400">
                  各模型夺冠概率：
                  {Object.entries(c.per_model)
                    .map(([mn, p]) => `${MODEL_SHORT[mn] ?? mn} ${pct(p, 1)}`)
                    .join(" · ") || "—"}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(
                      [
                        ["出线", c.stages.advance, 0],
                        ["16 强", c.stages.r16, 0],
                        ["8 强", c.stages.qf, 0],
                        ["4 强", c.stages.sf, 0],
                        ["决赛", c.stages.final, 0],
                        ["夺冠", c.stages.champion, 1],
                      ] as const
                    ).map(([label, p, dg]) => (
                      <span
                        key={label}
                        className="rounded-md bg-zinc-800/80 px-2 py-0.5 tabular-nums text-zinc-300"
                      >
                        {label} {pct(p, dg)}
                      </span>
                    ))}
                  </div>
                  {e && (
                    <div className="mt-2">
                      vs 市场：{e.direction === "BUY" ? "AI 认为被低估" : "AI 认为被高估"}{" "}
                      {Math.abs(e.edge_pct).toFixed(1)} 个百分点（{e.models_agree}/
                      {data.meta.models.length} 模型同向
                      {c.edge && c.edge.half_kelly > 0
                        ? `，半凯利仓位 ${pct(c.edge.half_kelly, 1)}`
                        : ""}
                      ）
                    </div>
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>
      {rows.length > 20 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="mx-auto mt-4 block rounded-full bg-zinc-900 px-4 py-1.5 text-[13px] text-zinc-400 hover:text-zinc-200"
        >
          显示全部 {rows.length} 队
        </button>
      )}
    </div>
  );
}

/* ── Record ────────────────────────────────────────────────────── */

export function RecordView({ data }: { data: Data }) {
  const p = data.performance;
  const cards: [string, string][] = [];
  if (p.details.length) {
    cards.push([
      `${((p.winner_hit_rate ?? 0) * 100).toFixed(0)}%`,
      `胜平负判对率（${p.details.length} 场）`,
    ]);
    if (p.n_score_preds > 0) cards.push([`${p.score_hits}/${p.n_score_preds}`, "精确比分命中"]);
    if (p.mean_brier != null) cards.push([p.mean_brier.toFixed(3), "平均 Brier（瞎猜 ≈ 0.667）"]);
  }
  if (p.scoreboard) {
    const s = p.scoreboard;
    cards.push([
      s.leader === "AI" ? "AI 领先" : "市场领先",
      `冠军盘 Brier：AI ${s.ai_brier} vs 市场 ${s.pm_brier}（${s.n_teams} 队已淘汰）`,
    ]);
  }

  const me = data.meta.match_edge;
  if (me && me.n_scored > 0) {
    const hit =
      me.edge_hit_rate != null ? `，命中率 ${(me.edge_hit_rate * 100).toFixed(0)}%` : "";
    const noMkt = me.n_no_market ? `，${me.n_no_market} 场无盘口` : "";
    cards.push([
      (me.ai_brier ?? 1) < (me.pm_brier ?? 1) ? "AI 领先" : "市场领先",
      `单场盘 Brier：AI ${me.ai_brier} vs 市场 ${me.pm_brier}（${me.n_scored} 场${hit}${noMkt}）`,
    ]);
  }

  const cal = data.meta.calibration;
  const showCal =
    cal != null &&
    (Math.abs(cal.T - 1) > 0.02 || Math.abs(cal.delta) > 0.02);

  return (
    <div>
      {showCal && cal && (
        <p className="mb-4 text-xs text-zinc-400">
          已按 {cal.n_wc} 场实战校准（T={cal.T.toFixed(2)}
          {cal.delta > 0 ? `，平局+${cal.delta.toFixed(2)}` : ""}）
        </p>
      )}
      {cards.length > 0 && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {cards.map(([v, label]) => (
            <div
              key={label}
              className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4 text-center"
            >
              <div className="text-xl font-bold tabular-nums text-emerald-400">{v}</div>
              <div className="mt-1 text-[11px] leading-4 text-zinc-500">{label}</div>
            </div>
          ))}
        </div>
      )}
      {p.details.length ? (
        <div className="overflow-x-auto rounded-2xl border border-zinc-800/80">
          <table className="w-full min-w-[480px] text-[13px]">
            <thead>
              <tr className="bg-zinc-900/60 text-left text-[11px] text-zinc-500">
                <th className="px-3 py-2.5 font-normal">对阵</th>
                <th className="px-3 py-2.5 font-normal">比分</th>
                <th className="px-3 py-2.5 font-normal">预测</th>
                <th className="px-3 py-2.5 font-normal">判定</th>
                <th className="px-3 py-2.5 font-normal">Brier</th>
              </tr>
            </thead>
            <tbody>
              {p.details.map((d) => {
                const top = (
                  [
                    ["主胜", d.p_home],
                    ["平", d.p_draw],
                    ["客胜", d.p_away],
                  ] as [string, number][]
                ).sort((a, b) => b[1] - a[1])[0];
                return (
                  <tr key={`${d.kickoff_utc}-${d.home}`} className="border-t border-zinc-800/60">
                    <td className="px-3 py-2.5">
                      <span className="flex items-center gap-1.5">
                        <Flag name={d.home} className="h-3 w-[1.1rem] shrink-0" />
                        {zh(d.home)}
                        <span className="text-zinc-600">vs</span>
                        {zh(d.away)}
                        <Flag name={d.away} className="h-3 w-[1.1rem] shrink-0" />
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-bold tabular-nums">{d.score}</td>
                    <td className="px-3 py-2.5 text-zinc-400">
                      {top[0]} {pct(top[1])}
                      {d.pred_score && (
                        <span className="block text-[11px] text-zinc-600">比分 {d.pred_score}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={`inline-flex items-center ${
                          d.winner_hit ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {d.winner_hit ? (
                          <CheckIcon className="h-3.5 w-3.5" />
                        ) : (
                          <XIcon className="h-3.5 w-3.5" />
                        )}
                      </span>
                      {d.score_hit && (
                        <span className="ml-1.5 inline-flex items-center gap-0.5 text-emerald-400">
                          <CheckIcon className="h-3 w-3" />比分
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-zinc-400">
                      {d.brier != null ? d.brier.toFixed(3) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="还没有已完赛的预测 — 等第一场比赛打完就有了" />
      )}
    </div>
  );
}
