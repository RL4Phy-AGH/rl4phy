"""Uniform random predictions drawn from the action box.

The lowest bar there is. A model that has learned nothing about the data must
still beat this one; if it does not, the metric or the action box is wrong, not
the model. The box is the bounding box of the recorded hits plus a margin (see
``TrackPredictionEnv``), so the error of this agent also says how big the
detector is in the units of the reward.
"""

from __future__ import annotations

import numpy as np
from gymnasium import spaces


class RandomAgent:
    name = "random"

    def __init__(self, action_space: spaces.Box, seed: int | None = None) -> None:
        # Sampling the environment's own box keeps the baseline tied to the
        # data the environment was built from; seeding it here makes two runs
        # with the same seed draw the same actions.
        self._action_space = action_space
        self._action_space.seed(seed)

    def act(self, observation: np.ndarray) -> np.ndarray:
        # The observation is ignored on purpose: this agent knows nothing.
        return self._action_space.sample()
