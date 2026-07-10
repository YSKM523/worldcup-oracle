"use client";

import { Flag } from "@/components/icons";
import type { LiveMap, Match } from "@/lib/types";
import { fmtTime, pct, zh } from "@/lib/wc";

type KnockoutMapProps = {
  matches: Match[];
  live: LiveMap;
  onOpen: (match: Match) => void;
};

const STAGES = ["qf", "sf", "final"] as const;
type KnockoutStage = (typeof STAGES)[number];

const STAGE_LABEL: Record<KnockoutStage, string> = {
  qf: "QUARTERFINALS · 1/4 决赛",
  sf: "SEMIFINALS · 半决赛",
  final: "FINAL · 决赛",
};

const stageMatches = (matches: Match[], stage: KnockoutStage) =>
  matches
    .filter((match) => match.stage === stage)
    .sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));

const unresolvedName = (name: string) => /\b(?:Winner|Loser)\b/i.test(name);

function KnockoutNode({
  match,
  live,
  onOpen,
  final = false,
}: {
  match: Match;
  live: LiveMap;
  onOpen: (match: Match) => void;
  final?: boolean;
}) {
  const liveEntry = live[match.espn_id];
  const completed = match.completed || !!liveEntry?.completed;
  const inPlay = liveEntry?.state === "in";
  const unresolved =
    match.tbd || unresolvedName(match.home) || unresolvedName(match.away);
  const homeScore = liveEntry?.home_score ?? match.home_score;
  const awayScore = liveEntry?.away_score ?? match.away_score;
  const advHome = match.pred?.p_adv_home ?? match.pred?.p_home;
  const advAway = match.pred?.p_adv_away ?? match.pred?.p_away;
  const winner =
    match.winner ??
    (completed &&
    homeScore != null &&
    awayScore != null &&
    homeScore !== awayScore
      ? homeScore > awayScore
        ? match.home
        : match.away
      : null);
  const state = unresolved ? "unresolved" : completed ? "completed" : "active";
  const status = completed
    ? "FT"
    : inPlay
      ? liveEntry.clock || "LIVE"
      : fmtTime(match.kickoff_utc);
  const showScore = completed || inPlay;

  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span
          className="lbl lbl-faint"
          style={final ? { color: "var(--mkt)" } : undefined}
        >
          {status}
        </span>
        {final ? <span className="lbl text-[var(--mkt)]">FINAL</span> : null}
      </div>

      {[match.home, match.away].map((team, index) => {
        const score = index === 0 ? homeScore : awayScore;
        const teamUnresolved = unresolvedName(team);
        return (
          <div
            key={`${index}-${team}`}
            className={`mt-1.5 flex items-center gap-2 ${winner && winner !== team ? "opacity-40" : ""}`}
          >
            {teamUnresolved ? (
              <span className="h-3.5 w-5 shrink-0 rounded-[3px] bg-[var(--line)]" aria-hidden />
            ) : (
              <Flag name={team} className="h-3.5 w-5 shrink-0" />
            )}
            <span className="min-w-0 flex-1 truncate text-[12px] font-semibold">
              {zh(team)}
            </span>
            {showScore && score != null ? (
              <span className="mono text-[12px] font-bold">{score}</span>
            ) : null}
          </div>
        );
      })}

      {!unresolved && !completed && advHome != null && advAway != null ? (
        <div className="mt-2">
          <div className="flex h-1 overflow-hidden rounded-[2px] bg-[var(--line)]">
            <span
              style={{
                width: `${Math.max(0, Math.min(1, advHome)) * 100}%`,
                background: "var(--up)",
              }}
            />
            <span
              style={{
                width: `${Math.max(0, Math.min(1, advAway)) * 100}%`,
                background: "var(--down)",
              }}
            />
          </div>
          <div className="mono mt-1 flex justify-between text-[10px] text-[var(--ink-faint)]">
            <span>{pct(advHome)}</span>
            <span>{pct(advAway)}</span>
          </div>
        </div>
      ) : null}
    </>
  );

  const classes = `block w-full rounded-[3px] border p-2 text-left ${
    final
      ? "border-[var(--line-strong)] bg-[var(--panel-2)]"
      : "border-[var(--line)] bg-[var(--panel)]"
  }`;

  return unresolved ? (
    <div data-match-state={state} className={classes}>
      {body}
    </div>
  ) : (
    <button
      data-match-state={state}
      className={`${classes} transition-colors hover:border-[var(--line-strong)] focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--up)]`}
      onClick={() => onOpen(match)}
    >
      {body}
    </button>
  );
}

function StageColumn({
  stage,
  matches,
  live,
  onOpen,
}: {
  stage: KnockoutStage;
  matches: Match[];
  live: LiveMap;
  onOpen: (match: Match) => void;
}) {
  return (
    <section data-knockout-stage={stage} className="flex min-w-0 flex-col">
      <div className="lbl lbl-faint mb-2">{STAGE_LABEL[stage]}</div>
      <div className="flex min-h-0 flex-1 flex-col justify-around gap-2">
        {matches.map((match) => (
          <KnockoutNode
            key={match.espn_id}
            match={match}
            live={live}
            onOpen={onOpen}
            final={stage === "final"}
          />
        ))}
      </div>
    </section>
  );
}

const Connector = () => (
  <div aria-hidden className="hidden items-center md:flex">
    <span className="h-px w-full bg-[var(--line-strong)]" />
  </div>
);

export function KnockoutMap({ matches, live, onOpen }: KnockoutMapProps) {
  const stages = STAGES.map((stage) => ({
    stage,
    matches: stageMatches(matches, stage),
  }));

  if (stages.every(({ matches: rows }) => rows.length === 0)) {
    return (
      <div className="mono flex h-full items-center justify-center p-6 text-[12px] text-[var(--ink-faint)]">
        淘汰赛对阵尚未生成
      </div>
    );
  }

  return (
    <div className="grid h-full grid-cols-1 gap-3 p-3 md:grid-cols-[minmax(0,1.25fr)_20px_minmax(0,1fr)_20px_minmax(0,.9fr)] md:gap-2">
      <StageColumn {...stages[0]} live={live} onOpen={onOpen} />
      <Connector />
      <StageColumn {...stages[1]} live={live} onOpen={onOpen} />
      <Connector />
      <StageColumn {...stages[2]} live={live} onOpen={onOpen} />
    </div>
  );
}
