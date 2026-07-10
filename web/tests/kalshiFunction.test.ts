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
