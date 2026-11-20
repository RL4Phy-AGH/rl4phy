import math
import pathlib

import pyarrow as pa
import pytest

import parquet_to_csv
from crossings import energy_loss, mass, read_crossings, scattering_angle
from dataset_writer import ParquetStepWriter
from test_client import ENERGY_LOSS_MEV, MUON_MASS_MEV, SCATTERING_ANGLE_RAD


@pytest.fixture
def recording(tmp_path, crossings):
    writer = ParquetStepWriter(str(tmp_path))
    for hit in crossings:
        writer.append_step_hit(hit)
    writer.close()
    return pathlib.Path(writer.path)


def test_reads_a_directory_a_file_or_a_glob_and_skips_partial_files(
    recording, crossings
):
    directory = recording.parent
    rows = len(crossings)
    (directory / "crossings-0-0.parquet.partial").write_bytes(b"")
    assert read_crossings(str(directory)).num_rows == rows
    assert read_crossings(str(directory / "crossings-*.parquet")).num_rows == rows
    assert read_crossings(str(recording)).num_rows == rows
    with pytest.raises(FileNotFoundError):
        read_crossings(str(directory / "nothing-*.parquet"))


def test_derived_quantities_match_the_generator(recording):
    table = read_crossings(str(recording))
    assert energy_loss(table) == pytest.approx(ENERGY_LOSS_MEV)
    assert scattering_angle(table) == pytest.approx(SCATTERING_ANGLE_RAD)
    assert mass(table) == pytest.approx(MUON_MASS_MEV)


def test_scattering_angle_resolves_a_nanoradian():
    angle = 1e-9
    table = pa.table(
        {
            "entry_px": [0.0],
            "entry_py": [0.0],
            "entry_pz": [1.0],
            "exit_px": [math.sin(angle)],
            "exit_py": [0.0],
            "exit_pz": [math.cos(angle)],
        }
    )
    assert scattering_angle(table) == pytest.approx(angle)


def test_csv_round_trip(recording):
    parquet_to_csv.main(str(recording))
    csv = read_crossings(str(recording.with_suffix(".csv")))
    assert csv.equals(read_crossings(str(recording)))
