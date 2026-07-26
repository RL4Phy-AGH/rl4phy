"""Tests for TrackPredictionEnv on a synthetic dataset.

Run from the ``python/`` directory:

    python -m pytest rl4phy_env/
"""

from __future__ import annotations

import os

import gymnasium
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from gymnasium.utils.env_checker import check_env

from dataset_writer import ParquetStepWriter
from rl4phy_env import ENV_ID
from rl4phy_env.track_env import OBSERVATION_COLUMNS, TrackPredictionEnv, load_tracks


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


def _record(directory: str, hits: list[_FakeHit]) -> str:
    """Write the hits through the real sink, in two-row batches.

    Going through ParquetStepWriter rather than building the table by hand keeps
    the tests honest about the file the server actually produces, and the small
    flush size means every fixture crosses a flush boundary.
    """
    writer = ParquetStepWriter(directory, flush_rows=2)
    for hit in hits:
        writer.append_step_hit(hit)
    writer.close()
    return writer.path


def write_dataset(directory: str) -> str:
    """Two usable tracks plus a single-hit track that must be dropped.

    The rows are recorded interleaved on purpose: the reader has to rebuild the
    trajectories from (event_id, track_id) and row_index, not from row order.
    """
    return _record(
        directory,
        [
            _hit(0, 1, 0.0, 0.0, 0.0),  # track A, hit 0
            _hit(0, 2, 5.0, 5.0, 5.0),  # track B, hit 0
            _hit(0, 1, 3.0, 4.0, 0.0),  # track A, hit 1
            _hit(1, 1, 1.0, 1.0, 1.0),  # track C (single hit, dropped)
            _hit(0, 1, 3.0, 4.0, 10.0),  # track A, hit 2
            _hit(0, 2, 5.0, 5.0, 15.0),  # track B, hit 1
        ],
    )


def write_long_dataset(directory: str) -> str:
    """Three straight tracks of four hits each, starting far apart.

    gymnasium's env_checker steps once per reset and rejects an environment that
    truncates after a single step, so nothing here may be a two-hit track.
    """
    hits = []
    for track_id, x in enumerate((0.0, 100.0, 200.0), start=1):
        hits += [_hit(0, track_id, x, 0.0, 10.0 * step) for step in range(4)]
    return _record(directory, hits)


def test_recorded_file_name_and_row_index(tmp_path):
    path = write_dataset(str(tmp_path))
    table = pq.read_table(path)

    # One file per server run, and two servers started in the same second do not
    # collide.
    assert os.path.basename(path).endswith(f"-{os.getpid()}.parquet")

    # The row counter keeps counting across flushes and does not overflow.
    assert table.num_rows == 6
    assert table.schema.field("row_index").type == pa.int64()
    assert table.column("row_index").to_pylist() == [0, 1, 2, 3, 4, 5]
    assert table.schema.field("event_id").type == pa.int32()


def test_episode_segmentation(tmp_path):
    path = write_dataset(str(tmp_path))
    tracks = load_tracks(path)

    assert len(tracks) == 2, "the single-hit track must be dropped"
    assert [(t.event_id, t.track_id) for t in tracks] == [(0, 1), (0, 2)]
    assert [len(t) for t in tracks] == [3, 2]

    # Track A was recorded interleaved; row_index defines the order.
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

    # Both boxes are bounded by the data, not by infinity.
    assert np.isfinite(env.observation_space.low).all()
    assert np.isfinite(env.observation_space.high).all()
    # x runs from 0 to 5 mm and e_kin is 1000 MeV everywhere, plus the margin.
    np.testing.assert_allclose(env.observation_space.low[0], -50.0)
    np.testing.assert_allclose(env.observation_space.high[0], 55.0)
    np.testing.assert_allclose(env.observation_space.low[-1], 950.0)
    np.testing.assert_allclose(env.observation_space.high[-1], 1050.0)

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

    # A perfect prediction of the last hit scores zero and exhausts the
    # recording, which is a truncation and never a termination.
    _, reward, terminated, truncated, _ = env.step([3.0, 4.0, 10.0])
    assert reward == 0.0
    assert truncated and not terminated

    with pytest.raises(RuntimeError):
        env.step([0.0, 0.0, 0.0])

    # An episode has one step less than it has hits.
    assert env.episode_length(0) == 2
    assert env.episode_length(1) == 1


def test_unknown_episode_is_an_error(tmp_path):
    env = TrackPredictionEnv(write_dataset(str(tmp_path)))

    assert env.num_episodes == 2
    with pytest.raises(IndexError):
        env.reset(options={"episode": 2})
    with pytest.raises(IndexError):
        env.reset(options={"episode": -1})


def test_epochs_cover_every_track(tmp_path):
    path = write_long_dataset(str(tmp_path))

    ordered = TrackPredictionEnv(path)
    assert [ordered.reset()[1]["episode"] for _ in range(6)] == [0, 1, 2, 0, 1, 2]

    def shuffled_run():
        env = TrackPredictionEnv(path, shuffle=True)
        return [env.reset(seed=7 if i == 0 else None)[1]["episode"] for i in range(6)]

    seen = shuffled_run()
    # Sampling must not starve a track: every epoch is a permutation.
    assert sorted(seen[:3]) == [0, 1, 2]
    assert sorted(seen[3:]) == [0, 1, 2]
    # Seeding once at the start of a run reproduces the whole sequence.
    assert shuffled_run() == seen


@pytest.mark.parametrize("shuffle", [False, True])
def test_gymnasium_api_and_seeded_reset(tmp_path, shuffle):
    path = write_long_dataset(str(tmp_path))
    env = gymnasium.make(ENV_ID, dataset=path, shuffle=shuffle).unwrapped

    check_env(env)

    first, _ = env.reset(seed=42)
    env.reset()  # a seeded reset must ignore whatever ran before it
    env.reset()
    again, _ = env.reset(seed=42)
    np.testing.assert_array_equal(first, again)
