import os

import pyarrow.parquet as pq

from dataset_writer import STEP_SCHEMA, ParquetStepWriter


def test_rows_survive_flush_boundaries(tmp_path, crossings):
    writer = ParquetStepWriter(str(tmp_path), flush_rows=7)
    for hit in crossings:
        writer.append_step_hit(hit)
    assert os.listdir(tmp_path) == [os.path.basename(writer.path) + ".partial"]
    writer.close()
    assert os.listdir(tmp_path) == [os.path.basename(writer.path)]

    table = pq.read_table(writer.path)
    assert table.schema.equals(STEP_SCHEMA)
    assert table.num_rows == len(crossings) == writer.rows_written
    assert table.to_pylist() == [
        {
            "event_id": hit.event_id,
            "track_id": hit.track_id,
            "parent_id": hit.parent_id,
            "pdg": hit.pdg,
            "volume": hit.volume,
            "entry_e": hit.entry.e,
            "entry_px": hit.entry.px,
            "entry_py": hit.entry.py,
            "entry_pz": hit.entry.pz,
            "exit_e": hit.exit.e,
            "exit_px": hit.exit.px,
            "exit_py": hit.exit.py,
            "exit_pz": hit.exit.pz,
            "path_length": hit.path_length,
        }
        for hit in crossings
    ]


def test_no_crossings_leave_no_file(tmp_path):
    writer = ParquetStepWriter(str(tmp_path))
    writer.close()
    assert writer.path is None
    assert os.listdir(tmp_path) == []


def test_close_ends_the_file_and_the_next_crossing_starts_another(tmp_path, crossings):
    writer = ParquetStepWriter(str(tmp_path))
    writer.append_step_hit(crossings[0])
    writer.close()
    first = writer.path
    writer.append_step_hit(crossings[1])
    writer.close()
    assert first != writer.path
    assert os.path.basename(first).startswith("crossings-")
    assert pq.read_table(first).num_rows == 1
    assert pq.read_table(writer.path).num_rows == 1
