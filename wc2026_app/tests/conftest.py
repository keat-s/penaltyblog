import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import poisson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from penaltyblog.models import FootballProbabilityGrid  # noqa: E402


@pytest.fixture
def grid():
    """Synthetic grid: independent Poisson, home 1.6 / away 1.0."""
    goals = np.arange(16)
    matrix = np.outer(poisson.pmf(goals, 1.6), poisson.pmf(goals, 1.0))
    return FootballProbabilityGrid(
        goal_matrix=matrix,
        home_goal_expectation=1.6,
        away_goal_expectation=1.0,
        normalize=True,
    )
