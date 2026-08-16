#!/bin/sh
# The geometry no longer travels through a file: GeometryExport writes the GDML
# to tmpfs, reads it back and ships it over gRPC at the start of every run, then
# deletes it. --export-gdml is still there for a human who wants a copy to open,
# but it is asked for explicitly rather than written behind everyone's back.
exec /usr/local/bin/rl4phy-geant "$@"
