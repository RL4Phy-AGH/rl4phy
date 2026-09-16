# Python

The Rerun-facing gRPC server. Dependencies are managed with
[uv](https://docs.astral.sh/uv/); `uv.lock` is the source of truth and the
Docker image installs from it, so keep it committed.

## Setup

```sh
uv sync                  # create .venv and install locked deps (including dev)
```

uv reads `.python-version` (3.11, matching the image) and fetches that
interpreter if it is missing. Nothing needs activating - prefix commands with
`uv run`.

Then generate the gRPC stubs. `rl4phy_pb2.py` and `rl4phy_pb2_grpc.py` are
build outputs, not sources: they are gitignored, so a fresh checkout has none
and `server.py` fails with `No module named rl4phy_pb2` until this has run.
Re-run it whenever `proto/rl4phy.proto` changes.

```sh
uv run python -m grpc_tools.protoc -I../proto \
    --python_out=. --grpc_python_out=. ../proto/rl4phy.proto
```

```sh
uv run server.py         # run the server
```

Adding or removing a dependency goes through uv, never by hand:

```sh
uv add loguru
uv remove loguru
uv add --dev ruff       # dev-only tools
```

## Formatting and linting

[ruff](https://docs.astral.sh/ruff/) does both, configured in `pyproject.toml`.

```sh
uv run ruff format .     # format
uv run ruff check .      # lint
uv run ruff check --fix .
```

Run both before opening a PR. The lint rules encode the style guide below:
`T20` rejects `print`, `I`/`E402` keep imports at the top and sorted, `UP031`/
`UP032` reject `%` and `.format` in favour of f-strings.

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

Exception: loguru supports lazy formatting, so prefer braces with arguments in log calls.

```python
logger.info("run {} of {}", i, n)
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
