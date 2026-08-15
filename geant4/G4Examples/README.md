# Connecting Geant4 examples to RL4PHYS (gRPC)

This guide explains how we hooked up the **B1** example. It is meant to grow over time —
each new example should add its own short section with lessons learned.

## What we want

- Geant4 runs **exactly like the original example** (same physics, same scoring, same geometry).
- Selected results are sent to Python over gRPC.
- The original example code (`B1/src/`, `B1/include/`) stays **unchanged**.
  Integration lives in a separate entry file: `B1_rl4phys.cc`.

## How it fits together

Geant4 builds a message from `proto/rl4phy.proto` and calls `SendData`. Python receives it
and checks which **payload type** is inside.

The proto uses `oneof payload` — each message carries **one** data type only:

| Payload | Example | Meaning |
|---------|---------|---------|
| `event_scoring` | B1 | total energy deposit in the scoring volume, per event (MeV) |
| `step_hit` | MUonE | one step inside a detector volume |
| `b5_event` | B5 | per-event summary of all six sensitive detectors |

To add a new example: define a new `message` in the proto and add it to the `oneof`.

---

## B1

Official B1: [Geant4 basic/B1](https://gitlab.cern.ch/geant4/geant4/-/tree/master/examples/basic/B1).

### What B1 scores

B1 sums **energy deposit per event** in a scoring volume (Shape2):

- `SteppingAction` adds each step’s edep to `EventAction`.
- At end of event, `RunAction` uses that sum (dose printed in the log).

We export **only that sum** over gRPC as `event_scoring.edep`.

### What we added (all in `B1_rl4phys.cc`)

We **subclass** B1’s user actions instead of copying them:

1. **`GrpcEventAction`** (extends `EventAction`)  
   Runs the normal B1 end-of-event logic, then sends `event_scoring` over gRPC.

2. **`RL4PhysSteppingAction`** (extends `SteppingAction`)  
   Calls the base class first (real B1 scoring), then records the same edep for gRPC.

3. **`RL4PhysActionInitialization`** (extends `ActionInitialization`)  
   Wires up the classes above instead of the default B1 actions.

`main` is like batch B1, plus a gRPC channel (`--grpc-host`, default `localhost:50051`).

**Note:** `EventAction` keeps `fEdep` private, so we mirror it in `fGrpcEdep` for sending.
We did not change B1’s source files.

### Build & run (Docker)

```powershell
docker compose build python geant
docker compose up -d python
docker compose run --rm --entrypoint B1_rl4phys geant --grpc-host python:50051 B1/run1.mac
docker compose logs python
```

- `run1.mac` → 6 events, all edep = 0 (matches B1 dose 0 in the log).
- `run2.mac` → some events with edep > 0.

Check that Geant4’s cumulative dose and the gRPC edep values are consistent.

### Key files

| File | Role |
|------|------|
| `B1/` | original Geant4 example |
| `B1_rl4phys.cc` | gRPC integration |
| `CMakeLists.txt` | builds `B1_rl4phys`, generates code from proto |
| `proto/rl4phy.proto` | shared gRPC contract |
| `python/server.py` | Python receiver |

---

## B5

Official B5: [Geant4 basic/B5](https://gitlab.cern.ch/geant4/geant4/-/tree/master/examples/basic/B5).
The copy in `B5/` is the unmodified 11.3.2 example (verified byte for byte against
the upstream tag).

### What B5 scores

B5 is a double arm spectrometer with **six sensitive detectors**, all read out at
end of event:

| Detector | Count | What it gives |
|----------|-------|---------------|
| hodoscope 1, 2 | 2 | hit time per fired strip |
| drift chamber 1, 2 | 2 | one hit per fired layer (5 layers) |
| EM calorimeter | 80 cells (20 columns x 4 rows) | energy deposit per cell |
| hadron calorimeter | 20 cells (10 columns x 2 rows) | energy deposit per cell |

`EventAction::EndOfEventAction` reads the hit collections, fills the histograms
and the ntuple, and stores the per cell energies.

### What we export

One `b5_event` per event — the same quantities the example puts in its own
ntuple, nothing more:

| Field | Size | Meaning |
|-------|------|---------|
| `event_id` | 1 | `G4Event::GetEventID()` |
| `drift_chamber_hits` | 2 | hits in chamber 1, 2 |
| `hodoscope_time` | 2 | time of the first hit [ns]; `-1` when the arm saw nothing |
| `em_cal_edep` | 80 | energy per EM cell [MeV], empty cells included |
| `had_cal_edep` | 20 | energy per hadronic cell [MeV], empty cells included |

Cells are indexed `column * rows + row`, so they reshape to `(20, 4)` and
`(10, 2)`.

### What we added (all in `B5_rl4phys.cc`)

Same rule as B1 — **subclass, never edit the example**:

1. **`GrpcEventAction`** (extends `EventAction`)
   Runs B5's own end-of-event logic first (histograms, ntuple, cell energies),
   then reads the results back and sends `b5_event`. Cell energies come from the
   public `GetEmCalEdep()` / `GetHadCalEdep()`; hit counts and hodoscope times
   come from the event's hit collections, whose Ids the base class keeps private
   and this class therefore looks up once per worker thread.

2. **`RL4PhysActionInitialization`** (extends `ActionInitialization`)
   Wires the gRPC event action in. **Note:** B5's `RunAction` takes the event
   action in its constructor (its ntuple columns point at vectors the event
   action owns), so the gRPC one has to be passed there too.

`main` mirrors `exampleB5.cc` — `FTFP_BERT` plus `G4StepLimiterPhysics`, same
order — and adds batch mode, `--threads`, `--grpc-host` and `--export-gdml`,
exactly like B1.

### Build & run (Docker)

```powershell
docker compose build python geant
docker compose up -d python
docker compose run --rm --entrypoint B5_rl4phys geant --grpc-host python:50051 B5/run1.mac
docker compose logs python
```

- `run1.mac` → 12 events over four detector settings (arm angle 0/60/30 deg,
  field 0/2/1 tesla).
- `run2.mac` → 90 events, protons / pi+ / e+ at 100 GeV.

**How to check it:** the example prints `EM Calorimeter has N hits. Total Edep is
X (MeV)` for every event; the sum of `em_cal_edep` in the matching `b5_event`
must be the same number. On the last event of `run1.mac` both read
123.801 MeV.

### CMake note

`B1` and `B5` both ship a `DetectorConstruction.hh`, `EventAction.hh`,
`RunAction.hh`, `ActionInitialization.hh` and `PrimaryGeneratorAction.hh` — they
only differ by namespace. A global include path would let one example pick up
the other's headers, so each target gets its own include directory instead
(`target_include_directories`), the way the upstream examples do it. The proto
stubs are generated once into a shared `rl4phy_proto` object library; generating
them per target would mean two custom commands writing the same output, which
CMake rejects.

### Key files

| File | Role |
|------|------|
| `B5/` | original Geant4 example, unmodified |
| `B5_rl4phys.cc` | gRPC integration |
| `CMakeLists.txt` | builds `B5_rl4phys`, shares the generated proto stubs |
| `Dockerfile` | installs `B5_rl4phys`, ships `B5/run1.mac`, `B5/run2.mac` |

---

## Checklist for the next example

1. **Understand the original scoring** — per step, event, or run? Which volume?
2. **Extend the proto** — new `message` + new `oneof` arm (do not break existing ones).
3. **Integrate in C++** — prefer a separate `*_rl4phys.cc`; subclass existing actions;
   call base methods before adding gRPC; avoid editing the original example if possible.
4. **CMake / Docker** — copy the `B1_rl4phys` setup.
5. **Python** — handle the new payload in `server.py`.
6. **Verify** — compare output with the original example (with and without gRPC).

---

## Other examples in this repo

| Example | Location | Payload |
|---------|----------|---------|
| B1 | `G4Examples/B1_rl4phys.cc` | `event_scoring` |
| B5 | `G4Examples/B5_rl4phys.cc` | `b5_event` |
| MUonE | `geant4/MUonE/` | `step_hit` (uses `commons/GrpcClient.hh`) |

---
