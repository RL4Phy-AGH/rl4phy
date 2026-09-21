"""Tests for the baseline agents and the benchmark loop on a synthetic dataset.

Run from the ``python/`` directory:

    python -m pytest rl4phy_env/
"""

from __future__ import annotations

import numpy as np

from rl4phy_env.agents.drift_agent import DriftAgent
from rl4phy_env.agents.persistence_agent import PersistenceAgent
from rl4phy_env.agents.random_agent import RandomAgent
from rl4phy_env.benchmark import evaluate
from rl4phy_env.test_track_env import write_dataset, write_long_dataset
from rl4phy_env.track_env import TrackPredictionEnv


def test_persistence_error_is_the_hit_spacing(tmp_path):
    env = TrackPredictionEnv(write_dataset(str(tmp_path)))
    result = evaluate(env, PersistenceAgent(), [0, 1], seed=0)

    # Track A steps (0,0,0)->(3,4,0)->(3,4,10), track B (5,5,5)->(5,5,15):
    # distances 5, 10 and 10 mm, and every error is either fully transverse or
    # fully longitudinal.
    assert result["episodes"] == 2 and result["steps"] == 3
    np.testing.assert_allclose(result["mean_step_distance_mm"], 25.0 / 3)
    np.testing.assert_allclose(result["mean_transverse_mm"], 5.0 / 3)
    np.testing.assert_allclose(result["mean_longitudinal_mm"], 20.0 / 3)
    np.testing.assert_allclose(result["mean_episode_reward"], -12.5)


def test_drift_fits_the_mean_step_and_beats_persistence(tmp_path):
    env = TrackPredictionEnv(write_long_dataset(str(tmp_path)))
    episodes = list(range(env.num_episodes))
    drift = DriftAgent.fit(env, episodes)

    # Straight tracks with 10 mm between hits along z and nothing transverse.
    np.testing.assert_allclose(drift.step_mm, [0.0, 0.0, 10.0])
    assert evaluate(env, drift, episodes, seed=0)["mean_step_distance_mm"] == 0.0
    assert (
        evaluate(env, PersistenceAgent(), episodes, seed=0)["mean_step_distance_mm"]
        == 10.0
    )


def test_random_agent_stays_in_the_box_and_is_seeded(tmp_path):
    env = TrackPredictionEnv(write_dataset(str(tmp_path)))
    observation, _ = env.reset(options={"episode": 0})

    agent = RandomAgent(env.action_space, seed=7)
    first = [agent.act(observation) for _ in range(3)]
    agent = RandomAgent(env.action_space, seed=7)
    second = [agent.act(observation) for _ in range(3)]
    for a, b in zip(first, second):
        assert env.action_space.contains(a)
        np.testing.assert_array_equal(a, b)

    # The same seed scores the same, and a random agent is worse than staying put.
    result = evaluate(env, RandomAgent(env.action_space, seed=7), [0, 1], seed=0)
    again = evaluate(env, RandomAgent(env.action_space, seed=7), [0, 1], seed=0)
    assert result == again
    assert result["mean_step_distance_mm"] > 25.0 / 3
