"use client";

import { useEffect, useRef, useState } from "react";
import { inplayProbs, parseClock } from "@/lib/inplay";
import type { LiveEntry, Pred } from "@/lib/types";
import type { CurvePoint, OutcomeSide } from "@/lib/useMatchMarket";

export type InplayCurves = Partial<Record<OutcomeSide, CurvePoint[]>>;

interface UseInplayCurveParams {
  pred?: Pred;
  liveEntry?: LiveEntry;
  totalMinutes?: 90 | 120;
}

const SAMPLE_MS = 30_000;

export function useInplayCurve({
  pred,
  liveEntry,
  totalMinutes = 90,
}: UseInplayCurveParams): InplayCurves {
  const [curves, setCurves] = useState<InplayCurves>({});
  const latest = useRef<UseInplayCurveParams>({ pred, liveEntry, totalMinutes });
  latest.current = { pred, liveEntry, totalMinutes };

  useEffect(() => {
    setCurves({});
    if (!pred || liveEntry?.state !== "in") return;

    const sample = () => {
      const p = latest.current.pred;
      const live = latest.current.liveEntry;
      const tm = latest.current.totalMinutes ?? 90;
      if (!p || live?.state !== "in") return;
      const minute = parseClock(live.clock);
      if (minute == null) return;

      const probs = inplayProbs({
        pHome: p.p_home,
        pDraw: p.p_draw,
        pAway: p.p_away,
        xgHome: p.scoreline.xg_home,
        xgAway: p.scoreline.xg_away,
        homeScore: live.home_score,
        awayScore: live.away_score,
        minute,
        totalMinutes: tm,
      });
      const t = Math.floor(Date.now() / 1000);
      setCurves((prev) => ({
        home: [...(prev.home ?? []), { t, p: probs.home }],
        draw: [...(prev.draw ?? []), { t, p: probs.draw }],
        away: [...(prev.away ?? []), { t, p: probs.away }],
      }));
    };

    sample();
    const id = setInterval(sample, SAMPLE_MS);
    return () => clearInterval(id);
  }, [
    pred,
    liveEntry?.state,
    totalMinutes,
  ]);

  return curves;
}
