# rl4phy_env

Gymnasium environment over recorded Geant4 step data (issue #27, v0).

The project goal is to compare learned surrogate models against Geant4 on the
MUonE setup. That comparison needs two things: ground truth from the simulation,
and a fixed task with a number attached to it. This package provides the second
one on top of the parquet files written by `python/dataset_writer.py`.

## Scope of v0

The environment replays recorded data instead of driving Geant4. This is a
deliberate limitation: the gRPC link is one-way today (Geant4 pushes step hits,
nothing can ask it to advance a specific track), so there is no way to step a
live simulation from Python yet. Replay is enough to train and score surrogates
offline against ground truth, and the interface does not change once the
bidirectional control exists — only the source of the next hit does.

## Task

One episode is one particle track, i.e. all hits sharing an `(event_id,
track_id)` key, ordered by the `step_index` written by the sink. Tracks with a
single hit are skipped.

| | |
|---|---|
| observation | `(x, y, z, px, py, pz, e_kin)` of the current hit — mm, MeV/c, MeV |
| action | `(x, y, z)` predicted for the next hit, in mm |
| reward | `-‖prediction − truth‖` in mm |
| terminated | the current observation is the last hit of the track |
| truncated | unused |

The action space is the bounding box of the positions in the dataset plus a
margin, so that `action_space.sample()` is a meaningful random baseline rather
than noise around the origin.

## Usage

```bash
pip install -r python/requirements-ml.txt

# record a dataset first (from the repository root)
docker compose run -d -e RL4PHY_DATASET_DIR=/tmp/ds --service-ports python
docker compose up geant
docker cp <python-container>:/tmp/ds/steps-<ts>.parquet .

cd python
python -m pytest rl4phy_env/test_track_env.py
python -m rl4phy_env.demo_random_agent --dataset ../steps-<ts>.parquet
```

`demo_random_agent.py` scores two policies on the same episodes: uniform random
actions, and persistence (predict that the particle stays where it is). The
persistence error in mm is the first benchmark number for the project — the
cheapest possible surrogate, and the bar a trained model has to clear.

```python
from rl4phy_env import TrackPredictionEnv

env = TrackPredictionEnv("steps-1753560000.parquet", shuffle=True)
observation, info = env.reset(seed=0)
observation, reward, terminated, truncated, info = env.step([0.0, 0.0, 0.0])
```

## Known limitations

- Only `StepHit` messages are recorded; the B1 `EventScoring` payload is not
  part of the dataset yet.
- Steps are only produced inside the `Station` volumes, so a trajectory is a
  sequence of hits in the trackers, not a continuous path through the detector.
- The reward ignores momentum and energy; a surrogate that gets the position
  right but the kinematics wrong scores perfectly.
