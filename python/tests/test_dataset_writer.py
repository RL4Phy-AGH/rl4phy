import os

import pyarrow.parquet as pq

from dataset_writer import STEP_SCHEMA, ParquetStepWriter


def test_rows_survive_flush_boundaries(tmp_path, crossings):
    writer = ParquetStepWriter(str(tmp_path), flush_rows=7)
    for hit in crossings:
        writer.append_step_hit(hit)
    writer.close()

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


def test_file_lands_in_the_directory_as_parquet(tmp_path):
    writer = ParquetStepWriter(str(tmp_path))
    writer.close()
    assert os.path.dirname(writer.path) == str(tmp_path)
    assert os.path.basename(writer.path).startswith("crossings-")
    assert writer.path.endswith(".parquet")


def test_close_is_final(tmp_path, crossings):
    writer = ParquetStepWriter(str(tmp_path))
    writer.append_step_hit(crossings[0])
    writer.close()
    writer.append_step_hit(crossings[1])
    writer.close()
    assert writer.rows_written == 1
    assert pq.read_table(writer.path).num_rows == 1
