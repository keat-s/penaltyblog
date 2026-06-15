"""Fit penaltyblog goal models on international training data."""

from __future__ import annotations

from penaltyblog.models import (
    BivariatePoissonGoalModel,
    DixonColesGoalModel,
    NegativeBinomialGoalModel,
    PoissonGoalsModel,
)

from .data import TrainingData

MODELS = {
    "poisson": PoissonGoalsModel,
    "dixon_coles": DixonColesGoalModel,
    "bivariate": BivariatePoissonGoalModel,
    "negbin": NegativeBinomialGoalModel,
}


def fit_model(train: TrainingData, kind: str = "dixon_coles"):
    """Fit a goal model; returns the fitted penaltyblog model object."""
    if kind not in MODELS:
        raise ValueError(f"unknown model '{kind}', choose from {sorted(MODELS)}")
    model = MODELS[kind](
        train.goals_home,
        train.goals_away,
        train.teams_home,
        train.teams_away,
        weights=train.weights,
        neutral_venue=train.neutral_venue,
    )
    model.fit()
    return model


def predict_fixture(model, home_team: str, away_team: str, neutral: bool = True):
    """Predict a fixture, returning a FootballProbabilityGrid."""
    return model.predict(home_team, away_team, neutral_venue=bool(neutral))


def try_predict_fixture(model, home_team: str, away_team: str, neutral: bool = True):
    """Predict a fixture, or return None if a team is absent from training data.

    Lets callers skip a single unknown/misspelled team instead of aborting a
    whole batch (e.g. one bad row in an odds file).
    """
    try:
        return predict_fixture(model, home_team, away_team, neutral)
    except ValueError:
        return None
