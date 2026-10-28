import os
import time

import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

FILE_PREFIX = "crossings"
# One row group per flush. At about 40 bytes a row, 1000 rows made a row group
# every 40 kB, far below what Parquet readers want; 65536 rows is about 3 MB.
DEFAULT_FLUSH_ROWS = 65536

STEP_SCHEMA = pa.schema(
    [
        ("event_id", pa.int32()),
        ("track_id", pa.int32()),
        ("parent_id", pa.int32()),
        ("pdg", pa.int32()),
        ("volume", pa.string()),
        # float64 and not float32: one float32 step at 160 GeV is 15.6 keV, which
        # would quantise an 84 keV Landau peak.
        *[
            (f"{point}_{axis}", pa.float64())
            for point in ("entry", "exit")
            for axis in ("e", "px", "py", "pz")
        ],
        ("path_length", pa.float32()),
    ]
)


def _step_row(hit) -> tuple:
    entry, exit_ = hit.entry, hit.exit
    return (
        hit.event_id,
        hit.track_id,
        hit.parent_id,
        hit.pdg,
        hit.volume,
        entry.e,
        entry.px,
        entry.py,
        entry.pz,
        exit_.e,
        exit_.px,
        exit_.py,
        exit_.pz,
        hit.path_length,
    )


class ParquetStepWriter:
    def __init__(self, directory: str, flush_rows: int = DEFAULT_FLUSH_ROWS) -> None:
        os.makedirs(directory, exist_ok=True)
        name = f"{FILE_PREFIX}-{int(time.time())}-{os.getpid()}.parquet"
        self.path = os.path.join(directory, name)
        self._flush_rows = flush_rows
        self._writer = pq.ParquetWriter(self.path, STEP_SCHEMA, compression="zstd")
        self._rows: list[tuple] = []
        self.rows_written = 0
        self._closed = False

    def append_step_hit(self, hit) -> None:
        if self._closed:
            return
        self._rows.append(_step_row(hit))
        if len(self._rows) >= self._flush_rows:
            self.flush()

    def flush(self) -> None:
        if not self._rows:
            return
        columns = zip(*self._rows, strict=True)
        batch = pa.record_batch(
            [
                pa.array(column, type=field.type)
                for column, field in zip(columns, STEP_SCHEMA, strict=True)
            ],
            schema=STEP_SCHEMA,
        )
        self._writer.write_batch(batch)
        self.rows_written += len(self._rows)
        self._rows.clear()

    def close(self) -> None:
        if self._closed:
            return
        self.flush()
        self._writer.close()
        self._closed = True
        logger.info(f"Dataset: wrote {self.rows_written} crossing(s) to {self.path}")


def maybe_create_step_writer(directory: str | None) -> ParquetStepWriter | None:
    if not directory:
        return None
    writer = ParquetStepWriter(directory)
    logger.info(f"Dataset: recording crossings to {writer.path}")
    return writer
