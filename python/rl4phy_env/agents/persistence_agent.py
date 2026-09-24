"""Predict that the particle does not move: the next hit is where this one is.

The cheapest possible surrogate and the first benchmark number of the project.
Its error is the mean distance between two consecutive recorded hits, which is
what a model has to explain before it explains anything about the physics. On
the MUonE geometry that distance is mostly the station spacing along z; the
transverse part is the scattering a surrogate would actually have to learn.
"""

from __future__ import annotations

import numpy as np

from rl4phy_env.track_env import positions_of


class PersistenceAgent:
    name = "persistence"

    def act(self, observation: np.ndarray) -> np.ndarray:
        return positions_of(observation)
