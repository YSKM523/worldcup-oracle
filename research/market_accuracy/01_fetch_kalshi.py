#!/usr/bin/env python3
"""Backfill settled Kalshi regulation-time match prices at AI-lock and kickoff.

This script reads the project ledger, never the production collector, and writes
one auditable row for every completed match. Missing events, legs, results, and
price observations remain explicit in the output.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXWCGAME"
ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "web" / "public" / "data.json"
OUT_PATH = Path(__file__).resolve().parent / "out" / "kalshi_prices.json"
OUTCOMES = ("home", "draw", "away")

ALIASES = {
    "Bosnia and Herzegovina": ("bosniaandherzegovina", "bosniaherzegovina", "bosnia"),
    "Cape Verde": ("capeverde", "caboverde"),
    "Curaçao": ("curacao",),
    "Czech Republic": ("czechrepublic", "czechia"),
    "DR Congo": ("drcongo", "congodr", "democraticrepublicofthecongo", "congo"),
    "Iran": ("iran", "iranislamicrepublic"),
    "Ivory Coast": ("ivorycoast", "cotedivoire"),
    "South Korea": ("southkorea", "korearepublic", "republicofkorea", "korea"),
    "Turkey": ("turkey", "turkiye"),
    "United States": ("unitedstates", "unitedstatesofamerica", "usa"),
}


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def target_times(kickoff_iso: str) -> tuple[datetime, datetime]:
    kickoff = parse_dt(kickoff_iso).astimezone(timezone.utc)
    lock = kickoff.replace(hour=6, minute=10, second=0, microsecond=0)
    if kickoff < lock:
        lock -= timedelta(days=1)
    return lock, kickoff - timedelta(minutes=5)


def normalized(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def team_aliases(team: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((normalized(team), *ALIASES.get(team, ()))))


def contains_team(text: str, team: str) -> bool:
    haystack = normalized(text)
    return any(alias and alias in haystack for alias in team_aliases(team))


def classify_leg(subtitle: str, home: str, away: str) -> str | None:
    label = re.sub(r"^\s*Reg\s+Time:\s*", "", subtitle or "", flags=re.I).strip()
    if normalized(label) in {"tie", "draw"}:
        return "draw"
    home_match = contains_team(label, home)
    away_match = contains_team(label, away)
    if home_match and not away_match:
        return "home"
    if away_match and not home_match:
        return "away"
    return None


def match_key(match: dict[str, Any]) -> str:
    return f"{match['kickoff_utc']}|{match['home']}|{match['away']}"


def event_date(event: dict[str, Any]) -> datetime.date | None:
    ticker = event.get("event_ticker", "")
    found = re.search(r"KXWCGAME-(\d{2}[A-Z]{3}\d{2})", ticker)
    if not found:
        return None
    try:
        return datetime.strptime(found.group(1), "%y%b%d").date()
    except ValueError:
        return None


def event_matches(event: dict[str, Any], match: dict[str, Any]) -> bool:
    title = event.get("title") or event.get("sub_title") or ""
    if not (contains_team(title, match["home"]) and contains_team(title, match["away"])):
        return False
    dated = event_date(event)
    kickoff_date = parse_dt(match["kickoff_utc"]).astimezone(timezone.utc).date()
    return dated is None or abs((dated - kickoff_date).days) <= 1


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def nested_close(candle: dict[str, Any], field: str) -> float | None:
    value = candle.get(field)
    if isinstance(value, dict):
        value = value.get("close_dollars", value.get("close"))
    return as_float(value)


def select_candle(candles: list[dict[str, Any]], target_ts: int) -> dict[str, Any] | None:
    eligible = [c for c in candles if int(c.get("end_period_ts", 0) or 0) <= target_ts]
    if not eligible:
        return None
    candle = max(eligible, key=lambda c: int(c.get("end_period_ts", 0) or 0))
    bid = nested_close(candle, "yes_bid")
    ask = nested_close(candle, "yes_ask")
    close = nested_close(candle, "price")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        method = "bid_ask_mid"
    else:
        mid = close
        method = "price_close_fallback"
    if mid is None:
        return None
    return {
        "target_ts": target_ts,
        "candle_ts": int(candle["end_period_ts"]),
        "bid": bid,
        "ask": ask,
        "close": close,
        "mid": mid,
        "method": method,
    }


class KalshiClient:
    def __init__(self, interval: float = 1.02):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "worldcup-oracle-market-accuracy/1.0"})
        self.interval = interval
        self.last_request = 0.0

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        wait = self.interval - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(5):
            try:
                response = self.session.get(BASE_URL + path, params=params, timeout=45)
                self.last_request = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 4:
                        response.raise_for_status()
                    time.sleep(min(2 ** attempt, 16))
                    continue
                if 400 <= response.status_code < 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError):
                self.last_request = time.monotonic()
                if attempt == 4:
                    raise
                time.sleep(min(2 ** attempt, 16))
        raise RuntimeError("unreachable")

    def settled_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        cursor = None
        while True:
            params: dict[str, Any] = {
                "series_ticker": SERIES,
                "status": "settled",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            payload = self.get("/events", params)
            events.extend(payload.get("events", []))
            cursor = payload.get("cursor")
            if not cursor:
                break
        return events

    def markets(self, event_ticker: str) -> list[dict[str, Any]]:
        return self.get("/markets", {"event_ticker": event_ticker, "limit": 1000}).get(
            "markets", []
        )

    def candles(
        self, ticker: str, start_ts: int, end_ts: int
    ) -> list[dict[str, Any]]:
        path = f"/series/{SERIES}/markets/{ticker}/candlesticks"
        return self.get(
            path,
            {"start_ts": start_ts, "end_ts": end_ts, "period_interval": 1},
        ).get("candlesticks", [])


def completed_matches() -> list[dict[str, Any]]:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [m for m in payload["matches"] if m.get("completed") is True]


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def empty_row(match: dict[str, Any], lock: datetime, ko: datetime) -> dict[str, Any]:
    return {
        "match_key": match_key(match),
        "kickoff_utc": match["kickoff_utc"],
        "home": match["home"],
        "away": match["away"],
        "stage": match.get("stage"),
        "t_lock": lock.isoformat(),
        "t_ko": ko.isoformat(),
        "event_ticker": None,
        "event_title": None,
        "legs": {},
        "result": None,
        "errors": [],
    }


def fetch_all(client: KalshiClient) -> dict[str, Any]:
    matches = completed_matches()
    events = client.settled_events()
    rows: list[dict[str, Any]] = []
    used_events: set[str] = set()

    for index, match in enumerate(matches, start=1):
        lock, ko = target_times(match["kickoff_utc"])
        row = empty_row(match, lock, ko)
        candidates = [e for e in events if event_matches(e, match)]
        candidates = [e for e in candidates if e.get("event_ticker") not in used_events]
        if len(candidates) != 1:
            row["errors"].append(f"event_candidates={len(candidates)}")
            rows.append(row)
            print(f"[{index:02d}/{len(matches)}] no unique event: {match['home']} vs {match['away']} ({len(candidates)})")
            continue

        event = candidates[0]
        ticker = event["event_ticker"]
        used_events.add(ticker)
        row["event_ticker"] = ticker
        row["event_title"] = event.get("title") or event.get("sub_title")
        try:
            markets = client.markets(ticker)
        except Exception as exc:  # preserve the fixture and continue the backfill
            row["errors"].append(f"markets_request:{type(exc).__name__}:{exc}")
            rows.append(row)
            continue

        classified: dict[str, dict[str, Any]] = {}
        for market in markets:
            outcome = classify_leg(market.get("yes_sub_title", ""), match["home"], match["away"])
            if outcome and outcome not in classified:
                classified[outcome] = market
        if set(classified) != set(OUTCOMES):
            row["errors"].append(f"classified_legs={sorted(classified)}")

        yes_outcomes: list[str] = []
        for outcome in OUTCOMES:
            market = classified.get(outcome)
            if not market:
                continue
            result = (market.get("result") or "").lower()
            if result == "yes":
                yes_outcomes.append(outcome)
            leg = {
                "ticker": market.get("ticker"),
                "yes_sub_title": market.get("yes_sub_title"),
                "settled_result": result or None,
                "t_lock": None,
                "t_ko": None,
            }
            market_ticker = market.get("ticker")
            if market_ticker:
                try:
                    # The API caps a request at 5,000 one-minute candles.  A
                    # one-day lookback plus the longest lock-to-KO gap here is
                    # below that cap and retains the most recent pre-lock quote.
                    start_ts = int((lock - timedelta(days=1)).timestamp())
                    end_ts = int(ko.timestamp())
                    candles = client.candles(market_ticker, start_ts, end_ts)
                    leg["candles_returned"] = len(candles)
                    leg["t_lock"] = select_candle(candles, int(lock.timestamp()))
                    leg["t_ko"] = select_candle(candles, int(ko.timestamp()))
                except Exception as exc:
                    leg["request_error"] = f"{type(exc).__name__}:{exc}"
                    row["errors"].append(f"candles_{outcome}:{type(exc).__name__}")
            row["legs"][outcome] = leg
        if len(yes_outcomes) == 1:
            row["result"] = yes_outcomes[0]
        else:
            row["errors"].append(f"yes_results={yes_outcomes}")
        rows.append(row)
        complete = all(
            row["legs"].get(o, {}).get(t) is not None
            for o in OUTCOMES
            for t in ("t_lock", "t_ko")
        )
        print(f"[{index:02d}/{len(matches)}] {ticker}: legs={len(row['legs'])} result={row['result']} prices={'ok' if complete else 'missing'}")

    return {
        "source": "Kalshi",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "series_ticker": SERIES,
        "completed_matches": len(matches),
        "settled_events_seen": len(events),
        "rows": rows,
    }


def print_coverage(payload: dict[str, Any]) -> None:
    rows = payload["rows"]
    event = sum(bool(r.get("event_ticker")) for r in rows)
    legs = sum(set(r.get("legs", {})) == set(OUTCOMES) for r in rows)
    truth = sum(r.get("result") in OUTCOMES for r in rows)
    lock = sum(all(r.get("legs", {}).get(o, {}).get("t_lock") for o in OUTCOMES) for r in rows)
    ko = sum(all(r.get("legs", {}).get(o, {}).get("t_ko") for o in OUTCOMES) for r in rows)
    both = sum(
        all(r.get("legs", {}).get(o, {}).get(t) for o in OUTCOMES for t in ("t_lock", "t_ko"))
        for r in rows
    )
    print("\nKalshi 覆盖统计")
    print(f"  完赛账本: {len(rows)}")
    print(f"  事件匹配: {event} / {len(rows)}（缺 {len(rows) - event}）")
    print(f"  三腿识别: {legs} / {len(rows)}（缺 {len(rows) - legs}）")
    print(f"  settled truth: {truth} / {len(rows)}（缺 {len(rows) - truth}）")
    print(f"  t_lock 三腿价: {lock} / {len(rows)}（缺 {len(rows) - lock}）")
    print(f"  t_ko 三腿价: {ko} / {len(rows)}（缺 {len(rows) - ko}）")
    print(f"  两时点完整: {both} / {len(rows)}（缺 {len(rows) - both}）")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--interval", type=float, default=1.02, help="minimum seconds between API calls")
    args = parser.parse_args()
    payload = fetch_all(KalshiClient(interval=args.interval))
    atomic_json(args.out, payload)
    print_coverage(payload)
    print(f"  写入: {args.out}")


if __name__ == "__main__":
    main()
