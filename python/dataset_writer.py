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


# Opened by the first crossing, not in __init__, so a run that records nothing
# leaves no file behind.
class ParquetStepWriter:
    def __init__(self, directory: str, flush_rows: int = DEFAULT_FLUSH_ROWS) -> None:
        os.makedirs(directory, exist_ok=True)
        self._directory = directory
        self._flush_rows = flush_rows
        self._files = 0
        self._file: pq.ParquetWriter | None = None
        self._rows: list[tuple] = []
        self.path: str | None = None
        self.rows_written = 0

    def append_step_hit(self, hit) -> None:
        if self._file is None:
            self._open()
        self._rows.append(_step_row(hit))
        if len(self._rows) >= self._flush_rows:
            self.flush()

    def _open(self) -> None:
        self._files += 1
        name = f"{FILE_PREFIX}-{int(time.time())}-{os.getpid()}-{self._files}.parquet"
        self.path = os.path.join(self._directory, name)
        # Written under a temporary name and renamed when complete, so a reader
        # never opens a file without its footer.
        self._file = pq.ParquetWriter(
            f"{self.path}.partial", STEP_SCHEMA, compression="zstd"
        )
        self.rows_written = 0
        logger.info(f"Dataset: recording crossings to {self.path}")

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
        self._file.write_batch(batch)
        self.rows_written += len(self._rows)
        self._rows.clear()

    def close(self) -> None:
        if self._file is None:
            return
        self.flush()
        self._file.close()
        self._file = None
        os.replace(f"{self.path}.partial", self.path)
        logger.info(f"Dataset: wrote {self.rows_written} crossing(s) to {self.path}")


def maybe_create_step_writer(directory: str | None) -> ParquetStepWriter | None:
    if not directory:
        return None
    logger.info(f"Dataset: recording crossings under {directory}")
    return ParquetStepWriter(directory)
