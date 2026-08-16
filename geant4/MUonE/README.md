# MUonE

The MUonE Geant4 application, plus its Dockerfile.

## Geometry

Small Geant4 app that builds the detector in C++ and writes it out to GDML, so
the Python side (`python/gdml_geometry.py`, a minimal hand-rolled reader, not
pyg4ometry) can load the same geometry. The geometry and physics live in the
C++; GDML is the export, not the source.

- `src/DetectorConstruction.*`: `BuildMUonE()` builds the MUonE-scope geometry
  in C++: 3 silicon tracking stations along the beam (z = -300 / 0 / +300 mm),
  the middle one rotated 30 deg (stereo). `BuildFromGDML()` stays as an import path.
- `main.cc`: flags `--export-gdml <file>` (write geometry to GDML),
  `--gdml <file>` (import instead of the C++ build), `--vis [macro]`, `<macro>`.
- `src/RunAction.*`: prints the `STEP` column header, and hands the geometry to
  the Python side once per `/run/beamOn` via `commons/GeometryExport.hh`. Per run
  and not once from `main` because the geometry is what the run's tracks get
  drawn on, and a UI command between runs can have moved it — B5 next door has
  exactly such a command. `GeometryExport::SendForRun()` sends on the master
  thread only, which here is the only thread there is.
- `src/SteppingAction.*`: one `STEP` line per step with the track's position,
  momentum, energy, time and the process (column header from `RunAction`).
  Console only, and still only the steps inside the `Station` volumes.
- `src/EventAction.*`: one `event_trajectories` message per event over gRPC —
  the polylines Geant4's own viewer draws, straight out of the event's
  trajectory container, via `commons/TrajectoryStream.hh`. Whole tracks, not
  just the pieces inside the stations, because the point is to put our picture
  next to the OpenGL one. Prints `TRAJECTORIES <eventID> <count>`.
- `macros/`: `run.mac` (mu- 160 GeV beam), `vis.mac` (OpenGL view).

The trajectories and the geometry only go out when `--grpc-host` is given, which
is also when `main` switches trajectory storage on: a batch run keeps none by
default, and in `--vis` mode the vis system asks for them itself. `--export-gdml`
is separate: it is an on-disk copy and needs no receiver, and an export-only run
never beams, so it sends nothing.

### Build (Windows, Geant4 11.3 with GDML + Xerces via vcpkg)

```powershell
cmake -S . -B build `
  -DGeant4_DIR=C:\Geant4\install\lib\cmake\Geant4 `
  -DXercesC_ROOT=C:\vcpkg\installed\x64-windows
cmake --build build --config Release --parallel
```

### Run

```powershell
# build geometry in C++ and export it to GDML (for Python / pyg4ometry)
build\Release\rl4phy-geant.exe --export-gdml muone.gdml

# fire a muon through the C++ geometry (per-step records to stdout)
build\Release\rl4phy-geant.exe macros\run.mac

# import a GDML file instead of the C++ build
build\Release\rl4phy-geant.exe --gdml muone.gdml macros\run.mac
```

### Datasets

Both commands above need the Geant4 data files present, not only the beam run:
`--export-gdml` also calls `Initialize()`, which builds the physics tables and
reads the nuclear and cross-section data. Locally they come with the Geant4
install (the `GEANT4_INSTALL_DATA=ON` build), so it just works. The container
image ships without data, so you mount them at `/data` (see the Dockerfile), and
the dataset versions have to match the ones Geant4 11.3 expects.

### Verification

`.github/workflows/geant-ci.yml` builds the image and runs both smoke tests on
every PR touching `geant4/**`: `--export-gdml` produces a GDML with the 3
stations (clean names), and a beam run prints the `STEP` records.

>The build above was verified on Windows, but the GDML export interface is platform-independent.
