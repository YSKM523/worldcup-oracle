"""Dry-run the Phase B pipeline as if it were tournament day 1 (2026-06-11).

Patches 'today' in the pipeline + results fetcher so the date guard passes
and ESPN is queried for real (scheduled, unplayed) fixtures. Everything else
— Elo rebuild, TSFM snapshot, conditioned MC, edges, scoring — runs for real.

Run:  PYTHONPATH=. venv/bin/python scripts/dry_run_phase_b.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAKE_NOW = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)


class FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FAKE_NOW if tz else FAKE_NOW.replace(tzinfo=None)


import data.fetcher_wc_results as fwr  # noqa: E402
import pipeline.matchday_run as mr  # noqa: E402

fwr.datetime = FakeDatetime
mr.datetime = FakeDatetime

mr.main()
