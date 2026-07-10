import { describe, expect, it } from "vitest";
import { buildMarketConsensus, normalizeThreeWay, pollDelay } from "./marketConsensus";

describe("normalizeThreeWay", () => {
  it("normalizes W/D/L to one", () => {
    const result = normalizeThreeWay({ home: 0.61, draw: 0.25, away: 0.17 });
    expect(result.home + result.draw + result.away).toBeCloseTo(1);
  });
});

describe("pollDelay", () => {
  it("uses one second normally and bounded failure backoff", () => {
    expect([0, 1, 2, 3, 8].map(pollDelay)).toEqual([1000, 2000, 5000, 10000, 10000]);
  });
});

describe("buildMarketConsensus", () => {
  const poly = { home: 0.61, draw: 0.25, away: 0.17, updatedAt: 10_000 };
  const kalshi = { home: 0.595, draw: 0.245, away: 0.165, updatedAt: 10_000 };

  it("averages normalized complete fresh sources equally", () => {
    const result = buildMarketConsensus(poly, kalshi, 12_000);
    expect(result.status).toBe("dual");
    expect(result.sources).toBe(2);
    expect(result.consensus.home + result.consensus.draw + result.consensus.away).toBeCloseTo(1);
  });

  it("excludes a source older than fifteen seconds", () => {
    const result = buildMarketConsensus(poly, { ...kalshi, updatedAt: 1_000 }, 20_000);
    expect(result).toMatchObject({ status: "single", sources: 1, sourceNames: ["polymarket"] });
  });

  it("returns unavailable for incomplete sources", () => {
    const result = buildMarketConsensus(null, null, 20_000);
    expect(result).toMatchObject({ status: "unavailable", sources: 0 });
  });

  it("classifies five and ten point divergence", () => {
    const result = buildMarketConsensus(
      { home: 0.70, draw: 0.20, away: 0.10, updatedAt: 10_000 },
      { home: 0.54, draw: 0.26, away: 0.20, updatedAt: 10_000 },
      11_000,
    );
    expect(result.severity.home).toBe("critical");
    expect(result.severity.draw).toBe("warning");
  });
});
