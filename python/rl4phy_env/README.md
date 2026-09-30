# rl4phy_env

Gymnasium environment over recorded Geant4 step data (issue #27, v0). It replays
the parquet files written by `python/dataset_writer.py`; driving Geant4 live
needs a two-way gRPC link that does not exist yet, and the interface will not
change when it does.

## Task

One episode is one track: all hits sharing `(event_id, track_id)`, ordered by
`row_index`. Single-hit tracks are skipped.

| | |
|---|---|
| observation | `(x, y, z, px, py, pz, e_kin)` of the current hit (mm, MeV/c, MeV) |
| action | `(x, y, z)` predicted for the next hit, in mm |
| reward | `-‖prediction − truth‖` in mm |
| terminated | never |
| truncated | the recorded hits of the track are exhausted |

Both spaces are the bounding box of the data plus a margin. Episodes are served
in epochs (every track once, shuffled with `shuffle=True`); `reset(seed=...)`
starts a fresh epoch.

## Usage

Record a dataset from the repository root; `datasets/` is gitignored and nothing
is written without the variable:

```bash
RL4PHY_DATASET_DIR=/datasets docker compose up --build
```

```powershell
$env:RL4PHY_DATASET_DIR="/datasets"; docker compose up --build
```

Then, from `python/`:

```bash
uv sync
uv run pytest rl4phy_env/
uv run python -m rl4phy_env.benchmark --dataset ../datasets
```

`benchmark.py` scores the agents from `agents/` (random, persistence, drift) on
the same episodes, with the error split into a transverse `(x, y)` and a
longitudinal `(z)` part. Each agent is a plain class with a `name` and an
`act(observation) -> (x, y, z)` method in its own file; to try your own model,
copy one, implement `act` and add it to the `agents` tuple in `benchmark.py`.

```python
import gymnasium

import rl4phy_env  # registers the id

env = gymnasium.make("Rl4Phy/TrackPrediction-v0", dataset="datasets", shuffle=True)
observation, info = env.reset(seed=0)
observation, reward, terminated, truncated, info = env.step([0.0, 0.0, 0.0])
```

## Known limitations

- Only `StepHit` messages are recorded, and since #37 no example sends them
  until #45 lands.
- Steps are only produced inside the `Station` volumes, so a trajectory is a
  sequence of tracker hits, not a continuous path.
- The reward ignores momentum and energy.
