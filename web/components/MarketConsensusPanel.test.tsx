import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KalshiMarketState } from "../lib/types";
import type { MatchMarketState, OutcomeBook } from "../lib/useMatchMarket";
import { MarketConsensusPanel } from "./MarketConsensusPanel";

const book = (mid: number): OutcomeBook => ({
  bids: [], asks: [], bestBid: mid - 0.01, bestAsk: mid + 0.01, mid, bidUsd: 0, askUsd: 0,
});

const polymarket = (updatedAt: number, mids = [0.5, 0.3, 0.2]): MatchMarketState => ({
  status: "live",
  updatedAt,
  wsUp: true,
  books: { home: book(mids[0]), draw: book(mids[1]), away: book(mids[2]) },
  trades: [], curves: {}, volume: 100, spike: null, liveTradeCount: 0,
});

const unavailableKalshi = (): KalshiMarketState => ({
  status: "unavailable", source: "kalshi-rest", eventTicker: null, updatedAt: Date.now(), outcomes: {}, stale: true, failures: 0,
});

const completeKalshi = (updatedAt: number): KalshiMarketState => ({
  status: "live",
  source: "kalshi-rest",
  eventTicker: "COMPLETE",
  updatedAt,
  outcomes: {
    home: { ticker: "H", bid: 0.49, ask: 0.51, mid: 0.5, last: 0.5, volume: 10 },
    draw: { ticker: "D", bid: 0.29, ask: 0.31, mid: 0.3, last: 0.3, volume: 10 },
    away: { ticker: "A", bid: 0.19, ask: 0.21, mid: 0.2, last: 0.2, volume: 10 },
  },
  stale: false,
  failures: 0,
});

const incompleteKalshi = (): KalshiMarketState => ({
  status: "live",
  source: "kalshi-rest",
  eventTicker: "INCOMPLETE",
  updatedAt: Date.now(),
  outcomes: {
    home: { ticker: "H", bid: 0.49, ask: 0.51, mid: 0.5, last: 0.5, volume: 10 },
    draw: { ticker: "D", bid: 0.29, ask: 0.31, mid: null, last: 0.3, volume: 10 },
  },
  stale: false,
  failures: 0,
});

describe("MarketConsensusPanel", () => {
  let renderer: ReactTestRenderer | null = null;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-10T18:00:00Z"));
    vi.spyOn(console, "error").mockImplementation((message, ...args) => {
      if (String(message).includes("react-test-renderer is deprecated")) return;
      console.warn(message, ...args);
    });
  });

  afterEach(async () => {
    if (renderer) await act(async () => renderer?.unmount());
    renderer = null;
    vi.restoreAllMocks();
    vi.useRealTimers();
    delete (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  const renderPanel = async (poly: MatchMarketState, kalshi: KalshiMarketState, polymarketAvailable = true) => {
    await act(async () => {
      renderer = create(createElement(MarketConsensusPanel, { home: "Spain", away: "Belgium", polymarket: poly, kalshi, polymarketAvailable }));
    });
  };

  const state = () => renderer!.root.find((node) => node.props["data-market-consensus-state"] != null).props["data-market-consensus-state"];
  const text = () => JSON.stringify(renderer!.toJSON());

  it("rerenders at each source expiry without new props", async () => {
    await renderPanel(polymarket(Date.now() - 5_000), completeKalshi(Date.now()));
    expect(state()).toBe("dual");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_002);
    });
    expect(state()).toBe("single");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(state()).toBe("unavailable");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("labels an incomplete live Kalshi line unavailable rather than stale", async () => {
    await renderPanel(polymarket(Date.now()), incompleteKalshi());
    expect(text()).toContain("KAL UNAVAILABLE");
    expect(text()).not.toContain("KAL STALE");
  });

  it("rejects mids outside the open probability interval", async () => {
    await renderPanel(polymarket(Date.now(), [1, 0.3, 0.2]), unavailableKalshi());
    expect(state()).toBe("unavailable");
  });

  it("labels each compact Kalshi quote column", async () => {
    await renderPanel(polymarket(Date.now()), incompleteKalshi());
    const labels = renderer!.root.findAll((node) => node.type === "b").flatMap((node) => node.children);
    expect(labels).toEqual(expect.arrayContaining(["H", "D", "A"]));
  });

  it("labels Polymarket unavailable while retaining a live Kalshi single source", async () => {
    const missingPoly = { ...polymarket(Date.now()), status: "error" as const, updatedAt: null, books: {} };
    await renderPanel(missingPoly, completeKalshi(Date.now()), false);
    expect(state()).toBe("single");
    expect(text()).toContain("1/2 SINGLE SOURCE");
    expect(text()).toContain("KAL LIVE");
    expect(text()).toContain("PM");
    expect(text()).toContain("UNAVAILABLE");
    expect(text()).toContain("该场暂无 Polymarket 微观结构");
  });
});
