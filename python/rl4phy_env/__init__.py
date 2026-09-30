"""Gymnasium environments over recorded Geant4 data (issue #27)."""

import gymnasium

from .track_env import TrackPredictionEnv, load_tracks

ENV_ID = "Rl4Phy/TrackPrediction-v0"

gymnasium.register(id=ENV_ID, entry_point="rl4phy_env.track_env:TrackPredictionEnv")

__all__ = ["ENV_ID", "TrackPredictionEnv", "load_tracks"]
