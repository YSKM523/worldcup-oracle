import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KalshiMarketState, KalshiQuoteResponse } from "./types";
import { useKalshiMarket } from "./useKalshiMarket";
import { MarketConsensusPanel } from "../components/MarketConsensusPanel";
import type { MatchMarketState, OutcomeBook } from "./useMatchMarket";

type Input = Parameters<typeof useKalshiMarket>[0];

const INPUT_A: Input = { home: "Argentina", away: "Algeria", kickoffUtc: "2026-07-10T20:00:00Z", enabled: true };
const INPUT_B: Input = { home: "Brazil", away: "Belgium", kickoffUtc: "2026-07-11T20:00:00Z", enabled: true };

const liveQuote = (ticker: string): KalshiQuoteResponse => ({
  status: "live",
  source: "kalshi-rest",
  eventTicker: `EVENT-${ticker}`,
  updatedAt: Date.now(),
  outcomes: {
    home: { ticker: `${ticker}-HOME`, bid: 0.4, ask: 0.42, mid: 0.41, last: 0.4, volume: 100 },
    draw: { ticker: `${ticker}-DRAW`, bid: 0.2, ask: 0.22, mid: 0.21, last: 0.2, volume: 50 },
    away: { ticker: `${ticker}-AWAY`, bid: 0.36, ask: 0.38, mid: 0.37, last: 0.36, volume: 80 },
  },
});

const response = (body: KalshiQuoteResponse) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "content-type": "application/json" },
});

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

describe("useKalshiMarket", () => {
  let renderer: ReactTestRenderer | null = null;
  let states: KalshiMarketState[];

  const Probe = ({ input }: { input: Input }) => {
    states.push(useKalshiMarket(input));
    return null;
  };

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-10T18:00:00Z"));
    vi.spyOn(console, "error").mockImplementation((message, ...args) => {
      if (String(message).includes("react-test-renderer is deprecated")) return;
      console.warn(message, ...args);
    });
    states = [];
  });

  afterEach(async () => {
    if (renderer) await act(async () => renderer?.unmount());
    renderer = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
    delete (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  it("resets outcomes before polling a new match identity", async () => {
    const nextMatch = deferred<Response>();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(liveQuote("A")))
      .mockReturnValueOnce(nextMatch.promise);
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      renderer = create(createElement(Probe, { input: INPUT_A }));
    });
    expect(states.at(-1)).toMatchObject({ status: "live", outcomes: { home: { ticker: "A-HOME" } } });

    await act(async () => {
      renderer?.update(createElement(Probe, { input: INPUT_B }));
    });
    expect(states.at(-1)).toMatchObject({ status: "unavailable", stale: true, outcomes: {} });

    await act(async () => nextMatch.reject(new Error("offline")));
    expect(states.at(-1)).toMatchObject({ status: "error", outcomes: {} });
  });

  it("marks a live quote stale while the next fetch is still pending", async () => {
    const pending = deferred<Response>();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(liveQuote("A")))
      .mockReturnValueOnce(pending.promise);
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      renderer = create(createElement(Probe, { input: INPUT_A }));
    });
    expect(states.at(-1)?.stale).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(16_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(states.at(-1)).toMatchObject({ status: "live", stale: true });
  });

  it("retains the last live outcomes after an error for the same match", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(liveQuote("A")))
      .mockRejectedValueOnce(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      renderer = create(createElement(Probe, { input: INPUT_A }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });

    expect(states.at(-1)).toMatchObject({
      status: "live",
      stale: false,
      failures: 1,
      outcomes: { home: { ticker: "A-HOME" } },
    });
  });

  it("keeps a transiently failing live quote in dual consensus until freshness expires", async () => {
    const book = (mid: number): OutcomeBook => ({
      bids: [], asks: [], bestBid: mid - 0.01, bestAsk: mid + 0.01, mid, bidUsd: 0, askUsd: 0,
    });
    const poly: MatchMarketState = {
      status: "live", updatedAt: Date.now() + 60_000, wsUp: true,
      books: { home: book(0.5), draw: book(0.3), away: book(0.2) },
      trades: [], curves: {}, volume: 100, spike: null, liveTradeCount: 0,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(liveQuote("A")))
      .mockRejectedValueOnce(new Error("offline"))
      .mockImplementation(() => new Promise<Response>(() => undefined));
    vi.stubGlobal("fetch", fetchMock);

    const ConsensusProbe = ({ input }: { input: Input }) => {
      const kalshi = useKalshiMarket(input);
      states.push(kalshi);
      return createElement(MarketConsensusPanel, { home: input.home, away: input.away, polymarket: poly, kalshi });
    };
    await act(async () => {
      renderer = create(createElement(ConsensusProbe, { input: INPUT_A }));
    });
    const consensusState = () => renderer!.root.find((node) => node.props["data-market-consensus-state"] != null).props["data-market-consensus-state"];
    expect(consensusState()).toBe("dual");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(states.at(-1)).toMatchObject({ status: "live", stale: false, failures: 1, outcomes: { away: { ticker: "A-AWAY" } } });
    expect(consensusState()).toBe("dual");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_002);
    });
    expect(states.at(-1)).toMatchObject({ status: "live", stale: true, failures: 1 });
    expect(consensusState()).toBe("single");
    expect(JSON.stringify(renderer!.toJSON())).toContain("KAL STALE");
  });

  it("aborts a pending request and clears every timer on cleanup", async () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      return new Promise<Response>(() => undefined);
    }));

    await act(async () => {
      renderer = create(createElement(Probe, { input: INPUT_A }));
    });
    expect(signal?.aborted).toBe(false);

    await act(async () => renderer?.unmount());
    renderer = null;
    expect(signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
