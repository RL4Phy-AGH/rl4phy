import os
import sys

import pyarrow.csv as pa_csv
from loguru import logger

from dataset_reader import read_crossings


def main(paths: list[str]) -> None:
    for path in paths:
        target = os.path.splitext(path)[0] + ".csv"
        table = read_crossings(path)
        pa_csv.write_csv(table, target)
        logger.info(f"{target}: {table.num_rows} row(s)")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout)
    main(sys.argv[1:])
