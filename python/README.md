# Python

The gRPC server that receives what the Geant4 side sends: it records layer
crossings to Parquet and draws geometry and trajectories in Rerun. Dependencies
are managed with [uv](https://docs.astral.sh/uv/); `uv.lock` is the source of
truth and the Docker image installs from it, so keep it committed.

| File | Role |
|---|---|
| `server.py` | entry point: reads the environment, one handler per payload of `proto/rl4phy.proto` |
| `rerun_view.py` | everything that talks to Rerun: the connection, geometry, trajectories |
| `gdml_geometry.py` | turns the GDML sent at the start of a run into drawable solids |
| `dataset_writer.py` | records `StepHit` crossings, one Parquet file per Geant4 job |
| `dataset_reader.py` | reads recordings back, Parquet or CSV, and derives energy loss, scattering angle and mass |
| `parquet_to_csv.py` | exports a recording to CSV (#38) |
| `test_client.py` | sends fake data, including generated crossings, to a running server |
| `tests/` | the pytest suite |
| `rl4phy_env/` | the Gymnasium environment from #31; it still reads the columns from before #45 |

## Setup

```sh
uv sync                  # create .venv and install locked deps (including dev)
```

uv reads `.python-version` (3.12, matching the image) and fetches that
interpreter if it is missing. Nothing needs activating - prefix commands with
`uv run`.

`rl4phy_pb2.py` and `rl4phy_pb2_grpc.py` are generated from
`proto/rl4phy.proto` and not committed; the Docker image builds its own.
Generate them after `uv sync` and again whenever the proto changes:

```sh
uv run python -m grpc_tools.protoc -I../proto \
    --python_out=. --grpc_python_out=. ../proto/rl4phy.proto
```

Never edit them by hand.

Adding or removing a dependency goes through uv, never by hand:

```sh
uv add loguru
uv remove loguru
uv add --dev ruff       # dev-only tools
```

## Running

```sh
uv run python -m rerun   # the viewer, listening on port 9876
uv run server.py         # the server, in another terminal
```

The server sends its drawing to a Rerun viewer, by default the one on this
machine. Under docker compose (from the repository root, `docker compose up
--build`) the viewer is its own service and runs in the browser at
http://localhost:9090. `RERUN=off` in the server's environment turns drawing
off.

| Variable | Meaning |
|---|---|
| `RL4PHY_DATASET_DIR` | directory for the Parquet recordings; unset means nothing is recorded |
| `RL4PHY_RERUN_URL` | where the Rerun viewer listens (default `rerun+http://127.0.0.1:9876/proxy`); compose points it at the `rerun` service |
| `RL4PHY_MAX_LABELS` | draw labels when an event or a geometry group has at most this many items (default 0) |

## Recording crossings

With `RL4PHY_DATASET_DIR` set the server writes one file per Geant4 job as
`crossings-<time>-<pid>-<n>.parquet`: it opens with the first crossing and
closes when the last of the job's streams ends (a job opens one per worker
thread). The file is written under a `.partial` name and renamed when complete,
so an unfinished one is never read by mistake. Each row is one
`StepHit`: `event_id`, `track_id`, `parent_id`, `pdg`, `volume`, the
four-momentum at entry and exit (`entry_e`, `entry_px`, `entry_py`, `entry_pz`
and the same for `exit`; MeV, doubles) and `path_length` in mm.

Today the only sender of crossings is `test_client.py`; the Geant4 side starts
sending them under #45, so a compose run with `RL4PHY_DATASET_DIR` set records
nothing yet.

```sh
uv run dataset_reader.py ../datasets     # a directory, a file or a glob; prints a summary
uv run parquet_to_csv.py ../datasets     # a .csv next to each file
```

`dataset_reader.read_crossings` takes a directory (its `crossings-*.parquet`
files), a file or a glob, reads Parquet or a `.csv` written by
`parquet_to_csv.py`, and returns a pyarrow table; `energy_loss`, `theta`,
`theta_xy` and `mass` derive the physics from it. The energy loss is what the
particle lost, including what its secondaries carried away, not what the layer
absorbed.

## Trying it without Geant4

```sh
RL4PHY_DATASET_DIR=/tmp/crossings uv run server.py   # terminal A, with the viewer up or RERUN=off
uv run test_client.py 10000                           # terminal B: 10000 fake crossings
uv run test_client.py 1000 plane                      # the 300 um plane instead of the 10 mm station
```

`test_client.py` draws the energy loss of a 160 GeV muon from a Moyal
distribution and the scattering angles from the Highland formula, so a
recording of it has the right medians and widths to check the reader against.

## Tests

```sh
uv run pytest
```

The tests build messages from the generated stubs, so generate them first (see
Setup). The `rl4phy_env` tests are skipped until the environment is rebuilt
under #33.

## Formatting and linting

[ruff](https://docs.astral.sh/ruff/) does both, configured in `pyproject.toml`.

```sh
uv run ruff format .     # format
uv run ruff check .      # lint
uv run ruff check --fix .
```

Run both before opening a PR. The lint rules encode the style guide below:
`T20` rejects `print`, `I`/`E402`/`PLC0415` keep imports at the top and sorted,
`UP031`/`UP032` reject `%` and `.format` in favour of f-strings.

## Style guide

### No `print`

Use [loguru](https://github.com/Delgan/loguru) for all output.

```python
# bad
print("server started")

# good
from loguru import logger

logger.info("server started")
```

Pick a level that matches the message: `debug`, `info`, `warning`, `error`.

Entry points (`server.py`, `test_client.py`, `dataset_reader.py`,
`parquet_to_csv.py`) send the log to stdout; loguru's default would be stderr.

### Imports at the top

All imports go at the top of the file, never inside functions or conditionals.

```python
# bad
def load():
    import json

    ...


# good
import json


def load(): ...
```

### f-strings for formatting

```python
# bad
"run %d of %d" % (i, n)
"run {} of {}".format(i, n)
"run " + str(i)

# good
f"run {i} of {n}"
```

### Almost no comments

Default to none. Fix the naming or the structure instead - if the code needs a
sentence to be readable, rewrite the code. A comment is a last resort for a
*why* that cannot live in the code at all: an external constraint, a workaround,
a decision someone would otherwise undo. No docstrings on obvious functions, no
section banners, no restating the line below.

```python
# bad
# increment the counter
counter += 1

# ok - the reason is nowhere in the code
# MUonE marks no end of event, so a quiet stream has to flush on a timer.
TRACK_IDLE_FLUSH_S = 1.0
```

Delete commented-out code; git remembers it.
