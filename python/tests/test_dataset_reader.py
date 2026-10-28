import math
import os

import numpy as np
import pytest

from dataset_reader import energy_loss, mass, read_crossings, theta, theta_xy
from dataset_writer import ParquetStepWriter
from parquet_to_csv import main as parquet_to_csv
from test_client import MASS_MU, STATION_10MM, fake_crossings

# Median of the standard Moyal distribution the generator draws from.
MOYAL_MEDIAN = 0.7876


@pytest.fixture
def recorded(tmp_path):
    writer = ParquetStepWriter(str(tmp_path), flush_rows=64)
    for hit in fake_crossings(2000, seed=3):
        writer.append_step_hit(hit)
    writer.close()
    return tmp_path


def test_reads_a_directory_a_file_or_a_glob_and_skips_partial_files(recorded):
    (recorded / "crossings-0-0-9.parquet.partial").write_bytes(b"")
    assert read_crossings(str(recorded)).num_rows == 2000
    assert read_crossings(str(recorded / "crossings-*.parquet")).num_rows == 2000
    [name] = [p for p in os.listdir(recorded) if p.endswith(".parquet")]
    assert read_crossings(str(recorded / name)).num_rows == 2000
    with pytest.raises(FileNotFoundError):
        read_crossings(str(recorded / "nothing-*.parquet"))


def test_derived_quantities_match_the_generator(recorded):
    table = read_crossings(str(recorded))
    layer = STATION_10MM

    loss = energy_loss(table)
    assert np.all(loss > 0.0)
    assert abs(np.median(loss) - (layer.mpv_mev + MOYAL_MEDIAN * layer.xi_mev)) < 0.03

    rms = math.sqrt(np.mean(theta(table) ** 2))
    assert abs(rms / (math.sqrt(2.0) * layer.theta0_rad) - 1.0) < 0.1
    theta_x, theta_y = theta_xy(table)
    assert abs(np.std(theta_x) / layer.theta0_rad - 1.0) < 0.1
    assert abs(np.std(theta_y) / layer.theta0_rad - 1.0) < 0.1

    assert np.allclose(mass(table), MASS_MU, atol=1e-3)


def test_csv_round_trip(recorded):
    parquet_to_csv([str(recorded)])
    [csv] = [p for p in os.listdir(recorded) if p.endswith(".csv")]
    [parquet] = [p for p in os.listdir(recorded) if p.endswith(".parquet")]
    assert (recorded / csv).with_suffix(".parquet") == recorded / parquet
    assert read_crossings(str(recorded / csv)).equals(read_crossings(str(recorded)))
