# scripts/validate_calibration.py
"""Evidence run: fit calibration on real played matches and report the honest deltas.

Prints (a) the fitted (T, delta), (b) in-sample Brier before/after on the fit set,
(c) observed vs predicted draw rate. This is a diagnostic — the HEADLINE live Brier
remains the out-of-sample number from live_scoring.score_completed_matches on locked
predictions (I2/I6).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone

from config import CALIB_TEMP_PRIOR, CALIB_DRAW_PRIOR
from data.fetcher_wc_results import fetch_wc_results
from evaluation.live_scoring import build_calibration_records
from prediction.calibration import fit_calibration

wc = fetch_wc_results(force=True)
now = datetime.now(timezone.utc)
records = build_calibration_records(wc, now)
calib, diag = fit_calibration(records, temp_prior=CALIB_TEMP_PRIOR, draw_prior=CALIB_DRAW_PRIOR)
print("Fitted:", calib)
print("Diagnostics:", diag)
assert diag["brier_after"] is None or diag["brier_after"] <= diag["brier_before"] + 1e-9, \
    "calibration must not worsen in-sample Brier"
print("OK — in-sample Brier did not worsen.")
