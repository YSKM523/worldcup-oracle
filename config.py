"""Central configuration for worldcup-oracle."""

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
TEAM_FEATURES_DIR = CACHE_DIR / "team_features"
RESULTS_DIR = ROOT / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
LOGS_DIR = RESULTS_DIR / "logs"

for d in [CACHE_DIR, TEAM_FEATURES_DIR, RESULTS_DIR, PLOTS_DIR, LOGS_DIR,
          RESULTS_DIR / "predictions", RESULTS_DIR / "odds_history",
          RESULTS_DIR / "edges", RESULTS_DIR / "simulations",
          RESULTS_DIR / "evaluations"]:
    d.mkdir(parents=True, exist_ok=True)

# ── Data Sources ─────────────────────────────────────────────────────────────
MATCHES_CSV_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/"
    "master/results.csv"
)

# ── Tournament: 2026 FIFA World Cup ─────────────────────────────────────────
TOURNAMENT_START = "2026-06-11"
TOURNAMENT_END = "2026-07-19"

# 12 groups of 4, extracted from the official match schedule
GROUPS = {
    "A": ["Mexico", "South Korea", "Czech Republic", "South Africa"],
    "B": ["United States", "Turkey", "Australia", "Paraguay"],
    "C": ["Canada", "Switzerland", "Bosnia and Herzegovina", "Qatar"],
    "D": ["Brazil", "Morocco", "Scotland", "Haiti"],
    "E": ["Germany", "Ivory Coast", "Ecuador", "Curaçao"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Iran", "Egypt", "New Zealand"],
    "H": ["Spain", "Uruguay", "Saudi Arabia", "Cape Verde"],
    "I": ["Argentina", "Algeria", "Austria", "Jordan"],
    "J": ["France", "Senegal", "Iraq", "Norway"],
    "K": ["Portugal", "Colombia", "Uzbekistan", "DR Congo"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

ALL_TEAMS = sorted({t for g in GROUPS.values() for t in g})
assert len(ALL_TEAMS) == 48

# Host countries — teams get home advantage when playing in their country
HOST_COUNTRIES = {"United States", "Canada", "Mexico"}

# Map host teams to the country they play in (all group games are at home)
HOST_TEAMS = {"United States", "Canada", "Mexico"}

# Venue → host country (for determining home advantage in knockout rounds)
VENUE_COUNTRY = {
    "Toronto": "Canada",
    "Vancouver": "Canada",
    "Mexico City": "Mexico",
    "Zapopan": "Mexico",
    "Guadalupe": "Mexico",
    "Inglewood": "United States",
    "Santa Clara": "United States",
    "East Rutherford": "United States",
    "Foxborough": "United States",
    "Houston": "United States",
    "Philadelphia": "United States",
    "Arlington": "United States",
    "Seattle": "United States",
    "Atlanta": "United States",
    "Miami Gardens": "United States",
    "Kansas City": "United States",
}

# ── Team Name Normalization ──────────────────────────────────────────────────
# martj42 dataset names → our canonical names (most already match)
TEAM_NAME_ALIASES = {
    "Korea Republic": "South Korea",
    "Côte d'Ivoire": "Ivory Coast",
    "IR Iran": "Iran",
    "Congo DR": "DR Congo",
    "Türkiye": "Turkey",
    "Cabo Verde": "Cape Verde",
    "Curacao": "Curaçao",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "USA": "United States",
    "US": "United States",
}

# ── Elo Parameters ───────────────────────────────────────────────────────────
ELO_INITIAL = 1500

# K-factor by tournament type
ELO_K_FACTORS = {
    "FIFA World Cup": 60,
    "FIFA World Cup qualification": 50,
    "UEFA Euro": 50,
    "UEFA Euro qualification": 50,
    "Copa América": 50,
    "AFC Asian Cup": 50,
    "African Cup of Nations": 50,
    "CONCACAF Gold Cup": 50,
    "FIFA Confederations Cup": 50,
    "UEFA Nations League": 40,
    "CONCACAF Nations League": 40,
    "Friendly": 20,
}
ELO_K_DEFAULT = 30  # For tournaments not explicitly listed

# Home advantage in Elo points (0 for neutral venues)
ELO_HOME_ADVANTAGE = 100

# Home advantage for host nations during the 2026 WC (slightly reduced)
WC_HOST_HOME_ADVANTAGE_ELO = 80

# ── Bradley-Terry Parameters ────────────────────────────────────────────────
# Davidson (1970) prediction map, MLE-fitted on 2010-2023 internationals with
# 2024+ holdout (scripts/calibrate_probability_map.py). Equal-teams draw prob
# = nu/(2+nu) ≈ 28%, matching the observed rate; the old nu=0.28 gave 12%.
BRADLEY_TERRY_SCALE = 405
BRADLEY_TERRY_DRAW_NU = 0.79

# ── Phase 2: residual form strength (evidence-gated; default OFF) ─────────────
FORM_LAMBDA = 0.0          # Elo points per unit residual. 0 = feature off (no-op).
FORM_CAP = 100.0           # max |Elo bump| from form
FORM_VARIANT = "points"    # "points" or "gd" — chosen by the walk-forward backtest

# ── Live Calibration (Phase 1) ───────────────────────────────────────────────
# Shrinkage priors pulling (T, delta) toward identity (1, 0). Acts like a fixed
# number of pseudo-observations at identity: dominates early, fades as n grows.
CALIB_TEMP_PRIOR = 1.5
CALIB_DRAW_PRIOR = 1.5
# Where the daily-fitted calibration artifact is written/read.
CALIBRATION_PATH = RESULTS_DIR / "calibration" / "calibration_latest.json"

# Penalty shootout split (for knockout rounds) — slight advantage to higher-rated
KNOCKOUT_PENALTY_ADVANTAGE = 0.55  # Higher-rated team's share of draw redistribution

# ── Feature Engineering ──────────────────────────────────────────────────────
# How many years of history to use for Elo computation
ELO_HISTORY_START = "1990-01-01"  # Post-1990 for relevance

# How many weeks of Elo history to feed TSFMs
TSFM_CONTEXT_WEEKS = 260  # ~5 years

# Rolling window for match-based features
ROLLING_WINDOW_MATCHES = 10

# TSFM forecast horizon in weeks (covers tournament window + buffer)
TSFM_FORECAST_HORIZON = 20

# ── Monte Carlo ──────────────────────────────────────────────────────────────
MONTE_CARLO_SIMULATIONS = 50_000
POISSON_AVG_GOALS = 2.5  # Average total goals per World Cup match

# ── Phase 4: scoreline quality (evidence-gated; default OFF) ──────────────────
DC_RHO = 0.0             # Dixon-Coles low-score correlation. 0 = independent Poisson (no-op).
GOAL_RATE_BLEND = 0.0    # weight on observed tournament goal rate vs static POISSON_AVG_GOALS. 0 = static.

# ── Model Specs ──────────────────────────────────────────────────────────────
FOUNDATION_MODELS = [
    ("models.chronos2_sports", "Chronos2SportsForecaster"),
    ("models.timesfm_sports", "TimesFMSportsForecaster"),
    ("models.flowstate_sports", "FlowStateSportsForecaster"),
]

FM_NAMES = ["Chronos-2", "TimesFM-2.5", "FlowState"]

# ── Edge Detection ───────────────────────────────────────────────────────────
MIN_EDGE_PCT = 3.0       # Minimum edge to flag (percentage points)
STRONG_EDGE_PCT = 5.0    # Strong edge threshold
STRONG_EDGE_MIN_MODELS = 3  # Minimum model agreement for STRONG EDGE
MIN_MARKET_VOLUME = 100_000  # Minimum market volume to consider ($)

# ── Polymarket ───────────────────────────────────────────────────────────────
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
