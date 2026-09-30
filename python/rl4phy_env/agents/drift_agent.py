"""Persistence plus a constant step along z, fitted on the scored tracks."""

from __future__ import annotations

import numpy as np

from rl4phy_env.track_env import TrackPredictionEnv, positions_of


class DriftAgent:
    name = "drift"

    def __init__(self, step_mm: np.ndarray) -> None:
        self.step_mm = np.asarray(step_mm, dtype=np.float32).reshape(3)

    @classmethod
    def fit(cls, env: TrackPredictionEnv, episodes: list[int]) -> DriftAgent:
        """Estimate the step as the mean z displacement over the given tracks."""
        steps = [np.diff(env.tracks[episode].positions[:, 2]) for episode in episodes]
        mean_dz = float(np.mean(np.concatenate(steps)))
        return cls(np.array([0.0, 0.0, mean_dz], dtype=np.float32))

    def act(self, observation: np.ndarray) -> np.ndarray:
        return positions_of(observation) + self.step_mm
