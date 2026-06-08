# geant

Code associated with geant, including dockerfile.

## Geometry

Small Geant4 app that builds the detector in C++ and writes it out to GDML, so
the Python side (pyg4ometry) can load the same geometry. The geometry and
physics live in the C++; GDML is the export, not the source. (That's the split
the team agreed for the architecture.)

- `src/DetectorConstruction.*`: `BuildMUonE()` builds the MUonE-scope geometry
  in C++: 3 silicon tracking stations along the beam (z = -300 / 0 / +300 mm),
  the middle one rotated 30 deg (stereo). `BuildFromGDML()` stays as an import path.
- `src/main.cc`: flags `--export-gdml <file>` (write geometry to GDML),
  `--gdml <file>` (import instead of the C++ build), `--vis [macro]`, `<macro>`.
- `src/SteppingAction.*`: one `STEP` line per step with the track's position,
  momentum, energy, time and the process (column header from `RunAction`).
- `macros/`: `run.mac` (mu- 160 GeV beam), `vis.mac` (OpenGL view).

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

To sanity-check, run the binary: `--export-gdml` produces a GDML with the 3
stations (clean names), and a beam run prints the `STEP` records (see the
header). The real, portable test belongs in CI once it exists, on the Python
side: pyg4ometry loads the exported GDML and validates it, which exercises the
actual G4 -> Python interface.

>The build above was verified on Windows, but the GDML export interface is platform-independent.
