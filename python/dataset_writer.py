"""Opt-in parquet sink for StepHit messages, enabled by RL4PHY_DATASET_DIR.

One file per server run, ``<dir>/steps-<unix-ts>-<pid>.parquet``; the files are
the input of ``rl4phy_env``.
"""

from __future__ import annotations

import atexit
import os
import signal
import threading
import time

import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

ENV_DATASET_DIR = "RL4PHY_DATASET_DIR"
DEFAULT_FLUSH_ROWS = 1000

_ID_COLUMNS = ("event_id", "track_id", "parent_id", "pdg")
_KINEMATIC_COLUMNS = ("x", "y", "z", "px", "py", "pz", "e_kin")
# Arrival order is step order; row_index freezes it in the file. A step number
# carried by StepHit itself would be the proper key.
_ORDER_COLUMN = "row_index"

STEP_COLUMNS = _ID_COLUMNS + _KINEMATIC_COLUMNS + (_ORDER_COLUMN,)


def step_schema():
    fields = [pa.field(name, pa.int32()) for name in _ID_COLUMNS]
    fields += [pa.field(name, pa.float32()) for name in _KINEMATIC_COLUMNS]
    # A long run can outgrow int32; the ids cannot.
    fields.append(pa.field(_ORDER_COLUMN, pa.int64()))
    return pa.schema(fields)


class ParquetStepWriter:
    """Buffered parquet writer for StepHit messages.

    The file is readable only after ``close()`` writes the footer; atexit and
    SIGTERM are covered, a SIGKILL loses the whole recording.
    """

    def __init__(self, directory: str, flush_rows: int = DEFAULT_FLUSH_ROWS) -> None:
        os.makedirs(directory, exist_ok=True)
        name = f"steps-{int(time.time())}-{os.getpid()}.parquet"
        self.path = os.path.join(directory, name)
        self._flush_rows = flush_rows
        self._schema = step_schema()
        self._writer = pq.ParquetWriter(self.path, self._schema)
        self._buffer: dict[str, list] = {name: [] for name in STEP_COLUMNS}
        self._buffered = 0
        self.rows_written = 0
        # Reentrant: the SIGTERM handler may call close() from inside append_step_hit().
        self._lock = threading.RLock()
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
        logger.info(f"Dataset: wrote {self.rows_written} step row(s) to {self.path}")


def _flush_on_sigterm(writer: ParquetStepWriter) -> None:
    """SIGTERM (``docker stop``) skips atexit, so close() is hooked here too."""
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
    logger.info(f"Dataset: recording step hits to {writer.path}")
    return writer
