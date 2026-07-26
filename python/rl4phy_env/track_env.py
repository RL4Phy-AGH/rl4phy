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
from gymnasium import spaces

OBSERVATION_COLUMNS = ("x", "y", "z", "px", "py", "pz", "e_kin")
POSITION_SLICE = slice(0, 3)
GROUP_COLUMNS = ("event_id", "track_id")
MIN_HITS_PER_EPISODE = 2

# Random actions are drawn from the action space, so an unbounded box would make
# the random baseline meaningless. The box is the detector volume seen in the
# dataset, padded by this margin.
DEFAULT_ACTION_MARGIN_MM = 50.0


@dataclass(frozen=True)
class Track:
    """One (event_id, track_id) group, ordered by step_index."""

    event_id: int
    track_id: int
    parent_id: int
    pdg: int
    features: np.ndarray  # (n_hits, len(OBSERVATION_COLUMNS)), float32

    @property
    def positions(self) -> np.ndarray:
        return self.features[:, POSITION_SLICE]

    def __len__(self) -> int:
        return int(self.features.shape[0])


def resolve_dataset_files(dataset: str | os.PathLike | list | tuple) -> list[str]:
    """Accept a file, a directory, a glob, or any sequence of those."""
    if isinstance(dataset, (list, tuple)):
        files: list[str] = []
        for entry in dataset:
            files.extend(resolve_dataset_files(entry))
        return sorted(dict.fromkeys(files))

    path = os.fspath(dataset)
    if os.path.isdir(path):
        return sorted(globmodule.glob(os.path.join(path, "*.parquet")))
    if os.path.isfile(path):
        return [path]
    return sorted(globmodule.glob(path))


def load_tracks(
    dataset: str | os.PathLike | list | tuple,
    min_hits: int = MIN_HITS_PER_EPISODE,
) -> list[Track]:
    """Read the dataset and split it into per-track trajectories.

    Tracks shorter than ``min_hits`` cannot produce a prediction and are
    dropped. Track and event ids restart with every server run, so the file a
    row came from is part of the grouping key.
    """
    import pyarrow.parquet as pq

    files = resolve_dataset_files(dataset)
    if not files:
        raise FileNotFoundError(f"No parquet files matched {dataset!r}")

    columns = ("event_id", "track_id", "parent_id", "pdg", "step_index")
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
    order = np.lexsort((data["step_index"], data["track_id"], data["event_id"], run))
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
        if end - start < min_hits:
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
    terminated:  the observation is the last hit of the track
    truncated:   unused, always False

    Episodes are served in dataset order; with ``shuffle=True`` they are drawn
    with the environment's RNG, so ``reset(seed=...)`` makes a run reproducible.
    ``reset(options={"episode": i})`` selects a specific track, which is what the
    evaluation script uses to score two policies on the same episodes.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        dataset: str | os.PathLike | list | tuple,
        shuffle: bool = False,
        min_hits: int = MIN_HITS_PER_EPISODE,
        action_margin_mm: float = DEFAULT_ACTION_MARGIN_MM,
    ) -> None:
        super().__init__()
        self.tracks = load_tracks(dataset, min_hits=min_hits)
        if not self.tracks:
            raise ValueError(
                f"{dataset!r} contains no track with at least {min_hits} hits"
            )

        self.shuffle = shuffle
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(len(OBSERVATION_COLUMNS),),
            dtype=np.float32,
        )

        positions = np.concatenate([track.positions for track in self.tracks])
        self.action_space = spaces.Box(
            low=positions.min(axis=0) - action_margin_mm,
            high=positions.max(axis=0) + action_margin_mm,
            dtype=np.float32,
        )

        self._next_episode = 0
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

        index = None if options is None else options.get("episode")
        if index is None:
            if self.shuffle:
                index = int(self.np_random.integers(len(self.tracks)))
            else:
                index = self._next_episode % len(self.tracks)
                self._next_episode += 1

        self._track_index = int(index) % len(self.tracks)
        self._track = self.tracks[self._track_index]
        self._hit = 0
        return self._observation(), self._info()

    def step(self, action):
        if self._track is None:
            raise RuntimeError("reset() must be called before step()")
        if self._hit >= len(self._track) - 1:
            raise RuntimeError("the episode is over, call reset()")

        target = self._track.positions[self._hit + 1]
        prediction = np.asarray(action, dtype=np.float32).reshape(3)
        distance = float(np.linalg.norm(prediction - target))

        self._hit += 1
        terminated = self._hit == len(self._track) - 1
        info = self._info()
        info["distance_mm"] = distance
        return self._observation(), -distance, terminated, False, info

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
