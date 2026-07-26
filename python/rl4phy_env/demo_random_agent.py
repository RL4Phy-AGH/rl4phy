"""First benchmark on recorded MUonE data: random guesses vs. persistence.

The persistence policy predicts that the particle does not move between two
hits. It is the cheapest possible surrogate and the number it scores here is the
bar every later model has to beat.

    python -m rl4phy_env.demo_random_agent --dataset /path/to/steps-*.parquet
"""

from __future__ import annotations

import argparse
import statistics

import numpy as np

try:
    from .track_env import POSITION_SLICE, TrackPredictionEnv
except ImportError:  # executed as a plain script
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from rl4phy_env.track_env import POSITION_SLICE, TrackPredictionEnv


def random_policy(env: TrackPredictionEnv, observation: np.ndarray) -> np.ndarray:
    return env.action_space.sample()


def persistence_policy(env: TrackPredictionEnv, observation: np.ndarray) -> np.ndarray:
    """Predict that the next hit is where the particle is now."""
    return observation[POSITION_SLICE]


def evaluate(env: TrackPredictionEnv, policy, episodes: list[int], seed: int) -> dict:
    env.action_space.seed(seed)
    episode_rewards: list[float] = []
    distances: list[float] = []

    for episode in episodes:
        observation, _ = env.reset(seed=seed, options={"episode": episode})
        total = 0.0
        terminated = False
        while not terminated:
            observation, reward, terminated, _, info = env.step(
                policy(env, observation)
            )
            total += reward
            distances.append(info["distance_mm"])
        episode_rewards.append(total)

    return {
        "episodes": len(episode_rewards),
        "steps": len(distances),
        "mean_episode_reward": statistics.fmean(episode_rewards),
        "mean_step_distance_mm": statistics.fmean(distances),
        "median_step_distance_mm": statistics.median(distances),
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
    count = env.num_episodes if args.episodes <= 0 else min(args.episodes, env.num_episodes)
    episodes = list(range(count))
    hits = [env.episode_length(i) + 1 for i in episodes]

    print(f"dataset: {args.dataset}")
    print(f"tracks with >= 2 hits: {env.num_episodes}, evaluating {count}")
    print(f"hits per evaluated track: min {min(hits)}, max {max(hits)}, total {sum(hits)}")
    print(
        "action space (mm): "
        f"low {np.round(env.action_space.low, 1).tolist()} "
        f"high {np.round(env.action_space.high, 1).tolist()}"
    )
    print()

    header = f"{'policy':<12}{'episodes':>9}{'steps':>7}{'mean ep. reward':>18}{'mean err [mm]':>15}{'median err [mm]':>17}"
    print(header)
    print("-" * len(header))
    for name, policy in (("random", random_policy), ("persistence", persistence_policy)):
        result = evaluate(env, policy, episodes, args.seed)
        print(
            f"{name:<12}{result['episodes']:>9}{result['steps']:>7}"
            f"{result['mean_episode_reward']:>18.3f}"
            f"{result['mean_step_distance_mm']:>15.3f}"
            f"{result['median_step_distance_mm']:>17.3f}"
        )


if __name__ == "__main__":
    main()
