"use client";

import { useEffect, useState } from "react";

const SUMMARY_URL =
  "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event=";

export type MatchState = "pre" | "in" | "post";

/** Per-team ESPN boxscore stats, keyed by ESPN stat name → numeric value. */
export interface MatchStats {
  state: MatchState;
  /** e.g. "45'+2" (live clock) or "FT" (post). */
  detail: string;
  home: Record<string, number>;
  away: Record<string, number>;
}

function parseSummary(d: unknown): MatchStats | null {
  const doc = d as {
    header?: { competitions?: { status?: { type?: { state?: string; detail?: string; shortDetail?: string } }; competitors?: { homeAway?: string; team?: { id?: string } }[] }[] };
    boxscore?: { teams?: { team?: { id?: string }; statistics?: { name?: string; displayValue?: string }[] }[] };
  };
  const comp = doc.header?.competitions?.[0];
  const status = comp?.status?.type;
  const state = (status?.state ?? "pre") as MatchState;
  const detail = status?.detail ?? status?.shortDetail ?? "";

  // map ESPN team.id → home/away
  const idSide: Record<string, "home" | "away"> = {};
  for (const c of comp?.competitors ?? []) {
    if (c.team?.id && (c.homeAway === "home" || c.homeAway === "away")) {
      idSide[c.team.id] = c.homeAway;
    }
  }

  const home: Record<string, number> = {};
  const away: Record<string, number> = {};
  const teams = doc.boxscore?.teams ?? [];
  for (let i = 0; i < teams.length; i++) {
    const t = teams[i];
    const side = (t.team?.id && idSide[t.team.id]) || (i === 0 ? "home" : "away");
    const bucket = side === "home" ? home : away;
    for (const s of t.statistics ?? []) {
      if (!s.name) continue;
      const v = parseFloat(s.displayValue ?? "");
      if (Number.isFinite(v)) bucket[s.name] = v;
    }
  }

  if (!Object.keys(home).length && !Object.keys(away).length) return null;
  return { state, detail, home, away };
}

/** Client-side live/final match stats from ESPN (CORS-open). Polls while in-play. */
export function useMatchStats(espnId: string | null, enabled: boolean): MatchStats | null {
  const [stats, setStats] = useState<MatchStats | null>(null);

  useEffect(() => {
    if (!espnId || !enabled) {
      setStats(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function refresh() {
      try {
        const r = await fetch(`${SUMMARY_URL}${espnId}`);
        const j = await r.json();
        if (cancelled) return;
        const parsed = parseSummary(j);
        setStats(parsed);
        // keep polling only while the match is in play
        if (parsed?.state === "in") timer = setTimeout(refresh, 25_000);
      } catch {
        /* transient — keep last snapshot */
      }
    }
    refresh();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [espnId, enabled]);

  return stats;
}
