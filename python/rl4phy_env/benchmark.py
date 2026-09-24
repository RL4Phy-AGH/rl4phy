"""First benchmark on recorded MUonE data: the agents from ``rl4phy_env.agents``.

    random       uniform sample from the action space
    persistence  predict that the particle does not move between two hits
    drift        persistence plus a constant step along z

None of them learns anything; their errors in mm are the bar every later model
has to clear. The errors are reported split into a transverse (x, y) and a
longitudinal (z) part, because on this geometry the two are not the same
problem: the step along z is close to the station spacing, while the transverse
motion is the scattering that a surrogate would actually have to learn.

drift is fitted on the very tracks it is then scored on, see its module for why
that makes its number a lower bound rather than a held-out result.

Run from the ``python/`` directory:

    python -m rl4phy_env.benchmark --dataset /path/to/steps-*.parquet
"""

from __future__ import annotations

import argparse

import numpy as np

from rl4phy_env.agents.drift_agent import DriftAgent
from rl4phy_env.agents.persistence_agent import PersistenceAgent
from rl4phy_env.agents.random_agent import RandomAgent
from rl4phy_env.track_env import TrackPredictionEnv, positions_of


def evaluate(env: TrackPredictionEnv, agent, episodes: list[int], seed: int) -> dict:
    """Score one agent on the given episodes; every agent sees the same ones."""
    episode_rewards: list[float] = []
    errors: list[np.ndarray] = []

    for episode in episodes:
        observation, _ = env.reset(seed=seed, options={"episode": episode})
        total = 0.0
        while True:
            prediction = np.asarray(agent.act(observation), dtype=np.float32)
            observation, reward, terminated, truncated, info = env.step(prediction)
            total += reward

            # step() returns the hit it just asked about, so the truth the
            # prediction was scored against is that hit's position.
            error = prediction - positions_of(observation)
            assert abs(np.linalg.norm(error) - info["distance_mm"]) <= 1e-4 * max(
                1.0, info["distance_mm"]
            ), "the reported error is not the one the environment rewarded"
            errors.append(error)

            if terminated or truncated:
                break
        episode_rewards.append(total)

    # Columns of an error vector, in the order positions_of returns them.
    stacked = np.asarray(errors, dtype=np.float64)
    distances = np.linalg.norm(stacked, axis=1)
    transverse = np.linalg.norm(stacked[:, :2], axis=1)
    longitudinal = np.abs(stacked[:, 2])

    return {
        "episodes": len(episode_rewards),
        "steps": len(distances),
        "mean_episode_reward": float(np.mean(episode_rewards)),
        "mean_step_distance_mm": float(np.mean(distances)),
        "median_step_distance_mm": float(np.median(distances)),
        "mean_transverse_mm": float(np.mean(transverse)),
        "mean_longitudinal_mm": float(np.mean(longitudinal)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        required=True,
        help="parquet file, directory or glob written by dataset_writer.py",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=0,
        help="how many tracks to evaluate (0 = all)",
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    env = TrackPredictionEnv(args.dataset)
    count = (
        env.num_episodes if args.episodes <= 0 else min(args.episodes, env.num_episodes)
    )
    episodes = list(range(count))
    hits = [env.episode_length(i) + 1 for i in episodes]

    agents = (
        RandomAgent(env.action_space, seed=args.seed),
        PersistenceAgent(),
        DriftAgent.fit(env, episodes),
    )

    print(f"dataset: {args.dataset}")
    print(f"tracks with >= 2 hits: {env.num_episodes}, evaluating {count}")
    print(
        f"hits per evaluated track: min {min(hits)}, max {max(hits)}, total {sum(hits)}"
    )
    print(
        "action space (mm): "
        f"low {np.round(env.action_space.low, 1).tolist()} "
        f"high {np.round(env.action_space.high, 1).tolist()}"
    )
    drift = agents[-1]
    print(
        f"drift step (mm): {np.round(drift.step_mm, 3).tolist()}, "
        "fitted on the evaluated tracks"
    )
    print()

    header = (
        f"{'agent':<12}{'episodes':>9}{'steps':>7}{'mean ep. reward':>18}"
        f"{'mean err':>10}{'median err':>12}{'mean err x,y':>14}{'mean err z':>12}"
    )
    print(header)
    print(
        f"{'':<12}{'':>9}{'':>7}{'':>18}{'[mm]':>10}{'[mm]':>12}{'[mm]':>14}{'[mm]':>12}"
    )
    print("-" * len(header))
    for agent in agents:
        result = evaluate(env, agent, episodes, args.seed)
        print(
            f"{agent.name:<12}{result['episodes']:>9}{result['steps']:>7}"
            f"{result['mean_episode_reward']:>18.3f}"
            f"{result['mean_step_distance_mm']:>10.3f}"
            f"{result['median_step_distance_mm']:>12.3f}"
            f"{result['mean_transverse_mm']:>14.3f}"
            f"{result['mean_longitudinal_mm']:>12.3f}"
        )


if __name__ == "__main__":
    main()
