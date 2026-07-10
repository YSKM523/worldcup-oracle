"""Kalshi regulation-time match-market resolver and quote poller."""

import aiohttp


API = "https://api.elections.kalshi.com/trade-api/v2"
POLL_S = 1.0
FRESH_S = 10
RESOLVE_RETRY_S = 30
RESOLVE_ATTEMPTS = 5


async def resolve(
    sess: aiohttp.ClientSession, home: str, away: str
) -> dict[str, str] | None:
    """Resolve a fixture to its Kalshi home, draw, and away tickers."""
    async with sess.get(
        f"{API}/events",
        params={"series_ticker": "KXWCGAME", "status": "open", "limit": 200},
    ) as r:
        r.raise_for_status()
        events = (await r.json())["events"]

    home_l = home.lower()
    away_l = away.lower()
    event = next(
        (
            event
            for event in events
            if home_l in (event.get("title") or "").lower()
            and away_l in (event.get("title") or "").lower()
        ),
        None,
    )
    if not event:
        return None

    async with sess.get(
        f"{API}/markets", params={"event_ticker": event["event_ticker"]}
    ) as r:
        r.raise_for_status()
        markets = (await r.json())["markets"]

    legs: dict[str, str] = {}
    for market in markets:
        subtitle = (market.get("yes_sub_title") or "").lower()
        if subtitle == "reg time: tie":
            outcome = "draw"
        elif home_l in subtitle:
            outcome = "home"
        elif away_l in subtitle:
            outcome = "away"
        else:
            continue
        legs[outcome] = market["ticker"]
    return legs if len(legs) == 3 else None


async def poll_once(
    sess: aiohttp.ClientSession, legs: dict[str, str]
) -> dict[str, tuple[float | None, float | None, float | None]]:
    """Fetch one batched quote snapshot for the resolved Kalshi legs."""
    async with sess.get(
        f"{API}/markets", params={"tickers": ",".join(legs.values())}
    ) as r:
        r.raise_for_status()
        markets = (await r.json())["markets"]

    outcomes = {ticker: outcome for outcome, ticker in legs.items()}
    quotes = {}
    for market in markets:
        outcome = outcomes.get(market.get("ticker"))
        if not outcome:
            continue
        bid = float(market.get("yes_bid_dollars") or 0) or None
        ask = float(market.get("yes_ask_dollars") or 0) or None
        if bid is None and ask is None:
            continue
        mid = (bid + ask) / 2 if bid is not None and ask is not None else bid or ask
        quotes[outcome] = (bid, ask, mid)
    return quotes
