import React from "react";
import { act, create } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MatchTelemetry } from "./MatchTelemetry";
import type { KalshiMarketState, Match, PolyLive, WeatherData } from "../lib/types";

const match = {
  espn_id: "401", kickoff_utc: "2026-07-10T18:01:05Z", stage: "group", group: "B",
  venue: "Oracle Park", city: "Seattle", home: "Spain", away: "Belgium", tbd: false,
  completed: false, status: null, home_score: null, away_score: null, winner: null,
} satisfies Match;

const poly = {
  champion: {}, matches: { "1783706465": { home: .4, draw: .3, away: .3, src: "ws", ts: Date.parse("2026-07-10T17:59:55Z") } },
  championFresh: true, updatedAt: Date.parse("2026-07-10T17:59:55Z"), wsConnected: true,
} satisfies PolyLive;

const kalshi = (overrides: Partial<KalshiMarketState> = {}): KalshiMarketState => ({
  status: "live", source: "kalshi-rest", eventTicker: "KXWC", updatedAt: Date.parse("2026-07-10T17:59:55Z"),
  outcomes: {}, stale: false, failures: 0, ...overrides,
});

const render = (props: Partial<React.ComponentProps<typeof MatchTelemetry>> = {}) => {
  let root!: ReturnType<typeof create>;
  act(() => { root = create(<MatchTelemetry match={match} weather={null} poly={poly} kalshi={kalshi()} {...props} />); });
  return root;
};
const text = (root: ReturnType<typeof create>) => JSON.stringify(root.toJSON());

afterEach(() => { vi.useRealTimers(); });

describe("MatchTelemetry", () => {
  it("ticks every second and clears the interval on unmount", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-07-10T18:00:00Z"));
    const root = render();
    expect(text(root)).toContain("01:05");
    expect(vi.getTimerCount()).toBe(1);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(text(root)).toContain("01:04");
    act(() => root.unmount());
    expect(vi.getTimerCount()).toBe(0);
  });

  it("formats kickoff explicitly in UTC even under a non-UTC process timezone", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-07-10T18:00:00Z"));
    const previous = process.env.TZ; process.env.TZ = "America/Los_Angeles";
    let root: ReturnType<typeof create> | undefined;
    try {
      root = render();
      expect(text(root)).toContain("07/10 18:01");
      expect(text(root)).toContain(" UTC");
      expect(text(root)).not.toContain("07/10 11:01");
    } finally {
      if (root) act(() => root!.unmount());
      process.env.TZ = previous;
    }
  });

  it("shows a reached state instead of an endless zero countdown", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-07-10T18:02:00Z"));
    const root = render();
    expect(text(root)).toContain("KICKOFF REACHED");
    expect(text(root)).toContain("等待实时源");
    expect(text(root)).not.toContain("T−00:00:00");
    expect(text(root)).not.toContain("等待开赛");
    act(() => root.unmount());
  });

  it("uses match-keyed weather and Polymarket snapshot", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-07-10T18:00:00Z"));
    const weather = { matches: { "401": { temp_c: 22, humidity_pct: 61 } } } as unknown as WeatherData;
    const root = render({ weather });
    expect(text(root)).toContain("22°C"); expect(text(root)).toContain("61%"); expect(text(root)).toContain("POLY LIVE");
    act(() => root.unmount());
  });

  it.each([
    [kalshi(), "KAL LIVE"],
    [kalshi({ stale: true }), "KAL STALE"],
    [kalshi({ status: "unavailable" }), "KAL UNAVAILABLE"],
  ] as const)("renders each Kalshi health state", (state, label) => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-07-10T18:00:00Z"));
    const root = render({ kalshi: state }); expect(text(root)).toContain(label); act(() => root.unmount());
  });
});
