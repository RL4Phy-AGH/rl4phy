import os
import sys

import pyarrow.csv as pa_csv
from loguru import logger

from dataset_reader import crossing_files, read_file


def main(sources: list[str]) -> None:
    for path in (path for source in sources for path in crossing_files(source)):
        target = os.path.splitext(path)[0] + ".csv"
        table = read_file(path)
        pa_csv.write_csv(table, target)
        logger.info(f"{target}: {table.num_rows} row(s)")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout)
    main(sys.argv[1:])
