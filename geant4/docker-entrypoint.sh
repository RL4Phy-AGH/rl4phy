#!/bin/sh
if [ -n "$GDML_EXPORT_PATH" ]; then
  # G4GDMLWrite::Write() refuses to overwrite an existing file.
  rm -f "$GDML_EXPORT_PATH"
  exec /usr/local/bin/rl4phy-geant --export-gdml "$GDML_EXPORT_PATH" "$@"
fi

exec /usr/local/bin/rl4phy-geant "$@"
