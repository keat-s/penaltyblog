"""Fitted-model caching.

Fitting Dixon-Coles on ~6k internationals takes seconds; the CLI refits on
every invocation. Cache the fitted model object on disk, keyed by a hash of
the exact training inputs + model kind, so identical inputs load instantly
and any change in data/weights/config naturally produces a new key.
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

import numpy as np

from .data import TrainingData
from .model import fit_model

DEFAULT_MODEL_CACHE = Path.home() / ".cache" / "wc26" / "models"


def training_key(train: TrainingData, kind: str) -> str:
    """Stable hash of model kind + exact training inputs."""
    h = hashlib.sha256()
    h.update(kind.encode())
    h.update(train.goals_home.astype(np.int64).tobytes())
    h.update(train.goals_away.astype(np.int64).tobytes())
    h.update("\x00".join(train.teams_home.tolist()).encode())
    h.update("\x00".join(train.teams_away.tolist()).encode())
    # Round weights so float noise doesn't bust the cache.
    h.update(np.round(train.weights, 8).tobytes())
    h.update(train.neutral_venue.astype(np.int64).tobytes())
    return h.hexdigest()[:16]


def fit_cached(
    train: TrainingData,
    kind: str = "dixon_coles",
    cache_dir: Path | str = DEFAULT_MODEL_CACHE,
    use_cache: bool = True,
):
    """Fit a model, loading from / saving to the on-disk cache."""
    cache_dir = Path(cache_dir).expanduser()
    path = cache_dir / f"{kind}-{training_key(train, kind)}.pkl"

    if use_cache and path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            path.unlink(missing_ok=True)  # corrupt/stale cache: refit

    model = fit_model(train, kind=kind)

    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(model, f)
        tmp.replace(path)

    return model
