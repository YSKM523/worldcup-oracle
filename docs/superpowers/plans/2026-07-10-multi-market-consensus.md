# Multi-Market Consensus Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore LIVE STATS as a fixed left sidebar and add a Polymarket + Kalshi normalized 50/50 consensus market console with one-second unauthenticated Kalshi REST updates.

**Architecture:** A Cloudflare Pages Function resolves `KXWCGAME` events and returns a stable Kalshi quote contract. A modal-scoped React hook polls that endpoint and a pure consensus module normalizes each venue before averaging. `MatchModal` composes a 270px telemetry/stats sidebar, the prediction card, and a 440–500px market console; the existing Polymarket microstructure remains unchanged below the aggregate summary.

**Tech Stack:** Next.js 16, React 19, TypeScript, Vitest, Cloudflare Pages Functions, Wrangler, Kalshi public Trade API, existing Polymarket hooks

## Global Constraints

- Do not create or expose Kalshi credentials and do not bypass WebSocket authentication.
- Kalshi transport uses public REST at one-second cadence; the UI/domain interfaces must remain transport-agnostic for a later WebSocket adapter.
- Normalize each venue independently, then calculate a 50/50 arithmetic mean only when both venues have complete fresh W/D/L midpoints.
- A source missing any outcome or older than 15 seconds is excluded from dual-source consensus.
- Do not synthesize a combined order book and do not use cross-venue volume as a weighting factor.
- Preserve all existing AI, ESPN, weather, Polymarket WebSocket, depth, curve, trade-tape, and close interactions.
- At 1280px and above use `270px / minmax(0,1fr) / minmax(440px,500px)`; below 1280px use prediction → stats/telemetry → market source order.
- Only `/api/*` may invoke Pages Functions; static assets remain static.
- Preserve the repository's existing full-lint baseline of 10 errors; do not add new lint errors.

---

### Task 1: Kalshi Pages Function and deterministic API tests

**Files:**
- Create: `functions/api/kalshi/match.ts`
- Create: `web/tests/kalshiFunction.test.ts`
- Create: `web/public/_routes.json`
- Modify: `web/package.json`
- Modify: `web/package-lock.json`

**Interfaces:**
- Consumes: `GET /api/kalshi/match?home=<team>&away=<team>&kickoff=<ISO8601>`
- Produces: `KalshiQuoteResponse` JSON with `status`, `source`, `eventTicker`, `updatedAt`, `outcomes`, and optional diagnostic `reason`

- [ ] **Step 1: Add the test runner without changing production behavior**

Run from `web/`:

```bash
npm install --save-dev vitest
```

Add the exact script:

```json
"test": "vitest run"
```

- [ ] **Step 2: Write failing Function tests**

Create `web/tests/kalshiFunction.test.ts` with fixtures for Spain–Belgium:

```ts
import { describe, expect, it, vi } from "vitest";
import { fetchKalshiMatch, onRequestGet } from "../../functions/api/kalshi/match";

const events = {
  events: [{
    event_ticker: "KXWCGAME-26JUL10ESPBEL",
    title: "Spain vs Belgium: Regulation Time Moneyline",
    sub_title: "ESP vs BEL (Jul 10)",
  }],
};

const markets = {
  markets: [
    { ticker: "KXWCGAME-26JUL10ESPBEL-ESP", yes_sub_title: "Reg Time: Spain", yes_bid_dollars: "0.5900", yes_ask_dollars: "0.6000", last_price_dollars: "0.6000", volume_fp: "1631520.32" },
    { ticker: "KXWCGAME-26JUL10ESPBEL-TIE", yes_sub_title: "Reg Time: Tie", yes_bid_dollars: "0.2400", yes_ask_dollars: "0.2500", last_price_dollars: "0.2500", volume_fp: "453864.89" },
    { ticker: "KXWCGAME-26JUL10ESPBEL-BEL", yes_sub_title: "Reg Time: Belgium", yes_bid_dollars: "0.1600", yes_ask_dollars: "0.1700", last_price_dollars: "0.1700", volume_fp: "737859.59" },
  ],
};

describe("fetchKalshiMatch", () => {
  it("maps regulation-time home, draw, and away quotes", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(events)))
      .mockResolvedValueOnce(new Response(JSON.stringify(markets)));
    const result = await fetchKalshiMatch({ home: "Spain", away: "Belgium", kickoff: "2026-07-10T19:00:00Z" }, fetcher);
    expect(result.status).toBe("live");
    expect(result.outcomes.home?.mid).toBeCloseTo(0.595);
    expect(result.outcomes.draw?.mid).toBeCloseTo(0.245);
    expect(result.outcomes.away?.mid).toBeCloseTo(0.165);
  });

  it("rejects incomplete three-way markets", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(events)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ markets: markets.markets.slice(0, 2) })));
    const result = await fetchKalshiMatch({ home: "Spain", away: "Belgium", kickoff: "2026-07-10T19:00:00Z" }, fetcher);
    expect(result).toMatchObject({ status: "unavailable", reason: "incomplete-market" });
  });

  it("orients quotes to a reversed fixture input", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(events)))
      .mockResolvedValueOnce(new Response(JSON.stringify(markets)));
    const result = await fetchKalshiMatch({ home: "Belgium", away: "Spain", kickoff: "2026-07-10T19:00:00Z" }, fetcher);
    expect(result.outcomes.home?.ticker).toContain("-BEL");
    expect(result.outcomes.away?.ticker).toContain("-ESP");
  });

  it("returns a structured upstream error for rate limiting", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("", { status: 429 }));
    const result = await fetchKalshiMatch({ home: "Spain", away: "Belgium", kickoff: "2026-07-10T19:00:00Z" }, fetcher);
    expect(result).toMatchObject({ status: "error", reason: "events-429" });
  });

  it("rejects an ambiguous event match on the accepted match date", async () => {
    const duplicate = { events: [...events.events, { ...events.events[0], event_ticker: "KXWCGAME-26JUL10ESPBELX" }] };
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(duplicate)));
    const result = await fetchKalshiMatch({ home: "Spain", away: "Belgium", kickoff: "2026-07-10T19:00:00Z" }, fetcher);
    expect(result).toMatchObject({ status: "unavailable", reason: "ambiguous-event" });
  });

  it("rejects the same teams outside the kickoff date window", async () => {
    const wrongDate = { events: [{ ...events.events[0], event_ticker: "KXWCGAME-26JUL08ESPBEL" }] };
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(wrongDate)));
    const result = await fetchKalshiMatch({ home: "Spain", away: "Belgium", kickoff: "2026-07-10T19:00:00Z" }, fetcher);
    expect(result).toMatchObject({ status: "unavailable", reason: "event-not-found" });
  });
});

describe("onRequestGet", () => {
  it("returns 400 for invalid input", async () => {
    const response = await onRequestGet({
      request: new Request("https://example.com/api/kalshi/match?home=%3Cscript%3E&away=Belgium&kickoff=nope"),
      waitUntil: () => undefined,
    });
    expect(response.status).toBe(400);
  });

  it("returns a structured 502 when Kalshi is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const response = await onRequestGet({
      request: new Request("https://example.com/api/kalshi/match?home=Spain&away=Belgium&kickoff=2026-07-10T19%3A00%3A00Z"),
      waitUntil: () => undefined,
    });
    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({ status: "error", reason: "upstream-failure" });
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
cd web && npm test -- tests/kalshiFunction.test.ts
```

Expected: FAIL because `functions/api/kalshi/match.ts` does not exist.

- [ ] **Step 4: Implement the Function contract**

Create `functions/api/kalshi/match.ts` with these exported contracts and behavior:

```ts
type Side = "home" | "draw" | "away";
type Quote = { ticker: string; bid: number | null; ask: number | null; mid: number | null; last: number | null; volume: number | null };
export type KalshiQuoteResponse = {
  status: "live" | "unavailable" | "error";
  source: "kalshi-rest";
  eventTicker: string | null;
  updatedAt: number;
  outcomes: Partial<Record<Side, Quote>>;
  reason?: string;
};

const API = "https://external-api.kalshi.com/trade-api/v2";
const TEAM = /^[\p{L}\p{M} .'-]{2,40}$/u;
const TEAM_VARIANTS: Record<string, string[]> = {
  "ivory coast": ["ivory coast", "cote d'ivoire", "côte d'ivoire"],
  "south korea": ["south korea", "korea republic"],
  "united states": ["united states", "usa", "us"],
  "cape verde": ["cape verde", "cabo verde"],
  "dr congo": ["dr congo", "congo dr", "dem. rep. congo"],
  "czech republic": ["czech republic", "czechia"],
  turkey: ["turkey", "turkiye", "türkiye"],
  "bosnia and herzegovina": ["bosnia and herzegovina", "bosnia-herzegovina", "bosnia"],
  "curaçao": ["curaçao", "curacao"],
};
const hasTeam = (text: string, team: string) => (TEAM_VARIANTS[team.toLowerCase()] ?? [team.toLowerCase()]).some((name) => text.includes(name));
const json = (body: unknown, status = 200, cache = "public, max-age=0, s-maxage=1, stale-while-revalidate=4") =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": cache } });

export async function fetchKalshiMatch(
  input: { home: string; away: string; kickoff: string },
  fetcher: typeof fetch = fetch,
): Promise<KalshiQuoteResponse> {
  const now = Date.now();
  const eventResponse = await fetcher(`${API}/events?series_ticker=KXWCGAME&status=open&limit=200`);
  if (!eventResponse.ok) return { status: "error", source: "kalshi-rest", eventTicker: null, updatedAt: now, outcomes: {}, reason: `events-${eventResponse.status}` };
  const eventJson = await eventResponse.json() as { events?: Array<{ event_ticker?: string; title?: string }> };
  const home = input.home.toLowerCase();
  const away = input.away.toLowerCase();
  const kickoff = new Date(input.kickoff);
  const month = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const dateKey = (date: Date) => `${String(date.getUTCFullYear()).slice(-2)}${month[date.getUTCMonth()]}${String(date.getUTCDate()).padStart(2, "0")}`;
  const acceptedDates = new Set([dateKey(kickoff), dateKey(new Date(kickoff.getTime() - 86_400_000))]);
  const matches = (eventJson.events ?? []).filter((event) => {
    const title = (event.title ?? "").toLowerCase();
    const tickerDate = (event.event_ticker ?? "").match(/^KXWCGAME-(\d{2}[A-Z]{3}\d{2})/)?.[1];
    return !!tickerDate && acceptedDates.has(tickerDate) && hasTeam(title, home) && hasTeam(title, away) && title.includes("regulation time moneyline");
  });
  if (matches.length !== 1) return { status: "unavailable", source: "kalshi-rest", eventTicker: null, updatedAt: now, outcomes: {}, reason: matches.length ? "ambiguous-event" : "event-not-found" };

  const eventTicker = matches[0].event_ticker!;
  const marketResponse = await fetcher(`${API}/markets?event_ticker=${encodeURIComponent(eventTicker)}`);
  if (!marketResponse.ok) return { status: "error", source: "kalshi-rest", eventTicker, updatedAt: now, outcomes: {}, reason: `markets-${marketResponse.status}` };
  const marketJson = await marketResponse.json() as { markets?: Array<Record<string, unknown>> };
  const outcomes: Partial<Record<Side, Quote>> = {};
  for (const market of marketJson.markets ?? []) {
    const subtitle = String(market.yes_sub_title ?? "").toLowerCase();
    const side: Side | null = subtitle === "reg time: tie" ? "draw" : hasTeam(subtitle, home) ? "home" : hasTeam(subtitle, away) ? "away" : null;
    if (!side) continue;
    const number = (value: unknown) => { const parsed = Number(value); return Number.isFinite(parsed) && parsed > 0 ? parsed : null; };
    const bid = number(market.yes_bid_dollars);
    const ask = number(market.yes_ask_dollars);
    outcomes[side] = {
      ticker: String(market.ticker), bid, ask,
      mid: bid != null && ask != null ? (bid + ask) / 2 : bid ?? ask,
      last: number(market.last_price_dollars), volume: number(market.volume_fp),
    };
  }
  if (!outcomes.home || !outcomes.draw || !outcomes.away) return { status: "unavailable", source: "kalshi-rest", eventTicker, updatedAt: now, outcomes: {}, reason: "incomplete-market" };
  return { status: "live", source: "kalshi-rest", eventTicker, updatedAt: now, outcomes };
}

export async function onRequestGet(context: { request: Request; waitUntil(promise: Promise<unknown>): void }): Promise<Response> {
  const url = new URL(context.request.url);
  const home = url.searchParams.get("home") ?? "";
  const away = url.searchParams.get("away") ?? "";
  const kickoff = url.searchParams.get("kickoff") ?? "";
  if (!TEAM.test(home) || !TEAM.test(away) || !Number.isFinite(Date.parse(kickoff))) return json({ status: "error", source: "kalshi-rest", eventTicker: null, updatedAt: Date.now(), outcomes: {}, reason: "invalid-input" }, 400, "no-store");
  const cache = (globalThis.caches as CacheStorage & { default?: Cache } | undefined)?.default;
  const cacheKey = new Request(url.toString(), { method: "GET" });
  const cached = await cache?.match(cacheKey);
  if (cached) return cached;
  try {
    const response = json(await fetchKalshiMatch({ home, away, kickoff }));
    if (cache) context.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  } catch {
    return json({ status: "error", source: "kalshi-rest", eventTicker: null, updatedAt: Date.now(), outcomes: {}, reason: "upstream-failure" }, 502, "public, max-age=0, s-maxage=2");
  }
}
```

Create `web/public/_routes.json`:

```json
{ "version": 1, "include": ["/api/*"], "exclude": [] }
```

- [ ] **Step 5: Verify GREEN and Function compilation**

Run:

```bash
cd web && npm test -- tests/kalshiFunction.test.ts
cd .. && npx wrangler pages functions build functions --outfile /tmp/worldcup-functions.js
```

Expected: all tests pass and Wrangler exits 0.

- [ ] **Step 6: Commit**

```bash
git add functions/api/kalshi/match.ts web/tests/kalshiFunction.test.ts web/public/_routes.json web/package.json web/package-lock.json
git commit -m "feat(markets): add Kalshi quote function"
```

---

### Task 2: Consensus domain model and Kalshi polling hook

**Files:**
- Create: `web/lib/marketConsensus.ts`
- Create: `web/lib/marketConsensus.test.ts`
- Create: `web/lib/useKalshiMarket.ts`
- Modify: `web/lib/types.ts`
- Modify: `web/lib/useMatchMarket.ts`

**Interfaces:**
- Produces: `KalshiMarketState`, `buildMarketConsensus()`, and `useKalshiMarket()`
- Consumes later: `MatchModal`, `MarketConsensusPanel`, and telemetry sidebar

- [ ] **Step 1: Write failing consensus tests**

Create `web/lib/marketConsensus.test.ts`:

```ts
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
```

- [ ] **Step 2: Run RED**

Run `cd web && npm test -- lib/marketConsensus.test.ts`.

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement exact shared types**

Add to `web/lib/types.ts`:

```ts
export type MarketSide = "home" | "draw" | "away";
export interface KalshiOutcomeQuote { ticker: string; bid: number | null; ask: number | null; mid: number | null; last: number | null; volume: number | null; }
export interface KalshiQuoteResponse { status: "live" | "unavailable" | "error"; source: "kalshi-rest"; eventTicker: string | null; updatedAt: number; outcomes: Partial<Record<MarketSide, KalshiOutcomeQuote>>; reason?: string; }
export interface KalshiMarketState extends KalshiQuoteResponse { stale: boolean; failures: number; }
```

Extend `MatchMarketState` in `web/lib/useMatchMarket.ts` with `updatedAt: number | null`. Set `INIT.updatedAt` to `null`, set it to `nowS * 1000` in the existing `flush()` state update, and keep it `null` in the error reset. This timestamp is the Polymarket freshness input; no fetch or WebSocket behavior changes.

Create `web/lib/marketConsensus.ts` exporting:

```ts
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
```

- [ ] **Step 4: Implement the modal-scoped polling hook**

Create `web/lib/useKalshiMarket.ts` with `useKalshiMarket({ home, away, kickoffUtc, enabled })`. Initialize an unavailable state, request the encoded `/api/kalshi/match` URL immediately, retain the last live outcomes on errors, set `stale` when `Date.now() - updatedAt > 15_000`, and schedule with `pollDelay(failures)`. Abort the active fetch and clear the timeout in effect cleanup.

The exported signature must be:

```ts
export function useKalshiMarket(input: { home: string; away: string; kickoffUtc: string; enabled: boolean }): KalshiMarketState;
```

- [ ] **Step 5: Verify GREEN and TypeScript**

Run:

```bash
cd web && npm test -- lib/marketConsensus.test.ts
npx tsc --noEmit
```

Expected: all tests and TypeScript pass.

- [ ] **Step 6: Commit**

```bash
git add web/lib/types.ts web/lib/marketConsensus.ts web/lib/marketConsensus.test.ts web/lib/useKalshiMarket.ts web/lib/useMatchMarket.ts
git commit -m "feat(markets): add cross-venue consensus model"
```

---

### Task 3: Aggregate market console

**Files:**
- Create: `web/components/MarketConsensusPanel.tsx`
- Modify: `web/components/MatchDetail.tsx`
- Modify: `web/components/Dashboard.tsx`
- Test: Playwright with mocked `/api/kalshi/match`

**Interfaces:**
- Consumes: `KalshiMarketState`, `buildMarketConsensus()`, existing `MatchMarketState`
- Produces: `[data-market-consensus-state="dual|single|unavailable"]` and `[data-market-source="polymarket|kalshi"]`

- [ ] **Step 1: Write the failing browser contract**

Mock `/api/kalshi/match` with complete quotes, open Spain–Belgium, and assert:

```js
const panel = page.locator('[data-market-consensus-state=dual]');
if (await panel.count() !== 1) throw new Error('dual consensus missing');
if (await panel.locator('[data-market-source=polymarket]').count() !== 1) throw new Error('Polymarket source missing');
if (await panel.locator('[data-market-source=kalshi]').count() !== 1) throw new Error('Kalshi source missing');
```

- [ ] **Step 2: Run RED**

Expected: FAIL with `dual consensus missing`.

- [ ] **Step 3: Build `MarketConsensusPanel`**

The component accepts `home`, `away`, `polymarket`, and `kalshi`; converts complete Polymarket books and complete Kalshi mids to `SourceLine`, calls `buildMarketConsensus`, and renders:

- status `PM WS|REST · KAL REST 1S · 2/2 LIVE`, `1/2 SINGLE SOURCE`, or `MARKETS UNAVAILABLE`;
- a three-segment consensus bar;
- three rows showing consensus/single line, PM, Kalshi, and divergence pp;
- bid/ask/last/volume detail for Kalshi;
- amber at `warning`, rose at `critical`;
- explicit `POLY MICROSTRUCTURE` divider below the aggregate block.

The root must expose `data-market-consensus-state={result.status}`. Each venue row must expose `data-market-source`.

- [ ] **Step 4: Integrate without changing default MatchDetail callers**

Extend `MatchDetail` with optional `kalshi?: KalshiMarketState`. Render `MarketConsensusPanel` only when `variant === "console" && kalshi`; keep the existing state row, spike alert, probability curve, tabs, depth ladder, trade tape, and disclaimer below the `POLY MICROSTRUCTURE` label.

In `MatchModal`, call:

```ts
const kalshi = useKalshiMarket({ home: m.home, away: m.away, kickoffUtc: m.kickoff_utc, enabled: !!slug });
```

and pass `kalshi` to the console `MatchDetail`.

- [ ] **Step 5: Verify dual and degraded states**

Use Playwright routes to verify:

- complete response → `dual`, `2/2 LIVE`, normalized probabilities sum to 100%;
- incomplete/unavailable → `single`, Polymarket remains visible;
- both missing → `unavailable`;
- `updatedAt` older than 15 seconds → `single` and `KAL STALE`;
- a fixture above 10pp divergence produces a rose alert.
- after closing the modal, advance fake/browser time by two seconds and assert no additional `/api/kalshi/match` requests occur.

Run `npm test`, `npx tsc --noEmit`, and `npm run build`; expected exit 0.

- [ ] **Step 6: Commit**

```bash
git add web/components/MarketConsensusPanel.tsx web/components/MatchDetail.tsx web/components/Dashboard.tsx
git commit -m "feat(web): add multi-market consensus console"
```

---

### Task 4: Restore LIVE STATS sidebar and pre-match telemetry

**Files:**
- Create: `web/components/MatchTelemetry.tsx`
- Modify: `web/components/Dashboard.tsx`
- Test: Playwright desktop and stacked-layout geometry

**Interfaces:**
- Consumes: match/meta/weather, `PolyLive`, `KalshiMarketState`, existing `LiveStats`
- Produces: three semantic sections with `data-match-column="stats|prediction|market"`

- [ ] **Step 1: Write failing desktop layout assertions**

At 1920×1080 open an upcoming match and assert three columns, stats width 260–280px, market width at least 440px, and order stats → prediction → market. Expected RED because the current modal has two sections.

- [ ] **Step 2: Create the pre-match telemetry component**

`MatchTelemetry` accepts:

```ts
type MatchTelemetryProps = {
  match: Match;
  weather: WeatherData | null;
  poly: PolyLive;
  kalshi: KalshiMarketState;
};
```

Render a compact `LIVE STATS · 赛前遥测` panel with kickoff countdown/time, stage, venue/city, available temperature/humidity, ESPN `等待开赛`, Polymarket connection/freshness, Kalshi live/stale/unavailable and the fixed metric preview copy. Use `weather?.matches[match.espn_id]` for weather and `poly.matches[kickoffEpoch(match.kickoff_utc)]` for the match-specific Polymarket snapshot. Use a one-second `setInterval` effect for the countdown and clean it up on unmount. Use only existing semantic color variables and 4/8/12px spacing.

- [ ] **Step 3: Recompose `MatchModal` into three columns**

Change the grid to:

```tsx
className="grid min-h-0 max-h-[calc(100dvh-54px)] grid-cols-1 grid-rows-[max-content_max-content_max-content] overflow-y-auto xl:max-h-[calc(90vh-37px)] xl:grid-cols-[270px_minmax(0,1fr)_minmax(440px,500px)] xl:grid-rows-none xl:overflow-hidden"
```

Use source order:

```tsx
const liveEntry = live[m.espn_id];
const isStarted = m.completed || liveEntry?.state === "in" || liveEntry?.state === "post" || !!liveEntry?.completed;

<section data-match-column="stats">
  {isStarted ? (
    <LiveStats espnId={m.espn_id} home={m.home} away={m.away} live />
  ) : (
    <MatchTelemetry match={m} weather={weather} poly={poly} kalshi={kalshi} />
  )}
</section>
<section data-match-column="prediction">
  <FocusCard m={m} meta={meta} live={live} poly={poly} weather={weather} hideBook />
</section>
<section data-match-column="market">
  {slug ? (
    <MatchDetail
      slug={slug}
      kickoffUtc={m.kickoff_utc}
      home={m.home}
      away={m.away}
      pred={m.pred}
      liveEntry={live[m.espn_id]}
      variant="console"
      kalshi={kalshi}
    />
  ) : (
    <div className="mono flex min-h-40 items-center justify-center text-[12px] text-[var(--ink-faint)]">该场暂无 Polymarket 盘口</div>
  )}
</section>
```

Set the dialog maximum width to `1600px`. Desktop sections receive right borders except the final market section and independently scroll at `xl`.

- [ ] **Step 4: Verify geometry, states, and no regression**

Test 1920×1080, 2560×1440, 3440×1440, 1366×768, 1024×768, and 390×844. Assert no document horizontal overflow; `xl` has three aligned columns; 1024/390 stack in source order without overlap. Verify pre-match telemetry fills the left rail, completed matches render single-column LIVE STATS, and Escape/icon/backdrop close still work.

Run TypeScript, build, and targeted ESLint; confirm full lint remains exactly 10 errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/MatchTelemetry.tsx web/components/Dashboard.tsx
git commit -m "refactor(web): restore live stats sidebar"
```

---

### Task 5: End-to-end Function, preview, production verification

**Files:**
- Verify all Task 1–4 files
- Modify only if a failing regression test identifies a scoped defect

**Interfaces:**
- Consumes: complete feature branch
- Produces: production deployment with static routing plus `/api/kalshi/match`

- [ ] **Step 1: Run fresh repository checks**

```bash
cd web
npm test
npx tsc --noEmit
npm run build
npm run lint
cd ..
npx wrangler pages functions build functions --outfile /tmp/worldcup-functions.js
git diff --check
```

Expected: tests, TypeScript, build, Function build, and diff check pass. Full lint remains the known 10-error baseline with no new files in the error list.

- [ ] **Step 2: Run local full-stack Pages preview**

```bash
npx wrangler pages dev web/out --port 8788
```

Verify `/api/kalshi/match?home=Spain&away=Belgium&kickoff=2026-07-10T19:00:00Z` returns three live outcomes, JSON content type, and short cache headers. Verify `/` and static chunks do not invoke the Function route.

- [ ] **Step 3: Run final browser matrix**

At six specified viewports, capture settled screenshots and verify geometry, dual/single/stale/unavailable states, consensus sum, divergence alerts, source quotes, left telemetry/live stats, Polymarket tabs/depth/trades, and all close methods. Classify external upstream errors separately from application errors.

- [ ] **Step 4: Review branch scope**

```bash
git status --short
git log --oneline main..HEAD
git diff --name-status main..HEAD
```

Expected: only spec/plan, Function, routing, tests, package metadata, and scoped frontend files. Main-workspace generated weather/live-data files remain outside feature commits.

- [ ] **Step 5: Merge, rebuild, deploy, and verify production**

After final whole-branch review, fast-forward merge to `main`, rerun `npm test && npm run build`, then deploy:

```bash
npx wrangler pages deploy web/out --project-name worldcup-oracle --branch main --commit-dirty=true
```

Verify the production alias serves both the static dashboard and `/api/kalshi/match`, then open Spain–Belgium at 1920×1080 and confirm `2/2 LIVE`, three-column geometry, one-second Kalshi updates, no horizontal overflow, and working close interactions.
