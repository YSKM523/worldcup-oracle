"""Phase B: During-tournament pipeline.  *** STUB — not yet implemented. ***

Intended to run daily at 06:00 UTC during June 11 - July 19, 2026.
Currently falls back to the Phase A (pre-tournament) pipeline.

TODO before tournament starts:
  - Fetch actual match results and update Elo with them
  - Re-simulate only the *remaining* bracket (not the full tournament)
  - Score previous predictions against actual outcomes (Brier score)
  - Produce a running AI-vs-Polymarket accuracy scoreboard
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import RESULTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(RESULTS_DIR / "logs" / "matchday_run.log"),
    ],
)
log = logging.getLogger(__name__)


def main():
    """Phase B stub — currently re-runs the Phase A pre-tournament pipeline."""
    today = datetime.now(timezone.utc)
    tournament_active = (
        (today.month == 6 and today.day >= 11)
        or today.month in (7,) and today.day <= 19
    )

    if not tournament_active:
        log.info("Tournament not yet active. Use daily_run.py for pre-tournament pipeline.")
        return

    log.info("Tournament is ACTIVE — running Phase A pipeline as interim fallback.")
    log.warning(
        "Phase B (Elo update from results, remaining-bracket re-sim, "
        "prediction scoring) is NOT yet implemented."
    )

    from pipeline.daily_run import (
        step_detect_edges,
        step_fetch_odds,
        step_run_models,
        step_update_data,
    )

    matches, elo = step_update_data()
    pm_df = step_fetch_odds()
    market_probs = (
        dict(zip(pm_df["team"], pm_df["implied_prob"]))
        if pm_df is not None
        else {}
    )
    ensemble_probs, model_sim_results = step_run_models(elo)
    step_detect_edges(ensemble_probs, market_probs, model_sim_results)


if __name__ == "__main__":
    main()
