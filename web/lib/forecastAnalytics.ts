import type { MarketSide } from "./types";

export type ScoreCell = { home: number; away: number; label: string; p: number; side: MarketSide };
export type ScoreDistribution = { cells: ScoreCell[]; tail: number; tailBySide: Record<MarketSide, number>; mode: ScoreCell };
export type MatchScript = { side: MarketSide; p: number; leadingScores: ScoreCell[] };
export type ValueRow = { side: MarketSide; ai: number; market: number | null; edge: number | null; fairOdds: number; marketOdds: number | null; direction: "BUY" | "SELL" | "FAIR"; halfKelly: number | null };

const sides: MarketSide[] = ["home", "draw", "away"];
const factorial = (value: number) => Array.from({ length: value }, (_, index) => index + 1).reduce((product, item) => product * item, 1);
const poisson = (lambda: number, goals: number) => Math.exp(-lambda) * (lambda ** goals) / factorial(goals);

export function buildScoreDistribution(xgHome: number, xgAway: number): ScoreDistribution | null {
  if (!Number.isFinite(xgHome) || !Number.isFinite(xgAway) || xgHome <= 0 || xgAway <= 0) return null;

  const full: ScoreCell[] = [];
  for (let home = 0; home <= 10; home++) for (let away = 0; away <= 10; away++) {
    full.push({
      home,
      away,
      label: `${home}-${away}`,
      p: poisson(xgHome, home) * poisson(xgAway, away),
      side: home > away ? "home" : home === away ? "draw" : "away",
    });
  }

  const total = full.reduce((sum, cell) => sum + cell.p, 0);
  const normalized = full.map((cell) => ({ ...cell, p: cell.p / total }));
  const cells = normalized.filter((cell) => cell.home <= 3 && cell.away <= 3);
  const tailCells = normalized.filter((cell) => cell.home > 3 || cell.away > 3);
  const tailBySide = Object.fromEntries(
    sides.map((side) => [side, tailCells.filter((cell) => cell.side === side).reduce((sum, cell) => sum + cell.p, 0)]),
  ) as Record<MarketSide, number>;

  return {
    cells,
    tail: tailCells.reduce((sum, cell) => sum + cell.p, 0),
    tailBySide,
    mode: normalized.reduce((best, cell) => cell.p > best.p ? cell : best),
  };
}

export function buildMatchScripts(distribution: ScoreDistribution): MatchScript[] {
  return sides.map((side) => {
    const matching = distribution.cells.filter((cell) => cell.side === side).sort((a, b) => b.p - a.p);
    return {
      side,
      p: matching.reduce((sum, cell) => sum + cell.p, 0) + distribution.tailBySide[side],
      leadingScores: matching.slice(0, 3),
    };
  });
}

export function buildValueRows(ai: Record<MarketSide, number>, market: Record<MarketSide, number> | null): ValueRow[] {
  const marketSum = market ? market.home + market.draw + market.away : 0;

  return sides.map((side) => {
    const normalized = market && marketSum > 0 ? market[side] / marketSum : null;
    const edge = normalized == null ? null : ai[side] - normalized;
    const halfKelly = normalized == null ? null : Math.max(0, ((ai[side] * (1 / normalized)) - 1) / ((1 / normalized) - 1) / 2);

    return {
      side,
      ai: ai[side],
      market: normalized,
      edge,
      fairOdds: 1 / ai[side],
      marketOdds: normalized ? 1 / normalized : null,
      direction: edge == null || Math.abs(edge) < .005 ? "FAIR" : edge > 0 ? "BUY" : "SELL",
      halfKelly,
    };
  });
}
