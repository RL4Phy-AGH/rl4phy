# rl4phy

Geant4 muon simulation (`geant`) streaming step data over gRPC to a Python
service (`python`), which visualizes it live in [Rerun](https://rerun.io/).

## Dev mode

```
docker compose up
```

Plain `docker compose` automatically merges `docker-compose.yml` with
`docker-compose.override.yaml`. That override adds bind mounts for
`python/` and `geant4/`, so edits on your host are picked up without
rebuilding the image, plus a `stubs-generator` step that mirrors headers
and packages into `.stubs/` for your editor (see below).

- Rerun viewer: `rerun --connect rerun+http://127.0.0.1:9876/proxy`
- gRPC port `50051` is also published.

## Production mode

```
docker compose -f docker-compose.yml up --build
```

This ignores the override: no bind mounts, no `.stubs/` generation, no
CMake/protoc re-run on every start. Everything is baked into the image at
build time.

## Geometry (GDML)

`geant` builds the detector, then exports it to GDML (`--export-gdml`) on
a shared volume before running the beam macro. `python` parses that file
(`python/gdml_geometry.py`) and draws the station layout dynamically — a
geometry change in `DetectorConstruction.cc` shows up in the viewer
automatically, no edit needed on the Python side.

`python` polls for the file until it shows up — no timeout, no fallback.
Both services read the export path from the shared `GDML_EXPORT_PATH` env
var (set once in `docker-compose.yml`), so it only needs changing in one
place.

## After changing code

| Change | Command |
|---|---|
| Python (`python/*.py`) | `docker compose restart python` |
| C++ (`geant4/MUonE/src/*.cc`, `main.cc`, incl. new files) | `docker compose restart geant` |
| `proto/rl4phy.proto` | `docker compose restart geant python` |
| `requirements.txt`, `Dockerfile`, `python/Dockerfile`, base image version | `docker compose build` |

`geant`'s CMake build and `python`'s protoc run on every container start
and are incremental, so a restart is all that's needed for the cases above.

## Editor setup (IntelliSense on Windows/macOS/Linux)

Nothing to install or configure manually. `docker compose up` (dev mode)
regenerates `.stubs/` — a mirror of the container's Python packages and
C++ headers — which `pyrightconfig.json` and `.clangd` point at. This
works automatically for any dependency added later (new pip package, new
`apt-get install ...-dev`), not just the ones present today.

- `.stubs/` is generated, gitignored, and safe to delete any time.
- A single `docker compose restart <service>` does not regenerate
  `.stubs/` (it skips re-checking `stubs-generator`'s dependency). Use
  `docker compose up` if IntelliSense needs to pick up a new dependency.
- Editor language servers may need a restart/reload after `.stubs/`
  changes.

## Windows

`.stubs/` generation uses plain file copies, not symlinks, so it works the
same as on Linux/macOS. Shell scripts are checked out with LF line endings
on any platform (`.gitattributes`), so they still run inside the Linux
containers.
