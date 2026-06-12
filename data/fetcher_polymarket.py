"""Fetch World Cup odds and market data from Polymarket."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from config import CACHE_DIR, GAMMA_API_BASE, CLOB_API_BASE, TEAM_NAME_ALIASES

log = logging.getLogger(__name__)

POLYMARKET_ODDS_PARQUET = CACHE_DIR / "polymarket_odds.parquet"

# Reverse alias map: canonical name → possible Polymarket display names
_POLYMARKET_TO_CANONICAL = {v: v for v in set(TEAM_NAME_ALIASES.values())}
_POLYMARKET_TO_CANONICAL.update({
    "USA": "United States",
    "US": "United States",
    "United States": "United States",
    "South Korea": "South Korea",
    "Korea Republic": "South Korea",
    "Ivory Coast": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Bosnia": "Bosnia and Herzegovina",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "DR Congo": "DR Congo",
    "Dem. Rep. Congo": "DR Congo",
    "Democratic Republic of the Congo": "DR Congo",
    "Cape Verde": "Cape Verde",
    "Cabo Verde": "Cape Verde",
    "Curacao": "Curaçao",
    "Curaçao": "Curaçao",
    "Turkiye": "Turkey",
    "Turkey": "Turkey",
    "Türkiye": "Turkey",
    "Cezchia": "Czech Republic",
    "Czechia": "Czech Republic",
    "Czech Republic": "Czech Republic",
    "Congo DR": "DR Congo",
    "USA": "United States",
})


def _normalize_polymarket_name(name: str) -> str:
    """Normalize a Polymarket team name to our canonical form."""
    return _POLYMARKET_TO_CANONICAL.get(name, name)


class PolymarketClient:
    """Client for the Polymarket Gamma API (public, no auth needed)."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def search_markets(self, query: str, limit: int = 50) -> list[dict]:
        """Search for markets matching a query."""
        resp = self.session.get(
            f"{GAMMA_API_BASE}/markets",
            params={"_q": query, "limit": limit, "active": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_events(self, query: str, limit: int = 20) -> list[dict]:
        """Search for events matching a query."""
        resp = self.session.get(
            f"{GAMMA_API_BASE}/events",
            params={"_q": query, "limit": limit, "active": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_market_by_id(self, market_id: str) -> dict:
        """Fetch a single market by ID."""
        resp = self.session.get(
            f"{GAMMA_API_BASE}/markets/{market_id}",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_wc_winner_odds(self) -> pd.DataFrame | None:
        """Fetch current World Cup winner market odds.

        The 2026 WC winner event is structured as ~50 binary markets
        ("Will X win?"), each with a Yes/No price. The Yes price is
        the implied probability.

        Returns DataFrame with columns: team, implied_prob, market_id
        """
        # Active event slug (verified 2026-06-12). Older dated slugs are dead;
        # the title-search fallback below covers future slug churn.
        WC_EVENT_SLUGS = [
            "world-cup-winner",
            "2026-fifa-world-cup-winner-595",
            "2026-fifa-world-cup-winner",
        ]

        for slug in WC_EVENT_SLUGS:
            try:
                events = self.session.get(
                    f"{GAMMA_API_BASE}/events",
                    params={"slug": slug},
                    timeout=30,
                ).json()

                if not events:
                    continue

                event = events[0]
                markets = event.get("markets", [])
                if not markets:
                    continue

                return self._parse_binary_winner_markets(markets, event)

            except (requests.RequestException, IndexError, KeyError) as e:
                log.warning("Slug '%s' failed: %s", slug, e)
                continue

        # Fallback: search by event title
        try:
            events = self.session.get(
                f"{GAMMA_API_BASE}/events",
                params={"limit": 50, "active": "true", "order": "volume",
                        "ascending": "false"},
                timeout=30,
            ).json()
            for event in events:
                if "world cup" in event.get("title", "").lower() and "winner" in event.get("title", "").lower():
                    markets = event.get("markets", [])
                    if markets:
                        return self._parse_binary_winner_markets(markets, event)
        except requests.RequestException as e:
            log.warning("Fallback search failed: %s", e)

        log.warning("Could not find World Cup winner market on Polymarket")
        return None

    def _parse_binary_winner_markets(
        self, markets: list[dict], event: dict
    ) -> pd.DataFrame:
        """Parse an event with multiple binary 'Will X win?' markets."""
        rows = []
        for market in markets:
            question = market.get("question", "")

            # Extract team name from "Will X win the 2026 FIFA World Cup?"
            team_name = question
            for prefix in ["Will ", "will "]:
                if team_name.startswith(prefix):
                    team_name = team_name[len(prefix):]
            for suffix in [
                " win the 2026 FIFA World Cup?",
                " win the FIFA World Cup?",
                " win the 2026 World Cup?",
                " win the World Cup?",
                " win?",
            ]:
                if team_name.endswith(suffix):
                    team_name = team_name[: -len(suffix)]
            team_name = team_name.strip()

            # Get Yes price (= implied probability)
            prices_raw = market.get("outcomePrices", "[]")
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw

            if not prices:
                continue

            yes_price = float(prices[0])  # First outcome is always Yes

            canonical = _normalize_polymarket_name(team_name)

            rows.append({
                "team": canonical,
                "polymarket_name": team_name,
                "implied_prob": yes_price,
                "market_id": str(market.get("id", "")),
                "question": question,
            })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["event_title"] = event.get("title", "")
        df["volume"] = float(event.get("volume", 0) or 0)
        df["liquidity"] = float(event.get("liquidity", 0) or 0)
        df["timestamp"] = datetime.now(timezone.utc).isoformat()

        return df.sort_values("implied_prob", ascending=False).reset_index(drop=True)

    def fetch_match_moneylines(self) -> dict[str, dict]:
        """Fetch per-match W/D/L (moneyline) odds for the World Cup.

        Each match is a Gamma event titled "{home} vs. {away}" with exactly
        three binary markets (home win / away win / draw). Discovered via the
        "FIFA World Cup" tag (102232). The event's endDate equals the match
        kickoff, so we key results by kickoff for matching against our fixtures.

        Returns {kickoff_iso: {slug, home_name, away_name, home_price,
        draw_price, away_price, volume}}.
        """
        WC_TAG_ID = 102232
        out: dict[str, dict] = {}
        for offset in range(0, 500, 100):  # paginate; cap at 5 pages
            try:
                events = self.session.get(
                    f"{GAMMA_API_BASE}/events",
                    params={"tag_id": WC_TAG_ID, "limit": 100, "offset": offset,
                            "closed": "false", "related_tags": "true"},
                    timeout=30,
                ).json()
            except requests.RequestException as e:
                log.warning("Moneyline page offset=%d failed: %s", offset, e)
                break
            if not events:
                break
            for ev in events:
                parsed = self._parse_moneyline_event(ev)
                if parsed:
                    out[parsed.pop("kickoff")] = parsed
            if len(events) < 100:
                break
        log.info("Polymarket moneylines: %d match markets", len(out))
        return out

    @staticmethod
    def _parse_moneyline_event(ev: dict) -> dict | None:
        """Parse a '{home} vs. {away}' 3-market moneyline event, or None."""
        title = ev.get("title", "")
        if " vs. " not in title or " - " in title:
            return None  # props/corners/totals events carry a " - " suffix
        markets = ev.get("markets", [])
        if len(markets) != 3:
            return None
        kickoff = ev.get("endDate")
        if not kickoff:
            return None
        home_raw, away_raw = (s.strip() for s in title.split(" vs. ", 1))

        home_price = away_price = draw_price = None
        for m in markets:
            q = (m.get("question") or "").lower()
            prices_raw = m.get("outcomePrices", "[]")
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if not prices:
                continue
            yes = float(prices[0])
            if "draw" in q:
                draw_price = yes
            elif home_raw.lower() in q:
                home_price = yes
            elif away_raw.lower() in q:
                away_price = yes
        if None in (home_price, draw_price, away_price):
            return None

        return {
            "kickoff": kickoff,
            "slug": ev.get("slug", ""),
            "home_name": _normalize_polymarket_name(home_raw),
            "away_name": _normalize_polymarket_name(away_raw),
            "home_price": home_price,
            "draw_price": draw_price,
            "away_price": away_price,
            "volume": float(ev.get("volume", 0) or 0),
        }

    def fetch_all_wc_markets(self) -> list[dict]:
        """Fetch all World Cup-related markets."""
        all_markets = []
        queries = ["World Cup 2026", "FIFA 2026", "World Cup winner"]

        seen_ids = set()
        for query in queries:
            try:
                markets = self.search_markets(query, limit=100)
                for m in markets:
                    mid = m.get("id", "")
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        all_markets.append(m)
            except requests.RequestException:
                continue

        return all_markets

    def fetch_price_history(
        self, clob_token_id: str, interval: str = "max", fidelity: int = 60
    ) -> pd.DataFrame | None:
        """Fetch historical price data for one outcome token."""
        try:
            resp = self.session.get(
                f"{CLOB_API_BASE}/prices-history",
                params={
                    "market": clob_token_id,
                    "interval": interval,
                    "fidelity": fidelity,
                },
                timeout=30,
            )
            resp.raise_for_status()
            history = resp.json().get("history", [])
            if not history:
                return None

            df = pd.DataFrame(history)
            df = df.rename(columns={"t": "timestamp", "p": "price"})
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
            return df
        except requests.RequestException as e:
            log.warning("Price history fetch failed: %s", e)
            return None


def fetch_current_wc_odds() -> pd.DataFrame | None:
    """Convenience function: fetch current WC winner odds."""
    client = PolymarketClient()
    return client.fetch_wc_winner_odds()


def fetch_match_moneylines() -> dict[str, dict]:
    """Convenience function: per-match W/D/L odds keyed by kickoff ISO."""
    return PolymarketClient().fetch_match_moneylines()


def save_odds_snapshot(df: pd.DataFrame) -> None:
    """Append current odds to the historical odds file."""
    if POLYMARKET_ODDS_PARQUET.exists():
        existing = pd.read_parquet(POLYMARKET_ODDS_PARQUET)
        combined = pd.concat([existing, df], ignore_index=True)
    else:
        combined = df
    combined.to_parquet(POLYMARKET_ODDS_PARQUET)
    log.info("Saved Polymarket odds snapshot (%d rows total)", len(combined))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    print("Fetching Polymarket World Cup 2026 odds …\n")
    df = fetch_current_wc_odds()

    if df is not None:
        print(f"Market: {df['question'].iloc[0]}")
        print(f"Volume: ${df['volume'].iloc[0]:,.0f}")
        print(f"Liquidity: ${df['liquidity'].iloc[0]:,.0f}")
        print(f"\n{'Team':25s} {'Implied Prob':>12s}")
        print("-" * 40)
        for _, row in df.head(20).iterrows():
            print(f"{row['team']:25s} {row['implied_prob']:11.1%}")
        print(f"\nTotal teams: {len(df)}")
        print(f"Sum of probabilities: {df['implied_prob'].sum():.3f}")
    else:
        print("Could not fetch Polymarket odds.")
