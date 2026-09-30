"""Uniform random predictions from the action box: the lowest baseline."""

from __future__ import annotations

import numpy as np
from gymnasium import spaces


class RandomAgent:
    name = "random"

    def __init__(self, action_space: spaces.Box, seed: int | None = None) -> None:
        self._action_space = action_space
        self._action_space.seed(seed)

    def act(self, observation: np.ndarray) -> np.ndarray:
        return self._action_space.sample()
