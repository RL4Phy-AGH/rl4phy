"""Print the header, the first events and the footer of a run file.

python ../analysis/siplate_dump.py siplate.pb            # header + 1 event
python ../analysis/siplate_dump.py siplate.pb -n 3 --steps
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from google.protobuf.json_format import MessageToJson

from siplate_io import iter_records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("-n", type=int, default=1, help="events to print (default 1)")
    ap.add_argument("--steps", action="store_true", help="include the steps")
    args = ap.parse_args()

    shown = 0
    for record in iter_records(args.file):
        kind = record.WhichOneof("content")
        if kind == "event":
            if shown >= args.n:
                continue  # read on to the footer
            shown += 1
            if not args.steps:
                for hit in record.event.hits:
                    del hit.steps[:]
        sys.stdout.write(f"--- {kind}\n{MessageToJson(getattr(record, kind))}\n")


if __name__ == "__main__":
    main()
