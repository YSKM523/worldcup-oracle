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
