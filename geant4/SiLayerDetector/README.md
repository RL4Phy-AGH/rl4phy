# SiLayerDetector

Geant4 application with a single silicon plate (5 x 5 cm, 300 um, normal along
the beam axis z) in vacuum. It records how the beam particles lose energy in the
plate and how they scatter, event by event, to study:

1. the **energy-loss distribution** and its shape: Landau / Vavilov, most probable
   value, width, mean;
2. the **angular distribution after the plate**, compared with Moliere's theory
   of multiple Coulomb scattering (and Highland's Gaussian approximation).

One run (`macros/sim.mac`, 3.6M events, tag `siplate`) holds both samples of
the study. The analysis splits it by event ID:

| sample | events | purpose |
|---|---|---|
| reference | 0 .. 1 999 999 (2M) | smooth reference distributions |
| simulation | 2 000 000 .. 3 599 999 (1.6M, 80% of the reference) | target event-by-event sample |

Geant4 seeds every event independently, so the first N events are a
statistically independent sample of the rest, with exactly the same setup. The
split is recorded in the run header (`/siplate/output/referenceEvents`) and can be
changed at analysis time without re-running.

`macros/run.mac` is a quick functional test (1800 events, 1000 reference, tag
`test`).

## Code

- `proto/siplate.proto`: the output format (below). `protoc` generates the C++
  code at build time, the Python module on first use.
- `src/DetectorConstruction.*`: world and plate. The plate carries
  `G4UserLimits` with a 10 um maximum step, so energy loss and scattering can be
  followed through the depth of the plate (~30 steps per primary).
- `src/SteppingAction.*`: passes on the steps whose pre-step point is in the
  plate.
- `src/EventAction.*`: builds the `Event` message of each event: one `StepHit`
  per track and passage through the plate, with the steps as `StepPoint`s when
  they are wanted for the event.
- `src/RunAction.*`: owns the output of a run and its UI commands, and writes
  the `RunHeader`: geometry, material constants (incl. the Sternheimer
  density-effect parameters), physics list, production cuts, process names.
- `src/RecordFile.*`: each thread writes its events to a part file; at the end
  of the run they are merged by event ID into `<tag>.pb` (streaming k-way merge,
  the event bytes are copied without parsing).
- `main.cc`: command line (macro, `--gdml` export); physics list from the
  `PHYSLIST` environment variable, default `FTFP_BERT_EMZ` (`G4EmStandardPhysics_option4`, the most accurate EM option for
  energy-loss fluctuations and multiple scattering in thin layers), plus
  `G4StepLimiterPhysics`.

### UI commands

| command | default | |
|---|---|---|
| `/siplate/output/tag <name>` | `siplate` | output file `<name>.pb` |
| `/siplate/output/writeSteps <bool>` | `true` | store the steps of the hits |
| `/siplate/output/referenceEvents <n>` | `0` | events with ID < n are the reference sample (written to the header) |
| `/siplate/output/maxStepEvents <n>` | `-1` | steps for at most n events, from the first target event (-1: all target events) |

Beam settings are the standard `/gun/particle`, `/gun/energy`. The primary is
the track with `parent_id == 0`, so one particle per event is assumed
(`/gun/number 1`, the default).

## Output

`<tag>.pb` in the working directory: a stream of `Record` messages, each
preceded by its size as a varint (protobuf delimited format). Units: MeV, mm,
ns. See `proto/siplate.proto` for every field.

```
Record{header}   RunHeader   setup, material, cuts, process names; once
Record{event}    Event       run_id, event_id, hits; one per event, by event ID
  StepHit                    one track in the layer, entry -> exit:
                             4-momenta and positions at entry and exit, edep,
                             path length, origin (entered / created inside),
                             fate (exited / stopped / destroyed), hadronic
                             interaction bits, creator_step of a secondary
    StepPoint                one step (post-step point): position, 4-momentum,
                             edep, step length, process, number of secondaries
Record{footer}   RunFooter   number of events written; missing if interrupted
```

Every event is written, also when no particle reached the plate, so the event
IDs are complete. Steps are stored for the first `maxStepEvents` target events
only; the reference sample needs only the hit-level distributions. Size: ~0.4 kB
per event without steps, ~3 kB with (~37 steps per event with deltas).

Only what Geant4 knows directly is stored. Kinetic energies, the energy loss and
the angles are derived by the consumer from the 4-vectors (`siplate_io.py`).

To look into a file:

```bash
python ../analysis/siplate_dump.py siplate.pb -n 2 --steps
```

## Build and run

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate g4rt
mkdir -p build && cd build
cmake .. && make -j
./siplate macros/sim.mac       # ~85 s on 12 threads; siplate.pb ~1.1 GB
```

Export the geometry to GDML:

```bash
./siplate --gdml siplate.gdml                   # build the geometry, export, exit
./siplate --gdml siplate.gdml macros/sim.mac    # run, then export
```

and draw it (matplotlib; box and tube solids, nested and rotated placements):

```bash
python ../analysis/view_gdml.py siplate.gdml            # -> siplate.png
python ../analysis/view_gdml.py siplate.gdml --show     # interactive, rotatable
```

Volume names are written without pointer suffixes, so they match
`StepHit.volume`. GDML stores the shapes, placements and materials, but not the
`G4UserLimits` (10 um maximum step) or the production cuts: those are set by
`DetectorConstruction` and the macro, and recorded in the run header.

Building needs `libprotobuf` from the `g4rt` environment (it provides `protoc`
and the CMake package); run cmake with the environment active. Without
arguments `./siplate` opens an interactive session with visualisation. The
macros are copied to `build/macros` at cmake time: re-run `cmake ..` after
editing them.

Notes:

- Re-running with the same tag overwrites its file. Leftover part files of the
  same tag (from an interrupted run) are removed at the start of the run. Do not
  run two simulations in the same directory at the same time.
- The production cut is 10 um (~32 keV for electrons in Si), so delta electrons
  are explicit tracks and the energy they carry out of the plate is visible.
  The cut applies to both samples, since they come from one run.

## Analysis

`analysis/` needs numpy, scipy (>= 1.15, for `scipy.stats.landau`), pandas,
matplotlib, loguru and protobuf (with `protoc` on the PATH), all present in the
`g4rt` environment.

```bash
cd build
python ../analysis/analyze_siplate.py                        # tag siplate
python ../analysis/analyze_siplate.py --n-reference 1500000   # another split
python ../analysis/analyze_siplate.py --tag test              # the test run
```

The script loads the run once, splits it into the reference and simulation
samples and analyses both. `siplate_io.py` decodes `<tag>.pb` into an event
table and a step table, deriving from the 4-vectors

| quantity | from |
|---|---|
| kinetic energy | `E - m`, `m^2 = E^2 - p^2` at the entry |
| primary energy loss | `E_entry - E_exit` (same particle: equal to the loss of kinetic energy) |
| energy deposited, carried out by secondaries | sum of `edep` over the hits; kinetic energy at exit of secondaries that left |
| projected angles | `atan2(p_x, p_z)`, `atan2(p_y, p_z)` at exit |
| space angle, azimuth | `atan2(p_T, p_z)`, `atan2(p_y, p_x)` |
| deflection in a step | `atan2(\|p0 x p1\|, p0 . p1)`, accurate at small angles |
| depth, step length | step positions, `step_length` |

Decoding 3.6M events takes ~40 s and ~4 GB of memory; the tables are cached in
`<tag>.cache.npz` (~0.9 GB) next to the run file and rebuilt when it changes,
after which the analysis takes ~20 s. The reference binning is used for both
samples. the reference binning is used for both. Results go
to `plots/<tag>/reference/` and `plots/<tag>/simulation/`:

- `energy_loss.png`: primary energy loss against the Landau curve with the
  Bichsel most probable value and width xi, Landau and Landau (x) Gauss fits;
  energy loss next to the energy deposited.
- `scattering_projected.png`, `scattering_space.png`: angles against Moliere
  (Bethe's expansion to 1/B^2) and Highland, with the ratio to Moliere.
- `scattering_2d.png`; `depth_profile.png` and `step_distributions.png` for a
  sample with stored steps (first 50k events, `--step-events`).
- `compare_*.png` (simulation only): the simulation sample over the reference
  on the reference binning, with chi2 and Kolmogorov-Smirnov tests.
- `histograms.npz`: binned distributions; for the reference sample these are
  the reference templates.
- `summary.json`: theory parameters, fit results, statistics, test results.

Theory and data use "clean" events, where the primary left the plate without a
hadronic interaction, since both theories are purely electromagnetic.
Scattering theory is evaluated at the mid-depth energy, energy-loss theory at
the entrance energy.

Modules: `theory.py` (Bethe, Landau/Bichsel, Highland, Moliere; constants read
from the run header, nothing silicon-specific), `siplate_io.py` (decoding a run,
kinematics from the 4-vectors, splitting into samples), `analyze_siplate.py`
(the CLI), `siplate_dump.py` (printing a run file), `view_gdml.py` (drawing a GDML
geometry). The Moliere functions are tabulated once (~30 s)
and cached in `~/.cache/siplate/`.

### What to expect (100 MeV protons, 300 um Si)

- kappa = xi / T_max = 0.13: the Vavilov regime, not the Landau limit. The peak
  agrees with the Bichsel value (MPV ~359 keV), the mean with Bethe (408.5 keV),
  but the measured distribution is narrower than Landau (FWHM 112 vs 117 keV)
  and its tail falls below the Landau tail, cut off by T_max = 229 keV. Landau
  fits therefore have chi2/ndf >> 1; this is physics, not a fit problem.
  Thinner layers or faster particles move towards the Landau limit.
- B = 10.3: the Gaussian core width agrees with Moliere (3.17 vs 3.21 mrad);
  Highland is ~7% wider. Geant4 sits ~15% below Moliere in the transition
  region (2.5-6 sigma) and agrees again in the single-scattering tail.
