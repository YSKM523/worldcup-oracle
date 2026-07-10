#!/usr/bin/env python3
"""Backfill closed Polymarket match-moneyline Yes-token histories."""

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


GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
TAG_ID = 102232
ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "web" / "public" / "data.json"
OUT_PATH = Path(__file__).resolve().parent / "out" / "pm_prices.json"
OUTCOMES = ("home", "draw", "away")
UA = "Mozilla/5.0"

ALIASES = {
    "Bosnia and Herzegovina": ("bosniaandherzegovina", "bosniaherzegovina", "bosnia"),
    "Cape Verde": ("capeverde", "caboverde"),
    "Curaçao": ("curacao",),
    "Czech Republic": ("czechrepublic", "czechia"),
    "DR Congo": ("drcongo", "congodr", "democraticrepublicofthecongo", "congo"),
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


def match_key(match: dict[str, Any]) -> str:
    return f"{match['kickoff_utc']}|{match['home']}|{match['away']}"


def classify_market(market: dict[str, Any], home: str, away: str) -> str | None:
    label = market.get("groupItemTitle") or ""
    question = market.get("question") or ""
    combined = f"{label} {question}"
    norm = normalized(combined)
    if "draw" in norm or "tie" in norm:
        return "draw"
    # groupItemTitle is the least ambiguous signal because questions often name both teams.
    if label:
        home_match = contains_team(label, home)
        away_match = contains_team(label, away)
    else:
        home_match = contains_team(question, home)
        away_match = contains_team(question, away)
        # In "Will HOME win HOME vs AWAY?", use the leading team after "Will".
        if home_match and away_match:
            prefix = re.split(r"\b(?:win|beat|vs\.?|versus)\b", question, maxsplit=1, flags=re.I)[0]
            home_match = contains_team(prefix, home)
            away_match = contains_team(prefix, away)
    if home_match and not away_match:
        return "home"
    if away_match and not home_match:
        return "away"
    return None


def select_price(history: list[dict[str, Any]], target_ts: int) -> dict[str, Any] | None:
    eligible = []
    for point in history:
        try:
            ts = int(point.get("t", 0))
            price = float(point["p"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts <= target_ts:
            eligible.append((ts, price))
    if not eligible:
        return None
    ts, price = max(eligible, key=lambda item: item[0])
    return {"ts": ts, "price": price}


def first_yes_token(market: dict[str, Any]) -> str | None:
    raw = market.get("clobTokenIds")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, list) and raw:
        return str(raw[0])
    return None


def event_matches(event: dict[str, Any], match: dict[str, Any]) -> bool:
    title = event.get("title") or ""
    if " - " in title or len(event.get("markets", [])) != 3:
        return False
    if not (contains_team(title, match["home"]) and contains_team(title, match["away"])):
        return False
    end_date = event.get("endDate")
    if not end_date:
        return False
    try:
        delta = abs((parse_dt(end_date) - parse_dt(match["kickoff_utc"])).total_seconds())
    except (ValueError, TypeError):
        return False
    # Gamma is normally exact, but two closed events currently record an
    # endDate one hour before the authoritative ledger kickoff. Team identity
    # plus the exact three-market moneyline title keeps this fallback unique.
    return delta <= 2 * 60 * 60


class PolymarketClient:
    def __init__(self, interval: float = 0.12):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "application/json"})
        self.interval = interval
        self.last_request = 0.0

    def get(self, base: str, path: str, params: dict[str, Any]) -> Any:
        wait = self.interval - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(5):
            try:
                response = self.session.get(base + path, params=params, timeout=45)
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

    def closed_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.get(
                GAMMA_URL,
                "/events",
                {"tag_id": TAG_ID, "closed": "true", "limit": 100, "offset": offset},
            )
            if not isinstance(page, list) or not page:
                break
            events.extend(page)
            if len(page) < 100:
                break
            offset += 100
        return events

    def price_history(self, token: str, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
        payload = self.get(
            CLOB_URL,
            "/prices-history",
            {"market": token, "startTs": start_ts, "endTs": end_ts, "fidelity": 1},
        )
        return payload.get("history", []) if isinstance(payload, dict) else []


def completed_matches() -> list[dict[str, Any]]:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [m for m in payload["matches"] if m.get("completed") is True]


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def fetch_all(client: PolymarketClient) -> dict[str, Any]:
    matches = completed_matches()
    events = client.closed_events()
    rows: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for index, match in enumerate(matches, start=1):
        lock, ko = target_times(match["kickoff_utc"])
        row: dict[str, Any] = {
            "match_key": match_key(match),
            "kickoff_utc": match["kickoff_utc"],
            "home": match["home"],
            "away": match["away"],
            "stage": match.get("stage"),
            "t_lock": lock.isoformat(),
            "t_ko": ko.isoformat(),
            "event_id": None,
            "event_slug": None,
                "event_title": None,
                "event_end_date": None,
                "event_kickoff_offset_seconds": None,
            "legs": {},
            "errors": [],
        }
        candidates = [e for e in events if event_matches(e, match)]
        candidates = [e for e in candidates if str(e.get("id")) not in used_ids]
        if len(candidates) != 1:
            row["errors"].append(f"event_candidates={len(candidates)}")
            rows.append(row)
            print(f"[{index:02d}/{len(matches)}] no unique event: {match['home']} vs {match['away']} ({len(candidates)})")
            continue
        event = candidates[0]
        event_id = str(event.get("id"))
        used_ids.add(event_id)
        row.update(
            {
                "event_id": event_id,
                "event_slug": event.get("slug"),
                "event_title": event.get("title"),
                "event_end_date": event.get("endDate"),
                "event_kickoff_offset_seconds": int(
                    (parse_dt(event["endDate"]) - parse_dt(match["kickoff_utc"])).total_seconds()
                ),
            }
        )
        classified: dict[str, dict[str, Any]] = {}
        for market in event.get("markets", []):
            outcome = classify_market(market, match["home"], match["away"])
            if outcome and outcome not in classified:
                classified[outcome] = market
        if set(classified) != set(OUTCOMES):
            row["errors"].append(f"classified_legs={sorted(classified)}")

        for outcome in OUTCOMES:
            market = classified.get(outcome)
            if not market:
                continue
            token = first_yes_token(market)
            leg: dict[str, Any] = {
                "market_id": str(market.get("id", "")),
                "question": market.get("question"),
                "group_item_title": market.get("groupItemTitle"),
                "yes_token": token,
                "t_lock": None,
                "t_ko": None,
            }
            if token:
                try:
                    history = client.price_history(
                        token,
                        int((lock - timedelta(days=14)).timestamp()),
                        int(ko.timestamp()),
                    )
                    leg["history_points"] = len(history)
                    for label, target in (("t_lock", lock), ("t_ko", ko)):
                        selected = select_price(history, int(target.timestamp()))
                        if selected:
                            leg[label] = {
                                "target_ts": int(target.timestamp()),
                                "price_ts": selected["ts"],
                                "bid": None,
                                "ask": None,
                                "close": selected["price"],
                                "mid": selected["price"],
                                "method": "last_trade_price",
                            }
                except Exception as exc:
                    leg["request_error"] = f"{type(exc).__name__}:{exc}"
                    row["errors"].append(f"history_{outcome}:{type(exc).__name__}")
            else:
                row["errors"].append(f"missing_yes_token_{outcome}")
            row["legs"][outcome] = leg
        rows.append(row)
        complete = all(
            row["legs"].get(o, {}).get(t) is not None
            for o in OUTCOMES
            for t in ("t_lock", "t_ko")
        )
        print(f"[{index:02d}/{len(matches)}] {event.get('slug')}: legs={len(row['legs'])} prices={'ok' if complete else 'missing'}")

    return {
        "source": "Polymarket",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tag_id": TAG_ID,
        "completed_matches": len(matches),
        "closed_events_seen": len(events),
        "rows": rows,
    }


def print_coverage(payload: dict[str, Any]) -> None:
    rows = payload["rows"]
    event = sum(bool(r.get("event_id")) for r in rows)
    legs = sum(set(r.get("legs", {})) == set(OUTCOMES) for r in rows)
    lock = sum(all(r.get("legs", {}).get(o, {}).get("t_lock") for o in OUTCOMES) for r in rows)
    ko = sum(all(r.get("legs", {}).get(o, {}).get("t_ko") for o in OUTCOMES) for r in rows)
    both = sum(
        all(r.get("legs", {}).get(o, {}).get(t) for o in OUTCOMES for t in ("t_lock", "t_ko"))
        for r in rows
    )
    print("\nPolymarket 覆盖统计")
    print(f"  完赛账本: {len(rows)}")
    print(f"  事件匹配: {event} / {len(rows)}（缺 {len(rows) - event}）")
    print(f"  三腿识别: {legs} / {len(rows)}（缺 {len(rows) - legs}）")
    print(f"  t_lock 三腿价: {lock} / {len(rows)}（缺 {len(rows) - lock}）")
    print(f"  t_ko 三腿价: {ko} / {len(rows)}（缺 {len(rows) - ko}）")
    print(f"  两时点完整: {both} / {len(rows)}（缺 {len(rows) - both}）")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--interval", type=float, default=0.12)
    args = parser.parse_args()
    payload = fetch_all(PolymarketClient(interval=args.interval))
    atomic_json(args.out, payload)
    print_coverage(payload)
    print(f"  写入: {args.out}")


if __name__ == "__main__":
    main()
