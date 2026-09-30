"""Predict that the particle stays where it is: the cheapest surrogate."""

from __future__ import annotations

import numpy as np

from rl4phy_env.track_env import positions_of


class PersistenceAgent:
    name = "persistence"

    def act(self, observation: np.ndarray) -> np.ndarray:
        return positions_of(observation)
