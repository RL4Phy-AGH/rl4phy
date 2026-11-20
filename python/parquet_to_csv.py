import argparse
import os
import sys

import pyarrow.csv as pa_csv
from loguru import logger

from crossings import crossing_files, read_crossing_file


def main(source: str) -> None:
    for path in crossing_files(source):
        target = f"{os.path.splitext(path)[0]}.csv"
        table = read_crossing_file(path)
        pa_csv.write_csv(table, target)
        logger.info(f"{target}: {table.num_rows} row(s)")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout)
    parser = argparse.ArgumentParser(
        description="Write a CSV copy next to every recorded Parquet file."
    )
    parser.add_argument("source", help="directory with recordings, a file or a glob")
    main(parser.parse_args().source)
