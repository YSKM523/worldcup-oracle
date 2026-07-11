import type { MarketSide, Match, PolyLive } from "./types";
import { kickoffEpoch } from "./wc";

export type ScoreCell = { home: number; away: number; label: string; p: number; side: MarketSide };
export type ScoreDistribution = {
  cells: ScoreCell[];
  tail: number;
  tailBySide: Record<MarketSide, number>;
  /** P(total goals ≥ 3) mass per outcome region — kept per side so conditioning can rescale it. */
  over25BySide: Record<MarketSide, number>;
  /** P(both teams score) mass per outcome region. */
  bttsBySide: Record<MarketSide, number>;
  mode: ScoreCell;
};
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

  if (full.some((cell) => !Number.isFinite(cell.p) || cell.p <= 0)) return null;
  const total = full.reduce((sum, cell) => sum + cell.p, 0);
  if (!Number.isFinite(total) || total <= 0) return null;
  const normalized = full.map((cell) => ({ ...cell, p: cell.p / total }));
  if (normalized.some((cell) => !Number.isFinite(cell.p) || cell.p <= 0)) return null;
  const cells = normalized.filter((cell) => cell.home <= 3 && cell.away <= 3);
  const tailCells = normalized.filter((cell) => cell.home > 3 || cell.away > 3);
  const sideMass = (pool: ScoreCell[]) => Object.fromEntries(
    sides.map((side) => [side, pool.filter((cell) => cell.side === side).reduce((sum, cell) => sum + cell.p, 0)]),
  ) as Record<MarketSide, number>;

  return {
    cells,
    tail: tailCells.reduce((sum, cell) => sum + cell.p, 0),
    tailBySide: sideMass(tailCells),
    over25BySide: sideMass(normalized.filter((cell) => cell.home + cell.away >= 3)),
    bttsBySide: sideMass(normalized.filter((cell) => cell.home >= 1 && cell.away >= 1)),
    mode: normalized.reduce((best, cell) => cell.p > best.p ? cell : best),
  };
}

/** Raw 1X2 prices (vig included) → normalized probabilities. null if unusable. */
export function devig(prices: Record<MarketSide, number> | null): Record<MarketSide, number> | null {
  if (!prices) return null;
  const total = prices.home + prices.draw + prices.away;
  if (!sides.every((side) => Number.isFinite(prices[side]) && prices[side] > 0) || !Number.isFinite(total) || total <= 0) return null;
  return { home: prices.home / total, draw: prices.draw / total, away: prices.away / total };
}

/** Rescale each W/D/L region of the Poisson grid so its mass equals the given
 *  outcome probabilities (same conditioning as the pipeline's condition_grid):
 *  the grid keeps deciding *which* scoreline within an outcome, the supplied
 *  probs decide how likely each outcome is. */
export function conditionDistribution(
  distribution: ScoreDistribution,
  probs: Record<MarketSide, number>,
): ScoreDistribution | null {
  if (!sides.every((side) => Number.isFinite(probs[side]) && probs[side] > 0 && probs[side] < 1)) return null;
  const mass = Object.fromEntries(sides.map((side) => [
    side,
    distribution.cells.filter((cell) => cell.side === side).reduce((sum, cell) => sum + cell.p, 0) + distribution.tailBySide[side],
  ])) as Record<MarketSide, number>;
  if (!sides.every((side) => mass[side] > 0)) return null;

  const cells = distribution.cells.map((cell) => ({ ...cell, p: cell.p * probs[cell.side] / mass[cell.side] }));
  const rescale = (record: Record<MarketSide, number>) => Object.fromEntries(
    sides.map((side) => [side, record[side] * probs[side] / mass[side]]),
  ) as Record<MarketSide, number>;
  const tailBySide = rescale(distribution.tailBySide);

  return {
    cells,
    tail: sides.reduce((sum, side) => sum + tailBySide[side], 0),
    tailBySide,
    over25BySide: rescale(distribution.over25BySide),
    bttsBySide: rescale(distribution.bttsBySide),
    // mode over the 0-3 grid only: per-side scaling keeps within-side order,
    // and a >3-goal true mode is unreachable with tournament-range xGs.
    mode: cells.reduce((best, cell) => cell.p > best.p ? cell : best),
  };
}

/** Best live-or-snapshot raw 1X2 prices for a match (vig included). */
export function marketPrices(match: Match, poly: PolyLive): Record<MarketSide, number> | null {
  const live = poly.matches[kickoffEpoch(match.kickoff_utc)];
  const values = live ?? match.market;
  return values ? { home: values.home, draw: values.draw, away: values.away } : null;
}

export type MarketScoreline = {
  /** De-vigged 1X2 outcome probabilities straight from the book. */
  probs: Record<MarketSide, number>;
  /** Poisson grid conditioned on those probabilities. */
  distribution: ScoreDistribution;
  mostLikely: string;
  topScores: Array<{ score: string; p: number }>;
  pOver25: number;
  pBtts: number;
};

/** Market-implied scoreline analytics for a match: de-vigged live (or snapshot)
 *  1X2 sets the W/D/L masses, the xG Poisson grid shapes scorelines within each
 *  outcome. null when either the book or the xG model is unavailable. */
export function buildMarketScoreline(match: Match, poly: PolyLive): MarketScoreline | null {
  const scoreline = match.pred?.scoreline;
  const base = buildScoreDistribution(scoreline?.xg_home ?? Number.NaN, scoreline?.xg_away ?? Number.NaN);
  const probs = devig(marketPrices(match, poly));
  const distribution = base && probs ? conditionDistribution(base, probs) : null;
  if (!probs || !distribution) return null;
  return {
    probs,
    distribution,
    mostLikely: distribution.mode.label,
    topScores: [...distribution.cells].sort((a, b) => b.p - a.p).slice(0, 6).map((cell) => ({ score: cell.label, p: cell.p })),
    pOver25: sides.reduce((sum, side) => sum + distribution.over25BySide[side], 0),
    pBtts: sides.reduce((sum, side) => sum + distribution.bttsBySide[side], 0),
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
  const marketIsValid = market !== null
    && sides.every((side) => Number.isFinite(market[side]) && market[side] > 0)
    && Number.isFinite(marketSum)
    && marketSum > 0;

  return sides.map((side) => {
    const normalized = marketIsValid && market ? market[side] / marketSum : null;
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
