"use client";

import { useEffect, useState } from "react";
import type { LiveMap } from "./types";

const ESPN_URL =
  "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=";

interface EspnCompetitor {
  homeAway?: string;
  score?: string;
}
interface EspnEvent {
  id: string | number;
  status: { type: { state: "pre" | "in" | "post"; completed: boolean }; displayClock?: string };
  competitions?: { competitors: EspnCompetitor[] }[];
}

/** Client-side live scores from ESPN (CORS-open), polled while matches run. */
export function useLive(): LiveMap {
  const [live, setLive] = useState<LiveMap>({});

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;

    async function refresh() {
      const dates = [0, -1].map((off) =>
        new Date(Date.now() + off * 86400e3).toISOString().slice(0, 10).replace(/-/g, "")
      );
      let anyLive = false;
      const next: LiveMap = {};
      try {
        const results = await Promise.all(
          dates.map((d) =>
            fetch(ESPN_URL + d)
              .then((r) => r.json() as Promise<{ events?: EspnEvent[] }>)
              .catch(() => null)
          )
        );
        for (const res of results) {
          for (const ev of res?.events ?? []) {
            const comp = ev.competitions?.[0];
            if (!comp) continue;
            const home = comp.competitors.find((c) => c.homeAway === "home") ?? comp.competitors[0];
            const away = comp.competitors.find((c) => c.homeAway === "away") ?? comp.competitors[1];
            const state = ev.status.type.state;
            next[String(ev.id)] = {
              state,
              completed: !!ev.status.type.completed,
              home_score: Number(home?.score ?? 0),
              away_score: Number(away?.score ?? 0),
              clock: state === "in" ? (ev.status.displayClock ?? "") : "",
            };
            if (state === "in") anyLive = true;
          }
        }
        if (!cancelled && Object.keys(next).length) setLive(next);
      } catch {
        /* offline — keep static data */
      }
      if (!cancelled) timer = setTimeout(refresh, anyLive ? 60e3 : 5 * 60e3);
    }

    refresh();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return live;
}
