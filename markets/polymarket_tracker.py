"""Track Polymarket odds over time."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from config import RESULTS_DIR
from data.fetcher_polymarket import PolymarketClient, save_odds_snapshot

log = logging.getLogger(__name__)

ODDS_HISTORY_DIR = RESULTS_DIR / "odds_history"
ODDS_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def take_snapshot() -> pd.DataFrame | None:
    """Fetch current odds and save a timestamped snapshot."""
    client = PolymarketClient()
    df = client.fetch_wc_winner_odds()

    if df is None:
        log.warning("Failed to fetch Polymarket odds")
        return None

    # Save dated snapshot
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot_path = ODDS_HISTORY_DIR / f"polymarket_{date_str}.csv"
    df.to_csv(snapshot_path, index=False)
    log.info("Snapshot saved to %s", snapshot_path)

    # Append to cumulative parquet
    save_odds_snapshot(df)

    return df


def load_odds_history() -> pd.DataFrame | None:
    """Load all historical odds snapshots."""
    from config import CACHE_DIR

    parquet = CACHE_DIR / "polymarket_odds.parquet"
    if not parquet.exists():
        return None
    return pd.read_parquet(parquet)
