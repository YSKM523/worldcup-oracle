#!/usr/bin/env python3
"""Kalshi resolver, quote polling, and Writer smoke test."""

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

import kalshi
from collector import Writer


HERE = Path(__file__).resolve().parent
DATA_JSON = HERE.parent / "web" / "public" / "data.json"
REQUIRED = {
    ("Spain", "Belgium"),
    ("Argentina", "Switzerland"),
    ("Norway", "England"),
}


def active_matches() -> list[dict]:
    data = json.loads(DATA_JSON.read_text())
    now = datetime.now(timezone.utc).timestamp()
    return [
        m
        for m in data["matches"]
        if not m.get("tbd")
        and datetime.fromisoformat(m["kickoff_utc"].replace("Z", "+00:00")).timestamp()
        + 3.5 * 3600
        >= now
    ]


async def test_live_api() -> None:
    resolved = {}
    async with aiohttp.ClientSession() as sess:
        for match in active_matches():
            key = (match["home"], match["away"])
            legs = await kalshi.resolve(sess, *key)
            print(f"resolve {key[0]} vs {key[1]}: {legs}")
            resolved[key] = legs

        assert REQUIRED <= resolved.keys()
        for key in REQUIRED:
            legs = resolved[key]
            assert legs is not None
            assert set(legs) == {"home", "draw", "away"}
            assert len(set(legs.values())) == 3
            assert legs["draw"].endswith("-TIE")

        spain = resolved[("Spain", "Belgium")]
        assert spain is not None
        assert all(t.startswith("KXWCGAME-26JUL10ESPBEL-") for t in spain.values())
        for i in range(3):
            quotes = await kalshi.poll_once(sess, spain)
            mids = [quotes[oc][2] for oc in ("home", "draw", "away")]
            assert all(mid is not None and 0 < mid < 1 for mid in mids)
            assert 0.9 <= sum(mids) <= 1.1
            print(
                f"poll {i + 1}: "
                + " ".join(
                    f"{oc}={quotes[oc][2]:.4f}"
                    for oc in ("home", "draw", "away")
                )
                + f" sum={sum(mids):.4f}"
            )
            if i < 2:
                await asyncio.sleep(1)


def test_writer() -> None:
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE kalshi_mids(
          ts_s INTEGER, slug TEXT, outcome TEXT,
          best_bid REAL, best_ask REAL, mid REAL)
        """
    )
    writer = Writer(con)
    ts = int(time.time())
    writer.kalshi.extend(
        [
            (ts, "test-slug", "home", 0.50, 0.52, 0.51),
            (ts, "test-slug", "draw", 0.24, 0.26, 0.25),
            (ts, "test-slug", "away", 0.23, 0.25, 0.24),
        ]
    )
    writer.flush()
    assert con.execute("SELECT count(*) FROM kalshi_mids").fetchone()[0] == 3
    assert writer.kalshi == []
    print("writer rows: 3")


async def main() -> None:
    await test_live_api()
    test_writer()
    print("PASS")


if __name__ == "__main__":
    asyncio.run(main())
