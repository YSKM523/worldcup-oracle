import { describe, expect, it } from "vitest";
import { buildMatchScripts, buildScoreDistribution, buildValueRows } from "./forecastAnalytics";

describe("buildScoreDistribution", () => {
  it("normalizes the 0-3 grid plus 4+ tail to one", () => {
    const result = buildScoreDistribution(1.02, 1.67);

    expect(result).not.toBeNull();
    expect(result!.cells.reduce((sum, cell) => sum + cell.p, 0) + result!.tail).toBeCloseTo(1);
    expect(result!.cells.find((cell) => cell.home === 1 && cell.away === 1)?.label).toBe("1-1");
  });

  it("returns null without finite positive xG", () => {
    expect(buildScoreDistribution(0, 1.2)).toBeNull();
    expect(buildScoreDistribution(Number.NaN, 1.2)).toBeNull();
  });
});

describe("buildMatchScripts", () => {
  it("partitions the score distribution into home draw and away paths", () => {
    const distribution = buildScoreDistribution(1.02, 1.67)!;
    const scripts = buildMatchScripts(distribution);

    expect(scripts.reduce((sum, script) => sum + script.p, 0)).toBeCloseTo(1);
    expect(scripts.map((script) => script.side)).toEqual(["home", "draw", "away"]);
  });
});

describe("buildValueRows", () => {
  it("compares AI with independently normalized market prices", () => {
    const rows = buildValueRows(
      { home: .23, draw: .30, away: .47 },
      { home: .24, draw: .26, away: .51 },
    );

    expect(rows.find((row) => row.side === "draw")?.edge).toBeCloseTo(.30 - (.26 / 1.01));
    expect(rows.find((row) => row.side === "draw")?.fairOdds).toBeCloseTo(1 / .30);
  });

  it("marks market-derived fields unavailable when the market is missing", () => {
    const rows = buildValueRows({ home: .23, draw: .30, away: .47 }, null);

    for (const row of rows) {
      expect(row.market).toBeNull();
      expect(row.edge).toBeNull();
      expect(row.marketOdds).toBeNull();
      expect(row.halfKelly).toBeNull();
      expect(row.direction).toBe("FAIR");
    }
  });
});
