import pandas as pd
from evaluation.backtester import walk_forward_form_backtest


def _synthetic_wc(year):
    # 2 matchdays, 4 teams, all on distinct dates; tournament == FIFA World Cup
    rows = [
        # matchday 1
        {"date": f"{year}-06-12", "home_team": "A", "away_team": "B", "home_score": 3, "away_score": 0},
        {"date": f"{year}-06-13", "home_team": "C", "away_team": "D", "home_score": 1, "away_score": 1},
        # matchday 2
        {"date": f"{year}-06-17", "home_team": "A", "away_team": "C", "home_score": 2, "away_score": 1},
        {"date": f"{year}-06-18", "home_team": "B", "away_team": "D", "home_score": 0, "away_score": 0},
    ]
    df = pd.DataFrame(rows)
    df["tournament"] = "FIFA World Cup"
    df["neutral"] = True
    return df


def test_walk_forward_runs_and_reports_baseline_and_candidate():
    df = _synthetic_wc(2014)
    out = walk_forward_form_backtest(
        years=[2014], grid=[("points", 0.0), ("points", 100.0)], matches=df
    )
    assert set(out.columns) >= {"year", "variant", "lam", "mean_brier", "n_matches"}
    base = out[(out["lam"] == 0.0)]["mean_brier"].iloc[0]
    cand = out[(out["lam"] == 100.0)]["mean_brier"].iloc[0]
    assert base > 0.0 and cand > 0.0
    # only matchday-2 matches can differ (matchday-1 has no prior form) -> n_matches counts all 4
    assert out["n_matches"].iloc[0] == 4


def test_walk_forward_no_lookahead_first_matchday_unaffected_by_lambda():
    # With form, matchday-1 predictions must be identical regardless of lambda
    # (no prior matches exist), so any brier difference comes only from matchday 2.
    # A large λ on a fixture with a non-draw matchday-1 result (A beat B 3-0) creates
    # a non-zero residual for matchday-2 — so mean_brier MUST differ between λ=0 and λ=200.
    df = _synthetic_wc(2014)
    out = walk_forward_form_backtest(
        years=[2014], grid=[("points", 0.0), ("points", 200.0)], matches=df
    )
    assert len(out) == 2
    base = out[out["lam"] == 0.0]["mean_brier"].iloc[0]
    cand = out[out["lam"] == 200.0]["mean_brier"].iloc[0]
    # Matchday-1: A beat B 3-0 (non-draw) → non-zero form residual for A and B.
    # Matchday-2 predictions use that residual (λ=200 applies a large bump),
    # so the overall mean_brier must differ from the λ=0 baseline.
    assert base != cand, (
        f"λ=0 and λ=200 produced identical mean_brier={base:.6f}; "
        "form signal is not reaching matchday-2 predictions (wiring no-op)"
    )
