#!/bin/sh
# G4GDMLWrite::Write() refuses to overwrite an existing file, but the GDML
# export path lives on a volume that survives container restarts (so python
# can still read the last export while geant is restarting). Clear out the
# stale file first so a restart doesn't abort with "File already exists!".
prev=""
for arg in "$@"; do
  if [ "$prev" = "--export-gdml" ]; then
    rm -f "$arg"
  fi
  prev="$arg"
done

exec /usr/local/bin/rl4phy-geant "$@"
