import os
import time

import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

FILE_PREFIX = "crossings"
DEFAULT_FLUSH_ROWS = 65536

CROSSING_SCHEMA = pa.schema(
    [
        ("event_id", pa.int32()),
        ("track_id", pa.int32()),
        ("parent_id", pa.int32()),
        ("pdg", pa.int32()),
        ("volume", pa.string()),
        ("entry_e", pa.float64()),
        ("entry_px", pa.float64()),
        ("entry_py", pa.float64()),
        ("entry_pz", pa.float64()),
        ("exit_e", pa.float64()),
        ("exit_px", pa.float64()),
        ("exit_py", pa.float64()),
        ("exit_pz", pa.float64()),
        ("path_length", pa.float32()),
    ]
)


def _crossing_row(hit) -> dict:
    entry, exit_ = hit.entry, hit.exit
    return {
        "event_id": hit.event_id,
        "track_id": hit.track_id,
        "parent_id": hit.parent_id,
        "pdg": hit.pdg,
        "volume": hit.volume,
        "entry_e": entry.e,
        "entry_px": entry.px,
        "entry_py": entry.py,
        "entry_pz": entry.pz,
        "exit_e": exit_.e,
        "exit_px": exit_.px,
        "exit_py": exit_.py,
        "exit_pz": exit_.pz,
        "path_length": hit.path_length,
    }


class ParquetStepWriter:
    def __init__(self, directory: str, flush_rows: int = DEFAULT_FLUSH_ROWS) -> None:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"Dataset: recording crossings under {directory}")
        self._directory = directory
        self._flush_rows = flush_rows
        self._files_opened = 0
        self._file: pq.ParquetWriter | None = None
        self._rows: list[dict] = []
        self.path: str | None = None
        self.rows_written = 0

    def append_step_hit(self, hit) -> None:
        if self._file is None:
            self._open()
        self._rows.append(_crossing_row(hit))
        if len(self._rows) >= self._flush_rows:
            self.flush()

    def _open(self) -> None:
        self._files_opened += 1
        name = f"{FILE_PREFIX}-{int(time.time())}-{self._files_opened}.parquet"
        self.path = os.path.join(self._directory, name)
        self._file = pq.ParquetWriter(
            f"{self.path}.partial", CROSSING_SCHEMA, compression="zstd"
        )
        self.rows_written = 0

    def flush(self) -> None:
        if not self._rows:
            return
        self._file.write_batch(
            pa.RecordBatch.from_pylist(self._rows, schema=CROSSING_SCHEMA)
        )
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
