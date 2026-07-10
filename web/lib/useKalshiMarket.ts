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
  const [state, setState] = useState<KalshiMarketState>(INIT);

  useEffect(() => {
    if (!input.enabled) {
      setState(INIT);
      return;
    }

    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let activeController: AbortController | null = null;
    let failures = 0;
    const url = `/api/kalshi/match?home=${encodeURIComponent(input.home)}&away=${encodeURIComponent(input.away)}&kickoff=${encodeURIComponent(input.kickoffUtc)}`;

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
        setState({
          ...quote,
          stale: Date.now() - quote.updatedAt > 15_000,
          failures,
        });
      } catch (error) {
        if (closed || (error instanceof DOMException && error.name === "AbortError")) return;
        failures += 1;
        setState((previous) => ({
          ...previous,
          status: "error",
          stale: Date.now() - previous.updatedAt > 15_000,
          failures,
          reason: error instanceof Error ? error.message : "request-failed",
        }));
      }
      if (!closed) timer = setTimeout(poll, pollDelay(failures));
    };

    void poll();
    return () => {
      closed = true;
      activeController?.abort();
      clearTimeout(timer);
    };
  }, [input.home, input.away, input.kickoffUtc, input.enabled]);

  return state;
}
