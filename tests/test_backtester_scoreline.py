import pandas as pd
from evaluation.backtester import walk_forward_scoreline_backtest


def _synth(year):
    rows = [
        {"date": f"{year}-06-12", "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 1},
        {"date": f"{year}-06-13", "home_team": "C", "away_team": "D", "home_score": 2, "away_score": 0},
        {"date": f"{year}-06-17", "home_team": "A", "away_team": "C", "home_score": 0, "away_score": 0},
        {"date": f"{year}-06-18", "home_team": "B", "away_team": "D", "home_score": 3, "away_score": 1},
    ]
    df = pd.DataFrame(rows)
    df["tournament"] = "FIFA World Cup"
    df["neutral"] = True
    return df


def test_scoreline_backtest_runs_and_reports():
    out = walk_forward_scoreline_backtest(
        years=[2014], grid=[(0.0, 0.0), (-0.1, 0.5)], matches=_synth(2014)
    )
    assert set(out.columns) >= {"year", "rho", "blend", "mean_nll", "hit_rate", "n_matches"}
    assert out["n_matches"].iloc[0] == 4
    assert (out["mean_nll"] > 0).all()


def test_scoreline_backtest_candidate_differs_from_baseline():
    out = walk_forward_scoreline_backtest(
        years=[2014], grid=[(0.0, 0.0), (-0.15, 1.0)], matches=_synth(2014)
    )
    base = out[(out["rho"] == 0.0) & (out["blend"] == 0.0)]["mean_nll"].iloc[0]
    cand = out[(out["rho"] == -0.15)]["mean_nll"].iloc[0]
    assert base != cand  # rho/blend genuinely move the scoreline NLL
