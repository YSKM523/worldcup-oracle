"""Phase B: During-tournament pipeline.

Runs daily at 06:00 UTC during June 11 - July 19, 2026.
After each match day:
1. Fetch actual results
2. Update Elo with results
3. Re-run TSFM models on updated data
4. Re-simulate remaining tournament
5. Fetch Polymarket odds
6. Detect edges
7. Score previous predictions
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
    """Placeholder for Phase B — will be implemented when tournament starts."""
    log.info("Matchday pipeline — Phase B")
    log.info("This pipeline activates during the tournament (June 11 - July 19, 2026)")
    log.info("It will:")
    log.info("  1. Fetch completed match results")
    log.info("  2. Update Elo ratings with actual results")
    log.info("  3. Re-run TSFM models on updated Elo")
    log.info("  4. Re-simulate remaining tournament bracket")
    log.info("  5. Compare with Polymarket odds")
    log.info("  6. Score previous predictions (Brier score)")
    log.info("  7. Update README with results")

    today = datetime.now(timezone.utc)
    if today.month == 6 and today.day >= 11 or today.month == 7 and today.day <= 19:
        log.info("Tournament is ACTIVE. Running full update …")
        # Import and run Phase A's full pipeline as a starting point
        from pipeline.daily_run import step_fetch_odds, step_update_data, step_run_models, step_detect_edges
        matches, elo = step_update_data()
        pm_df = step_fetch_odds()
        market_probs = dict(zip(pm_df["team"], pm_df["implied_prob"])) if pm_df is not None else {}
        ensemble_probs, model_sim_results = step_run_models(elo)
        step_detect_edges(ensemble_probs, market_probs, model_sim_results)
    else:
        log.info("Tournament not yet active. Use daily_run.py for pre-tournament pipeline.")


if __name__ == "__main__":
    main()
