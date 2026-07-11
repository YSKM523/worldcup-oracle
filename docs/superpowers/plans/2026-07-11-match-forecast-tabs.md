# Match Forecast Four-Tab Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the console-only model matrix/dossier with four keyboard-accessible analytical tabs, defaulting to a score distribution view.

**Architecture:** Pure functions in `forecastAnalytics.ts` derive score-grid, result scripts, and value rows from existing prediction and market data. A focused `ForecastAnalyticsTabs` component owns only tab selection and rendering. `FocusCard` keeps the always-visible match summary and mounts the tab component only in console mode.

**Tech Stack:** React 19, Next.js 16, TypeScript, Vitest, react-test-renderer, Playwright CLI, Tailwind CSS

## Global Constraints

- Default tab is `scores`; closing and reopening the dialog resets to `scores`.
- Tabs are `value`, `scripts`, `scores`, and `watch`; there is no automatic rotation.
- Remove `MODEL MATRIX` and `MATCH DOSSIER` from the console.
- Score probabilities use only a normalized Poisson grid derived from supplied xG.
- WATCH must not duplicate the right-column order book, volume, or trade tape.
- Card-mode `FocusCard` remains unchanged.
- Desktop fills the remaining center-column height; below 1280px the tab rail scrolls horizontally without wrapping.
- Preserve the established 10-error full-lint baseline and do not introduce a new lint error.

---

### Task 1: Forecast analytics domain model

**Files:**
- Create: `web/lib/forecastAnalytics.ts`
- Create: `web/lib/forecastAnalytics.test.ts`

**Interfaces:**
- Produces: `buildScoreDistribution()`, `buildMatchScripts()`, `buildValueRows()`
- Consumes later: `ForecastAnalyticsTabs`

- [ ] **Step 1: Write failing pure-function tests**

Create tests that assert normalization, score-cell identity, script aggregation, missing-xG handling, and normalized market edge:

```ts
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
});
```

- [ ] **Step 2: Run RED**

Run `cd web && npm test -- lib/forecastAnalytics.test.ts`.

Expected: FAIL because `forecastAnalytics.ts` does not exist.

- [ ] **Step 3: Implement the pure model**

Implement these exact exported contracts:

```ts
import type { MarketSide } from "./types";

export type ScoreCell = { home: number; away: number; label: string; p: number; side: MarketSide };
export type ScoreDistribution = { cells: ScoreCell[]; tail: number; tailBySide: Record<MarketSide, number>; mode: ScoreCell };
export type MatchScript = { side: MarketSide; p: number; leadingScores: ScoreCell[] };
export type ValueRow = { side: MarketSide; ai: number; market: number | null; edge: number | null; fairOdds: number; marketOdds: number | null; direction: "BUY" | "SELL" | "FAIR"; halfKelly: number | null };

const factorial = (value: number) => Array.from({ length: value }, (_, index) => index + 1).reduce((product, item) => product * item, 1);
const poisson = (lambda: number, goals: number) => Math.exp(-lambda) * (lambda ** goals) / factorial(goals);

export function buildScoreDistribution(xgHome: number, xgAway: number): ScoreDistribution | null {
  if (!Number.isFinite(xgHome) || !Number.isFinite(xgAway) || xgHome <= 0 || xgAway <= 0) return null;
  const full: ScoreCell[] = [];
  for (let home = 0; home <= 10; home++) for (let away = 0; away <= 10; away++) {
    full.push({ home, away, label: `${home}-${away}`, p: poisson(xgHome, home) * poisson(xgAway, away), side: home > away ? "home" : home === away ? "draw" : "away" });
  }
  const total = full.reduce((sum, cell) => sum + cell.p, 0);
  const normalized = full.map((cell) => ({ ...cell, p: cell.p / total }));
  const cells = normalized.filter((cell) => cell.home <= 3 && cell.away <= 3);
  const tailCells = normalized.filter((cell) => cell.home > 3 || cell.away > 3);
  const tailBySide = Object.fromEntries((["home", "draw", "away"] as const).map((side) => [side, tailCells.filter((cell) => cell.side === side).reduce((sum, cell) => sum + cell.p, 0)])) as Record<MarketSide, number>;
  return { cells, tail: tailCells.reduce((sum, cell) => sum + cell.p, 0), tailBySide, mode: normalized.reduce((best, cell) => cell.p > best.p ? cell : best) };
}

export function buildMatchScripts(distribution: ScoreDistribution): MatchScript[] {
  return (["home", "draw", "away"] as const).map((side) => {
    const matching = distribution.cells.filter((cell) => cell.side === side).sort((a, b) => b.p - a.p);
    return { side, p: matching.reduce((sum, cell) => sum + cell.p, 0) + distribution.tailBySide[side], leadingScores: matching.slice(0, 3) };
  });
}

export function buildValueRows(ai: Record<MarketSide, number>, market: Record<MarketSide, number> | null): ValueRow[] {
  const marketSum = market ? market.home + market.draw + market.away : 0;
  return (["home", "draw", "away"] as const).map((side) => {
    const normalized = market && marketSum > 0 ? market[side] / marketSum : null;
    const edge = normalized == null ? null : ai[side] - normalized;
    const halfKelly = normalized == null ? null : Math.max(0, ((ai[side] * (1 / normalized)) - 1) / ((1 / normalized) - 1) / 2);
    return { side, ai: ai[side], market: normalized, edge, fairOdds: 1 / ai[side], marketOdds: normalized ? 1 / normalized : null, direction: edge == null || Math.abs(edge) < .005 ? "FAIR" : edge > 0 ? "BUY" : "SELL", halfKelly };
  });
}
```

- [ ] **Step 4: Verify GREEN and commit**

Run `cd web && npm test -- lib/forecastAnalytics.test.ts && npx tsc --noEmit`.

Commit:

```bash
git add web/lib/forecastAnalytics.ts web/lib/forecastAnalytics.test.ts
git commit -m "feat(web): add forecast analytics model"
```

---

### Task 2: Four-tab analytics component

**Files:**
- Create: `web/components/ForecastAnalyticsTabs.tsx`
- Create: `web/components/ForecastAnalyticsTabs.test.tsx`

**Interfaces:**
- Consumes: Task 1 domain functions; `Match`, `PolyLive`, optional `KalshiMarketState`, `MatchWeather`, `LiveEntry`
- Produces: `[data-forecast-tabs]`, `[role=tab]`, `[role=tabpanel]`

- [ ] **Step 1: Write failing component tests**

Mount the real component and assert:

```tsx
expect(root.root.findByProps({ "data-forecast-tab": "scores" }).props["aria-selected"]).toBe(true);
expect(text(root)).toContain("比分分布");
act(() => root.root.findByProps({ "data-forecast-tab": "value" }).props.onClick());
expect(text(root)).toContain("AI FAIR");
act(() => root.root.findByProps({ "data-forecast-tab": "scripts" }).props.onClick());
expect(text(root)).toContain("比赛剧本");
act(() => root.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());
expect(text(root)).toContain("盯盘清单");
```

Also assert keyboard ArrowRight changes selection, missing market values render `MARKET UNAVAILABLE`, and missing xG renders `SCORE MODEL UNAVAILABLE`.

- [ ] **Step 2: Run RED**

Run `cd web && npm test -- components/ForecastAnalyticsTabs.test.tsx`.

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the component**

Use `useState<ForecastTab>("scores")`, a non-wrapping `role="tablist"`, roving `tabIndex`, `aria-controls`, and one `role="tabpanel"`. Render:

- VALUE: five aligned columns for AI, PM, fair odds, edge, and half Kelly.
- SCRIPTS: home/draw/away script rows with aggregate probability and three leading scores.
- SCORES: a 4×4 score grid, most-likely highlight, `4+` tail, and existing top-score ranking.
- WATCH: PM connection/freshness, Kalshi status, AI/PM maximum divergence, weather, and match-feed state.

The component root uses `className="mt-4 flex min-h-0 flex-1 flex-col border-y border-zinc-800/70"`; the panel uses `className="min-h-0 flex-1 overflow-y-auto py-3"`.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
cd web
npm test -- components/ForecastAnalyticsTabs.test.tsx lib/forecastAnalytics.test.ts
npx tsc --noEmit
```

Commit:

```bash
git add web/components/ForecastAnalyticsTabs.tsx web/components/ForecastAnalyticsTabs.test.tsx
git commit -m "feat(web): add forecast analytics tabs"
```

---

### Task 3: Console integration, removal, and deployment verification

**Files:**
- Modify: `web/components/MatchCards.tsx`
- Modify: `web/components/Dashboard.tsx`
- Modify: `web/components/MatchConsoleSurfaces.test.tsx`
- Test: `web/tests/task4-layout.playwright.js`

**Interfaces:**
- `FocusCard` adds optional `kalshi?: KalshiMarketState` and `liveEntry?: LiveEntry` props.
- Card-mode callers may omit both props.

- [ ] **Step 1: Write the failing integration test**

Update the console test to assert:

```ts
expect(output).toContain("VALUE · 盘口价值");
expect(output).toContain("SCORES · 比分分布");
expect(output).not.toContain("MODEL MATRIX · 模型矩阵");
expect(output).not.toContain("MATCH DOSSIER · 近期态势");
```

Run `cd web && npm test -- components/MatchConsoleSurfaces.test.tsx` and observe failure because the old sections remain.

- [ ] **Step 2: Integrate tabs and remove old console fillers**

- Import and render `ForecastAnalyticsTabs` from console-mode `FocusCard` after the always-visible Polymarket summary.
- Delete the console `MODEL MATRIX` and `MATCH DOSSIER` markup.
- Pass `kalshi` and `liveEntry` from `MatchModal` to its console `FocusCard`.
- Keep non-console h2h/stakes and analysis markup unchanged.

- [ ] **Step 3: Run fresh verification**

Run:

```bash
cd web
npm test
npx tsc --noEmit
npm run build
npx eslint components/ForecastAnalyticsTabs.tsx components/ForecastAnalyticsTabs.test.tsx lib/forecastAnalytics.ts lib/forecastAnalytics.test.ts
cd ..
git diff --check
```

Expected: all tests, TypeScript, build, targeted lint, and diff check pass; full lint remains the known 10-error baseline.

- [ ] **Step 4: Browser verification**

At 1920×1080 and 2560×1440 open Norway–England and assert:

- `scores` is selected initially.
- all four tabs switch to distinct panels.
- the prediction surface bottom aligns with the market column's 12px inset.
- no document horizontal overflow.
- closing and reopening resets to `scores`.

- [ ] **Step 5: Commit and deploy**

```bash
git add web/components/MatchCards.tsx web/components/Dashboard.tsx web/components/MatchConsoleSurfaces.test.tsx web/tests/task4-layout.playwright.js
git commit -m "feat(web): integrate forecast analytics console"
npx wrangler pages deploy web/out --project-name worldcup-oracle --branch main --commit-dirty=true
```

Verify the production alias exposes all four tabs and defaults to `SCORES`.
