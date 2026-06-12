"use client";

import { useEffect, useMemo, useState } from "react";
import type { Match, PolyLive, PolyMatchOdds } from "./types";
import { canonicalTeam, kickoffEpoch } from "./wc";

const GAMMA = "https://gamma-api.polymarket.com/events";
const CHAMPION_SLUG = "world-cup-winner";
const POLL_MS = 5 * 60e3; // Polymarket CDN caches 5 min; no point polling faster
// Live window around now: just-finished through the next ~30h of fixtures.
const WINDOW_BEFORE_MS = 3 * 3600e3;
const WINDOW_AFTER_MS = 30 * 3600e3;

interface GammaMarket {
  question?: string;
  outcomePrices?: string | string[];
}
interface GammaEvent {
  title?: string;
  endDate?: string;
  markets?: GammaMarket[];
}

const yesPrice = (m: GammaMarket): number | null => {
  const raw = m.outcomePrices ?? "[]";
  const arr = typeof raw === "string" ? (JSON.parse(raw) as string[]) : raw;
  const p = Number(arr?.[0]);
  return Number.isFinite(p) ? p : null;
};

function parseChampion(ev: GammaEvent): Record<string, number> {
  const out: Record<string, number> = {};
  for (const m of ev.markets ?? []) {
    let name = m.question ?? "";
    name = name.replace(/^Will\s+/i, "");
    name = name.replace(/\s+win the .*$/i, "").trim();
    const price = yesPrice(m);
    if (name && price != null) out[canonicalTeam(name)] = price;
  }
  return out;
}

function parseMoneyline(ev: GammaEvent): { key: string; odds: PolyMatchOdds } | null {
  const title = ev.title ?? "";
  if (!title.includes(" vs. ") || !ev.endDate || (ev.markets?.length ?? 0) !== 3) return null;
  const [home, away] = title.split(" vs. ", 2).map((s) => s.trim().toLowerCase());
  let h: number | null = null;
  let d: number | null = null;
  let a: number | null = null;
  for (const m of ev.markets ?? []) {
    const q = (m.question ?? "").toLowerCase();
    const p = yesPrice(m);
    if (p == null) continue;
    if (q.includes("draw")) d = p;
    else if (q.includes(home)) h = p;
    else if (q.includes(away)) a = p;
  }
  if (h == null || d == null || a == null) return null;
  return { key: kickoffEpoch(ev.endDate), odds: { home: h, draw: d, away: a } };
}

/**
 * Client-side live Polymarket odds (CORS-open Gamma API, like the ESPN hook).
 * Polls the champion market plus the slugs of fixtures in the live window.
 * Falls back silently to the data.json snapshot on any failure.
 */
export function usePolymarket(matches: Match[]): PolyLive {
  const slugs = useMemo(() => {
    const now = Date.now();
    const lo = now - WINDOW_BEFORE_MS;
    const hi = now + WINDOW_AFTER_MS;
    const list: string[] = [];
    for (const m of matches) {
      if (!m.market?.slug) continue;
      const t = new Date(m.kickoff_utc).getTime();
      if (t >= lo && t <= hi) list.push(m.market.slug);
    }
    return Array.from(new Set(list));
  }, [matches]);
  const slugKey = slugs.join(",");

  const [live, setLive] = useState<PolyLive>({
    champion: {},
    matches: {},
    championFresh: false,
    updatedAt: null,
  });

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;

    const getEvents = (params: string) =>
      fetch(`${GAMMA}?${params}`)
        .then((r) => r.json() as Promise<GammaEvent[]>)
        .catch(() => null);

    async function refresh() {
      const matchSlugs = slugKey ? slugKey.split(",") : [];
      const [champRes, ...matchRes] = await Promise.all([
        getEvents(`slug=${CHAMPION_SLUG}`),
        ...matchSlugs.map((s) => getEvents(`slug=${encodeURIComponent(s)}`)),
      ]);

      const next: PolyLive = {
        champion: {},
        matches: {},
        championFresh: false,
        updatedAt: Date.now(),
      };
      if (champRes?.[0]) {
        next.champion = parseChampion(champRes[0]);
        next.championFresh = Object.keys(next.champion).length > 0;
      }
      for (const res of matchRes) {
        const parsed = res?.[0] ? parseMoneyline(res[0]) : null;
        if (parsed) next.matches[parsed.key] = parsed.odds;
      }

      if (!cancelled && (next.championFresh || Object.keys(next.matches).length)) {
        setLive(next);
      }
      if (!cancelled) timer = setTimeout(refresh, POLL_MS);
    }

    refresh();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [slugKey]);

  return live;
}
