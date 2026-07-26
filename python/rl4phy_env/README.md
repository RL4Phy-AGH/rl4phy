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
track_id)` key, ordered by the `row_index` written by the sink. Tracks with a
single hit are skipped.

| | |
|---|---|
| observation | `(x, y, z, px, py, pz, e_kin)` of the current hit — mm, MeV/c, MeV |
| action | `(x, y, z)` predicted for the next hit, in mm |
| reward | `-‖prediction − truth‖` in mm |
| terminated | never |
| truncated | the recorded hits of the track are exhausted |

Running out of recorded hits is not a terminal state of the process being
modelled — the particle carries on, only the recording stops — so the episode
ends truncated, which keeps a bootstrapping learner from setting the value of the
last observed state to zero.

Both spaces are the bounding box of the loaded data plus a margin. For the action
space that is what makes `action_space.sample()` a meaningful random baseline
rather than noise around the origin; for the observation space it is a bound on
what a recording contains, not a physical claim.

Episodes are served in epochs: one pass visits every track exactly once, in
dataset order, or in an order drawn from the environment's RNG with
`shuffle=True`. `reset(seed=...)` starts a fresh epoch, so a seeded run is
reproducible.

## Usage

Record a dataset first. `RL4PHY_DATASET_DIR` is passed through to the python
service, and `/datasets` inside the container is bound to `./datasets` on the
host, so the parquet files show up next to the compose file (from the repository
root):

```bash
RL4PHY_DATASET_DIR=/datasets docker compose up --build
```

```powershell
$env:RL4PHY_DATASET_DIR="/datasets"; docker compose up --build
```

Stopping the stack (`docker compose down`, or Ctrl-C) closes the file; without
`RL4PHY_DATASET_DIR` nothing is written at all. `datasets/` is gitignored.

```bash
pip install -r python/requirements-ml.txt

cd python
python -m pytest rl4phy_env/
python -m rl4phy_env.demo_random_agent --dataset ../datasets
```

`demo_random_agent.py` scores three policies on the same episodes: uniform random
actions, persistence (predict that the particle stays where it is), and drift
(persistence plus a constant step along z, its length averaged over the evaluated
tracks). Errors are reported split into a transverse `(x, y)` and a longitudinal
`(z)` part. persistence is the first benchmark number for the project — the
cheapest possible surrogate, and the bar a trained model has to clear. drift fits
its single parameter on the tracks it is scored on, so its number is a lower
bound for a constant-step model rather than a held-out result.

```python
import gymnasium

import rl4phy_env  # registers the id

env = gymnasium.make("Rl4Phy/TrackPrediction-v0", dataset="datasets", shuffle=True)
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
