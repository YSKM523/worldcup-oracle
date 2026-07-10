"use client";

import { useEffect, useState } from "react";
import { pollDelay } from "./marketConsensus";
import type { KalshiMarketState, KalshiQuoteResponse } from "./types";

const INIT: KalshiMarketState = {
  status: "unavailable",
  source: "kalshi-rest",
  eventTicker: null,
  updatedAt: 0,
  outcomes: {},
  stale: true,
  failures: 0,
};

export function useKalshiMarket(input: { home: string; away: string; kickoffUtc: string; enabled: boolean }): KalshiMarketState {
  const identity = input.enabled ? JSON.stringify([input.home, input.away, input.kickoffUtc]) : null;
  const [snapshot, setSnapshot] = useState<{ identity: string | null; value: KalshiMarketState }>(() => ({ identity, value: INIT }));
  let current = snapshot;
  if (snapshot.identity !== identity) {
    current = { identity, value: INIT };
    setSnapshot(current);
  }

  useEffect(() => {
    if (!identity) return;

    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let freshnessTimer: ReturnType<typeof setTimeout> | undefined;
    let activeController: AbortController | null = null;
    let failures = 0;
    const url = `/api/kalshi/match?home=${encodeURIComponent(input.home)}&away=${encodeURIComponent(input.away)}&kickoff=${encodeURIComponent(input.kickoffUtc)}`;

    const scheduleFreshness = (updatedAt: number) => {
      clearTimeout(freshnessTimer);
      const remaining = updatedAt + 15_001 - Date.now();
      if (remaining <= 0) return;
      freshnessTimer = setTimeout(() => {
        setSnapshot((previous) => previous.identity === identity && previous.value.updatedAt === updatedAt
          ? { identity, value: { ...previous.value, stale: true } }
          : previous);
      }, remaining);
    };

    const poll = async () => {
      activeController = new AbortController();
      try {
        const response = await fetch(url, { signal: activeController.signal });
        const quote = await response.json() as KalshiQuoteResponse;
        if (closed) return;
        if (!response.ok || quote.status === "error") {
          throw new Error(quote.reason ?? `kalshi-${response.status}`);
        }
        failures = 0;
        const stale = Date.now() - quote.updatedAt > 15_000;
        setSnapshot({ identity, value: { ...quote, stale, failures } });
        if (!stale) scheduleFreshness(quote.updatedAt);
      } catch (error) {
        if (closed || (error instanceof DOMException && error.name === "AbortError")) return;
        failures += 1;
        setSnapshot((previous) => previous.identity === identity ? {
          identity,
          value: {
            ...previous.value,
            status: previous.value.status === "live" ? "live" : "error",
            stale: Date.now() - previous.value.updatedAt > 15_000,
            failures,
            reason: error instanceof Error ? error.message : "request-failed",
          },
        } : previous);
      }
      if (!closed) timer = setTimeout(poll, pollDelay(failures));
    };

    void poll();
    return () => {
      closed = true;
      activeController?.abort();
      clearTimeout(timer);
      clearTimeout(freshnessTimer);
    };
  }, [input.home, input.away, input.kickoffUtc, identity]);

  return current.value;
}
