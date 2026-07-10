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
const ISO_KICKOFF = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?(?:Z|[+-]\d{2}:\d{2})$/;
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
const normalizeTeam = (team: string) => team
  .normalize("NFKD")
  .replace(/\p{M}/gu, "")
  .toLowerCase()
  .replace(/[^\p{L}\p{N}]+/gu, " ")
  .trim();
const TEAM_ALIASES = new Map(
  Object.entries(TEAM_VARIANTS).flatMap(([canonical, aliases]) =>
    [canonical, ...aliases].map((alias) => [normalizeTeam(alias), normalizeTeam(canonical)] as const)),
);
const canonicalTeamId = (team: string) => {
  const normalized = normalizeTeam(team);
  return TEAM_ALIASES.get(normalized) ?? normalized;
};
const eventTeams = (title: string): [string, string] | null => {
  const match = title.match(/^(.*?)\s+vs\.?\s+(.*?):\s*Regulation Time Moneyline\s*$/iu);
  return match ? [canonicalTeamId(match[1]), canonicalTeamId(match[2])] : null;
};
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
  const home = canonicalTeamId(input.home);
  const away = canonicalTeamId(input.away);
  const kickoff = new Date(input.kickoff);
  const month = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const dateKey = (date: Date) => `${String(date.getUTCFullYear()).slice(-2)}${month[date.getUTCMonth()]}${String(date.getUTCDate()).padStart(2, "0")}`;
  const acceptedDates = new Set([dateKey(kickoff), dateKey(new Date(kickoff.getTime() - 86_400_000))]);
  const matches = (eventJson.events ?? []).filter((event) => {
    const teams = eventTeams(event.title ?? "");
    const tickerDate = (event.event_ticker ?? "").match(/^KXWCGAME-(\d{2}[A-Z]{3}\d{2})/)?.[1];
    const exactFixture = teams && (
      (teams[0] === home && teams[1] === away) ||
      (teams[0] === away && teams[1] === home)
    );
    return !!tickerDate && acceptedDates.has(tickerDate) && !!exactFixture;
  });
  if (matches.length !== 1) return { status: "unavailable", source: "kalshi-rest", eventTicker: null, updatedAt: now, outcomes: {}, reason: matches.length ? "ambiguous-event" : "event-not-found" };

  const eventTicker = matches[0].event_ticker!;
  const marketResponse = await fetcher(`${API}/markets?event_ticker=${encodeURIComponent(eventTicker)}`);
  if (!marketResponse.ok) return { status: "error", source: "kalshi-rest", eventTicker, updatedAt: now, outcomes: {}, reason: `markets-${marketResponse.status}` };
  const marketJson = await marketResponse.json() as { markets?: Array<Record<string, unknown>> };
  const outcomes: Partial<Record<Side, Quote>> = {};
  for (const market of marketJson.markets ?? []) {
    const teamToken = String(market.yes_sub_title ?? "").match(/^Reg Time:\s*(.+?)\s*$/iu)?.[1];
    const team = teamToken ? canonicalTeamId(teamToken) : "";
    const side: Side | null = team === "tie" ? "draw" : team === home ? "home" : team === away ? "away" : null;
    if (!side) continue;
    const number = (value: unknown) => { const parsed = Number(value); return Number.isFinite(parsed) && parsed > 0 ? parsed : null; };
    const bid = number(market.yes_bid_dollars);
    const ask = number(market.yes_ask_dollars);
    const mid = bid != null && ask != null ? (bid + ask) / 2 : bid ?? ask;
    const ticker = typeof market.ticker === "string" ? market.ticker.trim() : "";
    if (!ticker || mid == null || !Number.isFinite(mid) || mid <= 0 || mid >= 1) continue;
    outcomes[side] = {
      ticker, bid, ask, mid,
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
  if (!TEAM.test(home) || !TEAM.test(away) || !ISO_KICKOFF.test(kickoff) || !Number.isFinite(Date.parse(kickoff))) return json({ status: "error", source: "kalshi-rest", eventTicker: null, updatedAt: Date.now(), outcomes: {}, reason: "invalid-input" }, 400, "no-store");
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
