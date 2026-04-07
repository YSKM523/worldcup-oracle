"""XGBoost match-level classifier for direct win/draw/loss prediction."""

from __future__ import annotations

import gc
import logging
import time

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import LabelEncoder

log = logging.getLogger(__name__)


def build_match_features(
    matches: pd.DataFrame,
    elo_at_date: dict[str, dict[str, float]],
) -> pd.DataFrame:
    """Build feature matrix for match-level prediction.

    Parameters
    ----------
    matches : DataFrame with columns: date, home_team, away_team, result,
              tournament, neutral, is_competitive
    elo_at_date : {date_str: {team: elo}} — pre-match Elo for each team at each date

    Returns
    -------
    DataFrame with one row per match and feature columns + target.
    """
    rows = []
    for _, m in matches.iterrows():
        date_str = str(m["date"].date())
        home = m["home_team"]
        away = m["away_team"]

        elo_snapshot = elo_at_date.get(date_str, {})
        elo_h = elo_snapshot.get(home, 1500.0)
        elo_a = elo_snapshot.get(away, 1500.0)

        rows.append({
            "elo_home": elo_h,
            "elo_away": elo_a,
            "elo_diff": elo_h - elo_a,
            "elo_sum": elo_h + elo_a,
            "is_neutral": int(m.get("neutral", False)),
            "is_competitive": int(m.get("is_competitive", True)),
            "result": m["result"],  # H, D, A
        })

    return pd.DataFrame(rows)


def build_elo_snapshots(elo_history: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Build {date_str: {team: elo}} from Elo history.

    Uses the most recent Elo BEFORE each date (pre-match rating).
    """
    snapshots: dict[str, dict[str, float]] = {}
    current_elo: dict[str, float] = {}

    elo_sorted = elo_history.sort_values("date")
    prev_date = None

    for _, row in elo_sorted.iterrows():
        date_str = str(row["date"].date())
        if date_str != prev_date and prev_date is not None:
            snapshots[date_str] = dict(current_elo)
        current_elo[row["team"]] = row["elo"]
        prev_date = date_str

    # Last date
    if prev_date:
        snapshots[prev_date] = dict(current_elo)

    return snapshots


class XGBoostSportsPredictor:
    """XGBoost match-level classifier.

    Unlike the TSFM models, this operates on match features (both teams)
    and directly outputs P(home_win), P(draw), P(away_win).
    """

    name = "XGBoost"

    def __init__(self):
        self._model = None
        self._le = LabelEncoder()

    def train(
        self,
        matches: pd.DataFrame,
        elo_history: pd.DataFrame,
        min_date: str = "2015-01-01",
    ) -> None:
        """Train on historical match data."""
        snapshots = build_elo_snapshots(elo_history)

        train_matches = matches[
            (matches["date"] >= min_date) & matches["is_competitive"]
        ].copy()

        log.info("Training XGBoost on %d competitive matches since %s",
                 len(train_matches), min_date)

        feat_df = build_match_features(train_matches, snapshots)
        feat_df = feat_df.dropna(subset=["result"])

        X = feat_df[["elo_home", "elo_away", "elo_diff", "elo_sum",
                      "is_neutral", "is_competitive"]].values
        y = self._le.fit_transform(feat_df["result"].values)  # A=0, D=1, H=2

        self._model = xgb.XGBClassifier(
            objective="multi:softprob",
            num_class=3,
            max_depth=4,
            learning_rate=0.05,
            n_estimators=300,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="mlogloss",
        )
        self._model.fit(X, y, verbose=False)
        log.info("XGBoost trained. Classes: %s", list(self._le.classes_))

    def predict_match(
        self,
        elo_home: float,
        elo_away: float,
        is_neutral: bool = True,
        is_competitive: bool = True,
    ) -> dict[str, float]:
        """Predict match outcome probabilities.

        Returns
        -------
        {"home_win": float, "draw": float, "away_win": float}
        """
        X = np.array([[
            elo_home, elo_away, elo_home - elo_away, elo_home + elo_away,
            int(is_neutral), int(is_competitive),
        ]])

        proba = self._model.predict_proba(X)[0]  # (3,) for A, D, H

        # Map back to readable keys
        result = {}
        for i, cls in enumerate(self._le.classes_):
            if cls == "H":
                result["home_win"] = float(proba[i])
            elif cls == "D":
                result["draw"] = float(proba[i])
            elif cls == "A":
                result["away_win"] = float(proba[i])

        return result

    def cleanup(self):
        del self._model
        self._model = None
        gc.collect()
