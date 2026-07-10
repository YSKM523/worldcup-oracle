import type { MarketSide } from "./types";

export const MARKET_SIDES: MarketSide[] = ["home", "draw", "away"];
export type ThreeWay = Record<MarketSide, number>;
export type SourceLine = ThreeWay & { updatedAt: number };
export type ConsensusResult = {
  status: "dual" | "single" | "unavailable";
  sources: 0 | 1 | 2;
  sourceNames: Array<"polymarket" | "kalshi">;
  consensus: ThreeWay;
  normalized: Partial<Record<"polymarket" | "kalshi", ThreeWay>>;
  divergence: ThreeWay;
  severity: Record<MarketSide, "normal" | "warning" | "critical">;
};
const EMPTY: ThreeWay = { home: 0, draw: 0, away: 0 };
export function normalizeThreeWay(line: ThreeWay): ThreeWay {
  const sum = line.home + line.draw + line.away;
  if (!Number.isFinite(sum) || sum <= 0 || MARKET_SIDES.some((side) => !Number.isFinite(line[side]) || line[side] <= 0)) throw new Error("invalid-three-way");
  return { home: line.home / sum, draw: line.draw / sum, away: line.away / sum };
}
export function buildMarketConsensus(poly: SourceLine | null, kalshi: SourceLine | null, now = Date.now()): ConsensusResult {
  const fresh = (line: SourceLine | null) => !!line && now - line.updatedAt <= 15_000;
  const normalized: ConsensusResult["normalized"] = {};
  if (fresh(poly)) normalized.polymarket = normalizeThreeWay(poly!);
  if (fresh(kalshi)) normalized.kalshi = normalizeThreeWay(kalshi!);
  const sourceNames = (["polymarket", "kalshi"] as const).filter((name) => normalized[name]);
  const consensus = { ...EMPTY };
  for (const side of MARKET_SIDES) consensus[side] = sourceNames.length ? sourceNames.reduce((sum, name) => sum + normalized[name]![side], 0) / sourceNames.length : 0;
  const divergence = { ...EMPTY };
  const severity: ConsensusResult["severity"] = { home: "normal", draw: "normal", away: "normal" };
  if (normalized.polymarket && normalized.kalshi) for (const side of MARKET_SIDES) {
    divergence[side] = Math.abs(normalized.polymarket[side] - normalized.kalshi[side]);
    severity[side] = divergence[side] >= 0.10 ? "critical" : divergence[side] >= 0.05 ? "warning" : "normal";
  }
  return { status: sourceNames.length === 2 ? "dual" : sourceNames.length === 1 ? "single" : "unavailable", sources: sourceNames.length as 0 | 1 | 2, sourceNames: [...sourceNames], consensus, normalized, divergence, severity };
}
export const pollDelay = (failures: number) => [1000, 2000, 5000, 10000][Math.min(Math.max(failures, 0), 3)];
