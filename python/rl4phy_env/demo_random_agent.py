"""First benchmark on recorded MUonE data: three policies with no learning in them.

    random       uniform sample from the action space
    persistence  predict that the particle does not move between two hits
    drift        persistence plus a constant step along z

persistence is the cheapest possible surrogate, drift the cheapest one that knows
the beam goes down z. Their errors in mm are the bar every later model has to
clear. The errors are reported split into a transverse (x, y) and a longitudinal
(z) part, because on this geometry the two are not the same problem: the step
along z is close to the station spacing, while the transverse motion is the
scattering that a surrogate would actually have to learn.

drift estimates its one parameter, the mean z step, on the very tracks it is then
scored on. That makes its number optimistic by construction -- it is a lower
bound for a constant-step model, not a held-out result.

Run from the ``python/`` directory:

    python -m rl4phy_env.demo_random_agent --dataset /path/to/steps-*.parquet
"""

from __future__ import annotations

import argparse

import numpy as np

from rl4phy_env.track_env import TrackPredictionEnv, positions_of


def random_policy(env: TrackPredictionEnv, observation: np.ndarray) -> np.ndarray:
    return env.action_space.sample()


def persistence_policy(env: TrackPredictionEnv, observation: np.ndarray) -> np.ndarray:
    """Predict that the next hit is where the particle is now."""
    return positions_of(observation)


def make_drift_policy(step_mm: np.ndarray):
    """Predict the current position displaced by a fixed step."""

    def drift_policy(env: TrackPredictionEnv, observation: np.ndarray) -> np.ndarray:
        return positions_of(observation) + step_mm

    return drift_policy


def mean_dz_mm(env: TrackPredictionEnv, episodes: list[int]) -> float:
    """Mean z displacement between two consecutive hits of the given tracks."""
    steps = [np.diff(env.tracks[episode].positions[:, 2]) for episode in episodes]
    return float(np.mean(np.concatenate(steps)))


def evaluate(env: TrackPredictionEnv, policy, episodes: list[int], seed: int) -> dict:
    env.action_space.seed(seed)
    episode_rewards: list[float] = []
    errors: list[np.ndarray] = []

    for episode in episodes:
        observation, _ = env.reset(seed=seed, options={"episode": episode})
        total = 0.0
        while True:
            prediction = np.asarray(policy(env, observation), dtype=np.float32)
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
    count = env.num_episodes if args.episodes <= 0 else min(args.episodes, env.num_episodes)
    episodes = list(range(count))
    hits = [env.episode_length(i) + 1 for i in episodes]
    dz = mean_dz_mm(env, episodes)

    print(f"dataset: {args.dataset}")
    print(f"tracks with >= 2 hits: {env.num_episodes}, evaluating {count}")
    print(f"hits per evaluated track: min {min(hits)}, max {max(hits)}, total {sum(hits)}")
    print(
        "action space (mm): "
        f"low {np.round(env.action_space.low, 1).tolist()} "
        f"high {np.round(env.action_space.high, 1).tolist()}"
    )
    print(f"drift step (mm): [0, 0, {dz:.3f}], fitted on the evaluated tracks")
    print()

    policies = (
        ("random", random_policy),
        ("persistence", persistence_policy),
        ("drift", make_drift_policy(np.array([0.0, 0.0, dz], dtype=np.float32))),
    )

    header = (
        f"{'policy':<12}{'episodes':>9}{'steps':>7}{'mean ep. reward':>18}"
        f"{'mean err':>10}{'median err':>12}{'mean err x,y':>14}{'mean err z':>12}"
    )
    print(header)
    print(f"{'':<12}{'':>9}{'':>7}{'':>18}{'[mm]':>10}{'[mm]':>12}{'[mm]':>14}{'[mm]':>12}")
    print("-" * len(header))
    for name, policy in policies:
        result = evaluate(env, policy, episodes, args.seed)
        print(
            f"{name:<12}{result['episodes']:>9}{result['steps']:>7}"
            f"{result['mean_episode_reward']:>18.3f}"
            f"{result['mean_step_distance_mm']:>10.3f}"
            f"{result['median_step_distance_mm']:>12.3f}"
            f"{result['mean_transverse_mm']:>14.3f}"
            f"{result['mean_longitudinal_mm']:>12.3f}"
        )


if __name__ == "__main__":
    main()
