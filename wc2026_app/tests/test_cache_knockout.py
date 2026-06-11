import numpy as np
import pytest

from wc26.cache import fit_cached, training_key
from wc26.data import TrainingData
from wc26.knockout import advance_probabilities, et_outcome_probs


def _tiny_train(seed=42):
    rng = np.random.default_rng(seed)
    teams = np.array(["A", "B", "C", "D"])
    th = rng.choice(teams, 120)
    ta = rng.choice(teams, 120)
    mask = th != ta
    th, ta = th[mask], ta[mask]
    return TrainingData(
        goals_home=rng.poisson(1.5, len(th)),
        goals_away=rng.poisson(1.1, len(th)),
        teams_home=th,
        teams_away=ta,
        weights=np.ones(len(th)),
        neutral_venue=rng.integers(0, 2, len(th)),
    )


def test_cache_key_stable_and_sensitive():
    t1, t2 = _tiny_train(1), _tiny_train(1)
    assert training_key(t1, "poisson") == training_key(t2, "poisson")
    assert training_key(t1, "poisson") != training_key(t1, "dixon_coles")
    t2.weights = t2.weights * 0.5
    assert training_key(t1, "poisson") != training_key(t2, "poisson")


def test_fit_cached_roundtrip(tmp_path):
    train = _tiny_train()
    m1 = fit_cached(train, kind="poisson", cache_dir=tmp_path)
    files = list(tmp_path.glob("poisson-*.pkl"))
    assert len(files) == 1
    m2 = fit_cached(train, kind="poisson", cache_dir=tmp_path)  # loads pickle
    g1 = m1.predict("A", "B", neutral_venue=True)
    g2 = m2.predict("A", "B", neutral_venue=True)
    assert g1.home_win == pytest.approx(g2.home_win, abs=1e-9)


def test_et_probs_sum_to_one():
    w, d, l = et_outcome_probs(1.6, 1.0)
    assert w + d + l == pytest.approx(1.0, abs=1e-9)
    assert d > 0.4  # 30 minutes at low rates: draw is the modal ET outcome


def test_advance_symmetric_teams(grid):
    import numpy as np
    from scipy.stats import poisson as pois

    from penaltyblog.models import FootballProbabilityGrid

    goals = np.arange(16)
    matrix = np.outer(pois.pmf(goals, 1.3), pois.pmf(goals, 1.3))
    sym = FootballProbabilityGrid(matrix, 1.3, 1.3, normalize=True)
    adv = advance_probabilities(sym)
    assert adv.advance_home == pytest.approx(0.5, abs=1e-6)
    assert adv.advance_home + adv.advance_away == pytest.approx(1.0, abs=1e-9)


def test_advance_exceeds_win90_for_favourite(grid):
    adv = advance_probabilities(grid)  # grid favours home (1.6 v 1.0)
    assert adv.advance_home > adv.win_90
    assert adv.advance_home + adv.advance_away == pytest.approx(1.0, abs=1e-9)
    assert 0.5 < adv.advance_home < 1.0


def test_pens_prior_shifts_advance(grid):
    neutral = advance_probabilities(grid, pens_home=0.5)
    strong = advance_probabilities(grid, pens_home=0.8)
    assert strong.advance_home > neutral.advance_home
