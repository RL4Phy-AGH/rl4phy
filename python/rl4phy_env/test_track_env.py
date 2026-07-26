"""Tests for TrackPredictionEnv on a synthetic dataset.

    python -m pytest rl4phy_env/test_track_env.py
    python rl4phy_env/test_track_env.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

try:
    from .track_env import OBSERVATION_COLUMNS, TrackPredictionEnv, load_tracks
except ImportError:  # executed as a plain script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from rl4phy_env.track_env import (
        OBSERVATION_COLUMNS,
        TrackPredictionEnv,
        load_tracks,
    )

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataset_writer import STEP_COLUMNS, step_schema  # noqa: E402


class _FakeHit:
    def __init__(self, **values):
        self.__dict__.update(values)


def _hit(event_id, track_id, x, y, z, e_kin=1000.0, pdg=13, parent_id=0):
    return _FakeHit(
        event_id=event_id,
        track_id=track_id,
        parent_id=parent_id,
        pdg=pdg,
        x=x,
        y=y,
        z=z,
        px=0.0,
        py=0.0,
        pz=1000.0,
        e_kin=e_kin,
    )


def write_dataset(directory: str) -> str:
    """Two usable tracks plus a single-hit track that must be dropped.

    The rows are written interleaved on purpose: the reader has to rebuild the
    trajectories from (event_id, track_id) and step_index, not from row order.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = [
        _hit(0, 1, 0.0, 0.0, 0.0),  # track A, hit 0
        _hit(0, 2, 5.0, 5.0, 5.0),  # track B, hit 0
        _hit(0, 1, 3.0, 4.0, 0.0),  # track A, hit 1
        _hit(1, 1, 1.0, 1.0, 1.0),  # track C (single hit, dropped)
        _hit(0, 1, 3.0, 4.0, 10.0),  # track A, hit 2
        _hit(0, 2, 5.0, 5.0, 15.0),  # track B, hit 1
    ]

    schema = step_schema()
    columns = {name: [] for name in STEP_COLUMNS}
    for index, row in enumerate(rows):
        for name in STEP_COLUMNS:
            columns[name].append(index if name == "step_index" else getattr(row, name))

    path = os.path.join(directory, "steps-test.parquet")
    pq.write_table(
        pa.table([pa.array(columns[f.name], type=f.type) for f in schema], schema=schema),
        path,
    )
    return path


def test_episode_segmentation(tmp_path):
    path = write_dataset(str(tmp_path))
    tracks = load_tracks(path)

    assert len(tracks) == 2, "the single-hit track must be dropped"
    assert [(t.event_id, t.track_id) for t in tracks] == [(0, 1), (0, 2)]
    assert [len(t) for t in tracks] == [3, 2]

    # Track A was written interleaved; step_index defines the order.
    np.testing.assert_allclose(
        tracks[0].positions,
        [[0.0, 0.0, 0.0], [3.0, 4.0, 0.0], [3.0, 4.0, 10.0]],
    )


def test_spaces(tmp_path):
    env = TrackPredictionEnv(write_dataset(str(tmp_path)))

    assert env.observation_space.shape == (len(OBSERVATION_COLUMNS),)
    assert env.observation_space.dtype == np.float32
    assert env.action_space.shape == (3,)
    assert env.action_space.dtype == np.float32
    assert env.action_space.contains(env.action_space.sample())

    observation, info = env.reset(options={"episode": 0})
    assert env.observation_space.contains(observation)
    np.testing.assert_allclose(observation, [0.0, 0.0, 0.0, 0.0, 0.0, 1000.0, 1000.0])
    assert info["event_id"] == 0 and info["track_id"] == 1
    assert info["hits"] == 3


def test_reward_and_termination(tmp_path):
    env = TrackPredictionEnv(write_dataset(str(tmp_path)))
    observation, _ = env.reset(options={"episode": 0})

    # True next hit is (3, 4, 0); predicting the origin is 5 mm off.
    observation, reward, terminated, truncated, info = env.step([0.0, 0.0, 0.0])
    assert reward == -5.0
    assert info["distance_mm"] == 5.0
    assert not terminated and not truncated
    np.testing.assert_allclose(observation[:3], [3.0, 4.0, 0.0])

    # A perfect prediction of the last hit scores zero and ends the episode.
    _, reward, terminated, truncated, _ = env.step([3.0, 4.0, 10.0])
    assert reward == 0.0
    assert terminated and not truncated

    # An episode has one step less than it has hits.
    assert env.episode_length(0) == 2
    assert env.episode_length(1) == 1


def test_persistence_beats_random_on_a_straight_track(tmp_path):
    env = TrackPredictionEnv(write_dataset(str(tmp_path)))
    env.action_space.seed(0)

    observation, _ = env.reset(options={"episode": 0})
    _, persistence_reward, _, _, _ = env.step(observation[:3])

    observation, _ = env.reset(options={"episode": 0})
    _, random_reward, _, _, _ = env.step(env.action_space.sample())

    assert persistence_reward >= random_reward


def test_deterministic_and_seeded_iteration(tmp_path):
    path = write_dataset(str(tmp_path))

    sequential = TrackPredictionEnv(path)
    first = [sequential.reset()[1]["episode"] for _ in range(4)]
    assert first == [0, 1, 0, 1]

    # Seeding once at the start of a run has to reproduce the whole sequence.
    def shuffled_run():
        env = TrackPredictionEnv(path, shuffle=True)
        return [env.reset(seed=7 if i == 0 else None)[1]["episode"] for i in range(8)]

    assert shuffled_run() == shuffled_run()


def _main() -> int:
    import tempfile
    import traceback

    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(directory)
            except Exception:
                failures += 1
                print(f"FAIL {test.__name__}")
                traceback.print_exc()
            else:
                print(f"ok   {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main())
