"use client";

import { CheckIcon, Flag, XIcon } from "@/components/icons";
import type { FormEntry, LiveMap, Match, Meta, PolyLive } from "@/lib/types";
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

/** Polymarket per-match decimal odds (W/D/L). Live when fresh, else snapshot. */
function MarketOdds({ m, poly }: { m: Match; poly: PolyLive }) {
  const live = poly.matches[kickoffEpoch(m.kickoff_utc)];
  const snap = m.market;
  const prices = live ?? (snap ? { home: snap.home, draw: snap.draw, away: snap.away } : null);
  if (!prices) return null;
  return (
    <div className="mt-2 flex items-center gap-x-4 gap-y-1 text-[11px] text-zinc-500">
      <span className="inline-flex items-center gap-1 text-zinc-600">
        {live && <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />}
        Polymarket 赔率
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
    </div>
  );
}

/* ── Compact schedule card ─────────────────────────────────────── */

export function CompactCard({
  m,
  meta,
  live,
  poly,
}: {
  m: Match;
  meta: Meta;
  live: LiveMap;
  poly: PolyLive;
}) {
  const p = m.pred;
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
        <span className="truncate text-[11px] text-zinc-500">{venue}</span>
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
}: {
  m: Match;
  meta: Meta;
  live: LiveMap;
  poly: PolyLive;
}) {
  const p = m.pred;
  const d = m.detail;
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

  return (
    <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
      <div className="mb-4 flex items-center justify-between gap-2">
        <StageBadge m={m} />
        <span className="truncate text-[11px] text-zinc-500">{venue}</span>
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
          <MarketOdds m={m} poly={poly} />
        </div>
      ) : null}

      {(h2hLine || stakes) && (
        <div className="mt-4 space-y-1 border-t border-zinc-800/70 pt-3 text-xs leading-5 text-zinc-500">
          {h2hLine && <div>{h2hLine}</div>}
          {stakes && <div>{stakes}</div>}
        </div>
      )}

      {d?.analysis && (
        <div className="mt-4 rounded-r-xl border-l-2 border-emerald-500/70 bg-zinc-900/80 p-3.5 text-[13px] leading-6 text-zinc-300">
          {d.analysis}
        </div>
      )}
    </div>
  );
}
