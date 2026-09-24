"""Replay environment over recorded Geant4 step hits.

An episode is one particle track. The agent sees the current hit and predicts
where the particle will be at the next hit; the reward is minus the distance to
the true position. The data comes from parquet files written by
``python/dataset_writer.py``.

Units follow the wire format of the StepHit message: positions in mm, momenta in
MeV/c, kinetic energy in MeV.
"""

from __future__ import annotations

import glob as globmodule
import os
from dataclasses import dataclass

import gymnasium as gym
import numpy as np
import pyarrow.parquet as pq
from gymnasium import spaces

OBSERVATION_COLUMNS = ("x", "y", "z", "px", "py", "pz", "e_kin")
POSITION_INDICES = tuple(OBSERVATION_COLUMNS.index(name) for name in ("x", "y", "z"))
ORDER_COLUMN = "row_index"
MIN_HITS_PER_EPISODE = 2

# Both boxes are the bounding box of the loaded data, padded by this margin in
# each column's own unit (mm, MeV/c, MeV). They are loose bounds on what the
# recording contains, not a physical claim. The action box is the one that
# matters: random actions are drawn from it, so an unbounded box would make the
# random baseline meaningless.
BOX_MARGIN = 50.0


def positions_of(observations: np.ndarray) -> np.ndarray:
    """The (x, y, z) columns of one observation or of a stack of them."""
    return observations[..., POSITION_INDICES]


@dataclass(frozen=True)
class Track:
    """One (event_id, track_id) group, ordered by the recorded row_index."""

    event_id: int
    track_id: int
    parent_id: int
    pdg: int
    features: np.ndarray  # (n_hits, len(OBSERVATION_COLUMNS)), float32

    @property
    def positions(self) -> np.ndarray:
        return positions_of(self.features)

    def __len__(self) -> int:
        return int(self.features.shape[0])


def resolve_dataset_files(dataset: str | os.PathLike) -> list[str]:
    """Resolve one parquet file, a directory of them, or a glob pattern."""
    path = os.fspath(dataset)
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        path = os.path.join(path, "*.parquet")
    return sorted(globmodule.glob(path))


def load_tracks(dataset: str | os.PathLike) -> list[Track]:
    """Read the dataset and split it into per-track trajectories.

    Tracks shorter than ``MIN_HITS_PER_EPISODE`` cannot produce a prediction and
    are dropped. Track and event ids restart with every server run, so the file a
    row came from is part of the grouping key.
    """
    files = resolve_dataset_files(dataset)
    if not files:
        raise FileNotFoundError(f"No parquet files matched {dataset!r}")

    columns = ("event_id", "track_id", "parent_id", "pdg", ORDER_COLUMN)
    columns += OBSERVATION_COLUMNS
    tables = [pq.read_table(path, columns=list(columns)) for path in files]

    def column(name: str) -> np.ndarray:
        return np.concatenate(
            [table.column(name).to_numpy(zero_copy_only=False) for table in tables]
        )

    data = {name: column(name) for name in columns}
    run = np.concatenate(
        [np.full(table.num_rows, i, dtype=np.int64) for i, table in enumerate(tables)]
    )
    if run.size == 0:
        return []

    # np.lexsort sorts by the last key first.
    order = np.lexsort((data[ORDER_COLUMN], data["track_id"], data["event_id"], run))
    run = run[order]
    data = {name: values[order] for name, values in data.items()}

    features = np.stack(
        [data[name].astype(np.float32) for name in OBSERVATION_COLUMNS], axis=1
    )

    keys = np.stack([run, data["event_id"], data["track_id"]], axis=1)
    boundaries = np.flatnonzero(np.any(keys[1:] != keys[:-1], axis=1)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(run)]))

    tracks: list[Track] = []
    for start, end in zip(starts, ends):
        if end - start < MIN_HITS_PER_EPISODE:
            continue
        tracks.append(
            Track(
                event_id=int(data["event_id"][start]),
                track_id=int(data["track_id"][start]),
                parent_id=int(data["parent_id"][start]),
                pdg=int(data["pdg"][start]),
                features=np.ascontiguousarray(features[start:end]),
            )
        )
    return tracks


class TrackPredictionEnv(gym.Env):
    """Predict the next hit of a recorded track.

    observation: (x, y, z, px, py, pz, e_kin) of the current hit
                 -- mm, MeV/c, MeV
    action:      (x, y, z) predicted for the next hit, in mm
    reward:      -||prediction - truth|| in mm
    terminated:  never, see truncated
    truncated:   the recording of the track is exhausted

    Running out of recorded hits is not a terminal state of the process being
    modelled -- the particle carries on, only the recording stops -- so the
    episode ends truncated. A bootstrapping learner needs that distinction: on
    ``terminated`` it sets the value of the final state to zero, which for a
    track that merely left the last tracker would be wrong.

    Episodes are served in epochs: one pass visits every track exactly once, in
    dataset order, or in an order drawn from the environment's RNG with
    ``shuffle=True``. ``reset(seed=...)`` starts a fresh epoch, so a seeded run
    is reproducible. ``reset(options={"episode": i})`` selects a specific track,
    which is what the evaluation script uses to score policies on the same
    episodes.
    """

    metadata = {"render_modes": []}

    def __init__(self, dataset: str | os.PathLike, shuffle: bool = False) -> None:
        super().__init__()
        self.tracks = load_tracks(dataset)
        if not self.tracks:
            raise ValueError(
                f"{dataset!r} contains no track with at least "
                f"{MIN_HITS_PER_EPISODE} hits"
            )

        self.shuffle = shuffle
        features = np.concatenate([track.features for track in self.tracks])
        self.observation_space = spaces.Box(
            low=features.min(axis=0) - BOX_MARGIN,
            high=features.max(axis=0) + BOX_MARGIN,
            dtype=np.float32,
        )
        positions = positions_of(features)
        self.action_space = spaces.Box(
            low=positions.min(axis=0) - BOX_MARGIN,
            high=positions.max(axis=0) + BOX_MARGIN,
            dtype=np.float32,
        )

        self._epoch: np.ndarray | None = None
        self._cursor = 0
        self._track: Track | None = None
        self._track_index = -1
        self._hit = 0

    @property
    def num_episodes(self) -> int:
        return len(self.tracks)

    def episode_length(self, index: int) -> int:
        """Number of predictions the episode asks for."""
        return len(self.tracks[index]) - 1

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        if seed is not None:
            # Without this, which episode a seeded reset serves would depend on
            # how many resets happened before it.
            self._epoch = None
            self._cursor = 0

        index = None if options is None else options.get("episode")
        if index is None:
            index = self._next_in_epoch()
        else:
            index = int(index)
            if not 0 <= index < len(self.tracks):
                raise IndexError(
                    f"episode {index} out of range, the dataset has "
                    f"{len(self.tracks)} tracks"
                )

        self._track_index = index
        self._track = self.tracks[index]
        self._hit = 0
        return self._observation(), self._info()

    def _next_in_epoch(self) -> int:
        """Serve each track once per epoch, then draw the next epoch."""
        if self._epoch is None or self._cursor >= len(self._epoch):
            self._epoch = (
                self.np_random.permutation(len(self.tracks))
                if self.shuffle
                else np.arange(len(self.tracks))
            )
            self._cursor = 0
        index = int(self._epoch[self._cursor])
        self._cursor += 1
        return index

    def step(self, action):
        if self._track is None:
            raise RuntimeError("reset() must be called before step()")
        if self._hit >= len(self._track) - 1:
            raise RuntimeError("the episode is over, call reset()")

        target = positions_of(self._track.features[self._hit + 1])
        prediction = np.asarray(action, dtype=np.float32).reshape(3)
        distance = float(np.linalg.norm(prediction - target))

        self._hit += 1
        truncated = self._hit == len(self._track) - 1
        info = self._info()
        info["distance_mm"] = distance
        return self._observation(), -distance, False, truncated, info

    def _observation(self) -> np.ndarray:
        assert self._track is not None
        return self._track.features[self._hit].copy()

    def _info(self) -> dict:
        assert self._track is not None
        return {
            "episode": self._track_index,
            "event_id": self._track.event_id,
            "track_id": self._track.track_id,
            "parent_id": self._track.parent_id,
            "pdg": self._track.pdg,
            "hit_index": self._hit,
            "hits": len(self._track),
        }
