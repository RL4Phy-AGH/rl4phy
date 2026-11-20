import argparse
import glob
import os
import sys

import numpy as np
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq
from loguru import logger

from dataset_writer import CROSSING_SCHEMA, FILE_PREFIX


def crossing_files(source: str) -> list[str]:
    if os.path.isdir(source):
        source = os.path.join(source, f"{FILE_PREFIX}-*.parquet")
    paths = sorted(glob.glob(source))
    if not paths:
        raise FileNotFoundError(f"no crossings found at {source}")
    return paths


def read_crossing_file(path: str) -> pa.Table:
    if path.lower().endswith(".csv"):
        options = pa_csv.ConvertOptions(column_types=CROSSING_SCHEMA)
        return pa_csv.read_csv(path, convert_options=options)
    return pq.read_table(path)


def read_crossings(source: str) -> pa.Table:
    return pa.concat_tables(
        [read_crossing_file(path) for path in crossing_files(source)]
    )


def _momentum(table: pa.Table, point: str) -> np.ndarray:
    return np.column_stack(
        [table[f"{point}_{axis}"].to_numpy() for axis in ("px", "py", "pz")]
    )


def energy_loss(table: pa.Table) -> np.ndarray:
    return table["entry_e"].to_numpy() - table["exit_e"].to_numpy()


def mass(table: pa.Table) -> np.ndarray:
    p = _momentum(table, "entry")
    e = table["entry_e"].to_numpy()
    return np.sqrt(np.maximum(e**2 - np.sum(p**2, axis=1), 0.0))


def scattering_angle(table: pa.Table) -> np.ndarray:
    p_in, p_out = _momentum(table, "entry"), _momentum(table, "exit")
    cross = np.linalg.norm(np.cross(p_in, p_out), axis=1)
    dot = np.sum(p_in * p_out, axis=1)
    return np.arctan2(cross, dot)


def main(source: str) -> None:
    table = read_crossings(source)
    loss = energy_loss(table)
    angle = scattering_angle(table)
    logger.info(f"{table.num_rows} crossing(s) from {source}")
    logger.info(
        f"energy loss: median {np.median(loss):.4f} MeV, "
        f"1-99 % {np.percentile(loss, 1):.4f}..{np.percentile(loss, 99):.4f} MeV"
    )
    logger.info(f"scattering angle: rms {np.sqrt(np.mean(angle**2)):.3e} rad")
    logger.info(f"mass: mean {np.mean(mass(table)):.4f} MeV")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout)
    parser = argparse.ArgumentParser(description="Summarise recorded crossings.")
    parser.add_argument("source", help="directory with recordings, a file or a glob")
    main(parser.parse_args().source)
