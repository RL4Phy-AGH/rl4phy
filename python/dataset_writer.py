"""Parquet sink for the streamed step hits (first piece of issue #17).

Opt-in through the RL4PHY_DATASET_DIR environment variable: when it points at a
writable directory the server dumps every StepHit it receives into
``<dir>/steps-<unix-ts>.parquet``, one file per server run. With the variable
unset (the default) nothing is imported and nothing is written, so the gRPC path
behaves exactly as before.

The recorded files are the input of ``python/rl4phy_env``, which replays them as
RL episodes.
"""

from __future__ import annotations

import atexit
import os
import signal
import threading
import time

ENV_DATASET_DIR = "RL4PHY_DATASET_DIR"
DEFAULT_FLUSH_ROWS = 1000

# Column order is also the parquet column order.
_ID_COLUMNS = ("event_id", "track_id", "parent_id", "pdg")
_KINEMATIC_COLUMNS = ("x", "y", "z", "px", "py", "pz", "e_kin")
# Geant4 streams the steps of a track in step order over a synchronous unary
# RPC, so arrival order is step order. step_index freezes that order in the file
# instead of relying on the row order surviving every parquet reader.
_ORDER_COLUMN = "step_index"

STEP_COLUMNS = _ID_COLUMNS + _KINEMATIC_COLUMNS + (_ORDER_COLUMN,)


def step_schema():
    import pyarrow as pa

    fields = [pa.field(name, pa.int32()) for name in _ID_COLUMNS]
    fields += [pa.field(name, pa.float32()) for name in _KINEMATIC_COLUMNS]
    fields.append(pa.field(_ORDER_COLUMN, pa.int32()))
    return pa.schema(fields)


class ParquetStepWriter:
    """Buffered parquet writer for StepHit messages.

    pyarrow is imported here rather than at module scope so that a server run
    without RL4PHY_DATASET_DIR never pays for it.
    """

    def __init__(self, directory: str, flush_rows: int = DEFAULT_FLUSH_ROWS) -> None:
        import pyarrow.parquet as pq

        os.makedirs(directory, exist_ok=True)
        self.path = os.path.join(directory, f"steps-{int(time.time())}.parquet")
        self._flush_rows = flush_rows
        self._schema = step_schema()
        self._writer = pq.ParquetWriter(self.path, self._schema)
        self._buffer: dict[str, list] = {name: [] for name in STEP_COLUMNS}
        self._buffered = 0
        self.rows_written = 0
        self._lock = threading.Lock()
        self._closed = False

    def append_step_hit(self, hit) -> None:
        with self._lock:
            if self._closed:
                return
            for name in _ID_COLUMNS + _KINEMATIC_COLUMNS:
                self._buffer[name].append(getattr(hit, name))
            self._buffer[_ORDER_COLUMN].append(self.rows_written + self._buffered)
            self._buffered += 1
            if self._buffered >= self._flush_rows:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._buffered == 0:
            return
        import pyarrow as pa

        batch = pa.record_batch(
            [
                pa.array(self._buffer[field.name], type=field.type)
                for field in self._schema
            ],
            schema=self._schema,
        )
        self._writer.write_batch(batch)
        for column in self._buffer.values():
            column.clear()
        self.rows_written += self._buffered
        self._buffered = 0

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._flush_locked()
            self._writer.close()
            self._closed = True
        print(f"Dataset: wrote {self.rows_written} step row(s) to {self.path}")


def _flush_on_sigterm(writer: ParquetStepWriter) -> None:
    """`docker stop` sends SIGTERM, and Python's default handler skips atexit,
    which would drop everything still sitting in the buffer."""
    previous = signal.getsignal(signal.SIGTERM)

    def handler(signum, frame):
        writer.close()
        if callable(previous):
            previous(signum, frame)
        else:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    try:
        signal.signal(signal.SIGTERM, handler)
    except ValueError:
        # Not the main thread; atexit still covers the ordinary shutdown.
        pass


def maybe_create_step_writer() -> ParquetStepWriter | None:
    """Return a writer if RL4PHY_DATASET_DIR is set, otherwise None."""
    directory = os.environ.get(ENV_DATASET_DIR)
    if not directory:
        return None

    writer = ParquetStepWriter(directory)
    atexit.register(writer.close)
    _flush_on_sigterm(writer)
    print(f"Dataset: recording step hits to {writer.path}")
    return writer
