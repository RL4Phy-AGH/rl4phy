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
| MUonE | `geant4/MUonE/` | `step_hit` (uses `commons/GrpcClient.hh`) |

---
