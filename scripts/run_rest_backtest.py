"""Walk-forward gate: does a rest-day Elo bump improve knockout predictions?

Hypothesis (from the 2026 weather study): rest-day differential predicts
running output (beta=+0.52) and marginally predicts favorite wins in 2026
(rho=+0.26, p=0.059). Test on 2014/2018/2022 WC knockouts whether
    elo_eff = elo + REST_ELO_PER_DAY * clamp(rest_diff, +/-3)
lowers 3-way Brier vs the plain-Elo baseline, out of sample.

Project convention (Phase 2/4): candidate must beat baseline in ALL THREE
tournaments (beats_all) to go live; otherwise no-op. Rest is computed from
each team's previous match in the same tournament (group stage included),
strictly before the knockout match date.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import BRADLEY_TERRY_SCALE, BRADLEY_TERRY_DRAW_NU
from data.elo import elo_as_of

ELO_HIST = None  # lazy

KO_WINDOWS = {
    2014: ("2014-06-12", "2014-06-28", "2014-07-13"),   # (tournament start, KO start, KO end)
    2018: ("2018-06-14", "2018-06-30", "2018-07-15"),
    2022: ("2022-11-20", "2022-12-03", "2022-12-18"),
}
CANDIDATE_ELO_PER_DAY = [0, 5, 10, 15, 25, 40]
CLAMP_DAYS = 3.0

mt = pd.read_parquet(Path(__file__).resolve().parent.parent / "data/cache/matches.parquet")
mt["date"] = pd.to_datetime(mt.date)
wc = mt[mt.tournament == "FIFA World Cup"].copy()
ELO_HIST = pd.read_parquet(Path(__file__).resolve().parent.parent / "data/cache/elo_history.parquet")


def davidson(dh, scale=BRADLEY_TERRY_SCALE, nu=BRADLEY_TERRY_DRAW_NU):
    """Elo diff -> (p_home, p_draw, p_away), Davidson draw model."""
    g = 10 ** (dh / (2 * scale))
    gi = 1 / g
    den = g + gi + nu
    return g / den, nu / den, gi / den


def brier3(rows):
    P = np.array([r[0] for r in rows]); Y = np.array([r[1] for r in rows])
    onehot = np.zeros_like(P); onehot[np.arange(len(Y)), Y] = 1
    return float(((P - onehot) ** 2).sum(axis=1).mean())


results = {}
for yr, (t0, k0, k1) in KO_WINDOWS.items():
    tour = wc[(wc.date >= t0) & (wc.date <= k1)]
    ko = tour[(tour.date >= k0)].sort_values("date")
    # per-team last match date within tournament (strictly before)
    per_bump: dict[int, list] = {b: [] for b in CANDIDATE_ELO_PER_DAY}
    n_used = 0
    for _, r in ko.iterrows():
        prev_h = tour[(tour.date < r.date) &
                      ((tour.home_team == r.home_team) | (tour.away_team == r.home_team))].date.max()
        prev_a = tour[(tour.date < r.date) &
                      ((tour.home_team == r.away_team) | (tour.away_team == r.away_team))].date.max()
        if pd.isna(prev_h) or pd.isna(prev_a):
            continue
        rest_diff = float(np.clip((prev_a - prev_h) / pd.Timedelta(days=1) * -1
                                  + (r.date - r.date) / pd.Timedelta(days=1), -99, 99))
        # rest_h - rest_a = (date-prev_h) - (date-prev_a) = prev_a - prev_h
        rest_diff = float((prev_a - prev_h) / pd.Timedelta(days=1))
        rest_diff = float(np.clip(rest_diff, -CLAMP_DAYS, CLAMP_DAYS))
        eh = elo_as_of(ELO_HIST, r.home_team, r.date)
        ea = elo_as_of(ELO_HIST, r.away_team, r.date)
        y = 0 if r.home_score > r.away_score else (1 if r.home_score == r.away_score else 2)
        n_used += 1
        for b in CANDIDATE_ELO_PER_DAY:
            dh = (eh + b * max(rest_diff, 0)) - (ea + b * max(-rest_diff, 0))
            per_bump[b].append((davidson(dh), y))
    results[yr] = {b: round(brier3(rows), 4) for b, rows in per_bump.items()}
    results[yr]["n"] = n_used

print(f"{'bump':>6} | " + " | ".join(f"{yr}" for yr in KO_WINDOWS) + " | beats_all")
base = {yr: results[yr][0] for yr in KO_WINDOWS}
for b in CANDIDATE_ELO_PER_DAY:
    line = [results[yr][b] for yr in KO_WINDOWS]
    beats = all(results[yr][b] < base[yr] for yr in KO_WINDOWS) if b != 0 else False
    print(f"{b:>6} | " + " | ".join(f"{v:.4f}" for v in line) + f" | {beats}")
print("n per tournament:", {yr: results[yr]['n'] for yr in KO_WINDOWS})
print("\nGATE:", "PASS — some bump beats baseline in all 3 tournaments"
      if any(all(results[yr][b] < base[yr] for yr in KO_WINDOWS) for b in CANDIDATE_ELO_PER_DAY[1:])
      else "FAIL — no candidate beats baseline across all tournaments -> no-op")
