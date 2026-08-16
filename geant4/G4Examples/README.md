# Connecting Geant4 examples to RL4PHYS (gRPC)

This is a guide for putting a Geant4 example on the RL4PHYS wire: the example runs
exactly as upstream wrote it, sends what it scores to a Python receiver over gRPC,
and the receiver draws it in Rerun. It is written so that the next example — one of
Geant4's own, or anything else that arrives with a `src/`, an `include/` and a macro
— can be added by following it, rather than by reading what was done to the two that
are here already.

Those two sit at the end as worked examples: **B1**, the smallest integration there
is, and **B5**, which uses everything below.

## What an integration consists of

Three kinds of thing can go over the wire, and only the first of them is work:

| What | Where it comes from | What it costs you |
|------|---------------------|-------------------|
| the example's own scoring | whatever the example already computes | a message in `proto/rl4phy.proto`, a `Send…()` in `commons/GrpcClient.hh`, a branch in `python/server.py` |
| the geometry | `commons/GeometryExport.hh` | one call in `BeginOfRunAction` |
| the trajectories | `commons/TrajectoryStream.hh` | one call in `main`, one in `EndOfEventAction` |

Three things hold whichever of them you take:

- Geant4 runs **exactly like the original example** — same physics, same scoring,
  same geometry, same console output. Ours is added to it, never in place of it.
- The vendored example directory stays **byte-for-byte upstream**.
- Everything we add lives in one file beside it, `<Name>_rl4phys.cc`.

## Rule one: subclass, never edit

`B1/` and `B5/` are upstream Geant4, unmodified, and nothing we write is allowed to
change that. The integration goes in a separate entry point, `B1_rl4phys.cc` and
`B5_rl4phys.cc`, which subclasses the example's own user actions.

Two things follow from it, and they are the reason for the rule:

- The copy in the repo can be checked against the release it came from with a plain
  diff. Nobody has to take on trust that our physics is the example's physics.
- A newer Geant4 can be dropped in wholesale. Re-vendoring is a copy, not a merge,
  and what breaks afterwards is our one file, in the compiler, rather than
  somewhere in the example's scoring at runtime.

The shape of every override is the same: call the base class first, then add the
gRPC part.

```cpp
void EndOfEventAction(const G4Event* event) override
{
  EventAction::EndOfEventAction(event);   // the example's own end of event
  // ... ours
}
```

Doing it the other way round reads the example's results before it has computed
them. B5's `EventAction::EndOfEventAction` is what fills the histograms, the ntuple
and the per-cell energies, so everything we send is only there after the call.

You will meet base classes that keep the value you want private. There are two ways
out, and both are cheaper than editing the example:

- Read it back through whatever the class does expose. B5's cell energies come from
  the public `GetEmCalEdep()` and `GetHadCalEdep()`.
- Recompute it beside the example. B1's `EventAction` keeps its `fEdep` private, so
  the subclass mirrors the same sum into a field of its own; B5's subclass looks the
  hit collection Ids up a second time, since the base class resolves them privately.

Neither costs correctness: the numbers are checked against the example's own printed
output at the end (see [Verifying](#verifying)).

## What `commons/` gives you

`geant4/commons/` holds three headers, on the include path of every example (see
[CMake](#cmake-one-line-per-example)). Between them they cover the two jobs that are
identical in every example — the detector and the tracks — so that an example only
has to write its own scoring.

| Header | What it is for | The calls that matter |
|--------|----------------|-----------------------|
| `GrpcClient.hh` | the wire | `SendEventScoring`, `SendB5Event`, `SendTrajectories`, `SendGeometry` |
| `GeometryExport.hh` | the detector | `SendForRun`, `WriteToFile` |
| `TrajectoryStream.hh` | the tracks | `Enable`, `SendEvent` |

`geant4/commons/README.md` is the detail; what follows is what you need to write an
example.

### `GrpcClient.hh` — the wire

One class, constructed from a gRPC channel, with one method per payload:

```cpp
explicit GrpcClient(std::shared_ptr<grpc::Channel> channel);

void SendEventScoring(float edep_MeV, int event_id);
void SendStepHit(const rl4phys::StepHit& hit);
void SendB5Event(const rl4phys::B5Event& event);
void SendTrajectories(const rl4phys::EventTrajectories& trajectories);
bool SendGeometry(const std::string& gdmlContent);
```

An example does not hold a protobuf stub of its own any more. Adding a payload means
adding a `Send<Payload>()` here, which keeps the `oneof` packing, the failure
reporting and the geometry latch below in one place instead of one copy per example.

Two rules about ownership, and both have bitten:

- **One client per thread.** The `grpc::Channel` handed to the constructor is
  thread-safe and is meant to be shared; the client is not. In practice this means
  `main` creates the channel, the action initialisation carries it, and each action
  object builds its own client — and `Build()` runs once per worker thread, so that
  is one client per thread by construction.
- **The client outlives the run.** `SendGeometry` waits up to 30 s for the receiver
  the first time and never again, and the latch that remembers a failure is a member
  of the client. A run action that builds a fresh client per run gets a fresh latch
  with it and pays the 30 s again on every run with nothing listening. Hold the
  client as a member of the action, as `GrpcRunAction` in `B5_rl4phys.cc` and
  `RunAction` in `geant4/MUonE/` both do.

### `GeometryExport.hh` — the detector

```cpp
bool        WriteToFile(const std::string& path, const G4VPhysicalVolume* world = nullptr);
std::size_t SendOverGrpc(GrpcClient& client,     const G4VPhysicalVolume* world = nullptr);
std::size_t SendForRun(GrpcClient& client,       const G4VPhysicalVolume* world = nullptr);
```

`SendForRun()` goes in `BeginOfRunAction`, after the base class's own. It writes the
current geometry to GDML in tmpfs, ships the bytes and deletes the file, and returns
the number of bytes sent. Pass no world volume unless you have a reason to: it takes
the one the tracking navigator holds, which is whatever `DetectorConstruction`
returned.

It sends **on the master thread only**, and returns 0 on a worker — which is also
what a failed send returns, so a caller that logs a non-zero result stays quiet in
both cases. A four-run macro therefore puts four geometry messages on the wire
whether it runs on one thread or on eight.

`WriteToFile()` is the other half, and it needs no gRPC: it is what the
`--export-gdml` flag calls, for a human who wants a copy of the detector to open.

**Once per run, not once per job.** A detector can move between runs, and when it
does, the geometry is what the run's tracks are drawn on. B5's
`/B5/detector/armAngle` rotates the second arm and moves it five metres, three times
over the course of `B5/run1.mac`:

![B5 with the second arm at its default 30 degrees](img/b5-arm-30deg.png)

*`event_index` 1, in the first run of `B5/run1.mac`: the second arm sits at its
default 30°. The fixed first arm is the box to the right of the magnet, the arm that
moves is the one to the left of it.*

![B5 with the two arms in line](img/b5-arm-0deg.png)

*`event_index` 5, the last event of the second run, after
`/B5/detector/armAngle 0. deg`: the second arm has swung into line with the first.
That run also sets `/B5/field/value 0. tesla`, so the tracks cross the magnet
straight.*

![B5 with the second arm at 60 degrees](img/b5-arm-60deg.png)

*`event_index` 6, the first event of the third run, after `armAngle 60. deg` and
`field 2. tesla`: the second arm has swung right round, and the event on screen is
one of the three that were actually produced in that position.*

Nothing in the viewer was told about any of this. The geometry is logged on the same
`event_index` timeline as the tracks, at the slot the next event will take, so
Rerun's latest-at lookup pairs every event with the detector it was simulated on and
dragging the slider moves the detector with it. Send once before the macro instead
and nine of `run1.mac`'s twelve events are drawn on a detector they were never
produced in — nothing fails, no warning appears, and the picture looks perfectly
reasonable.

### `TrajectoryStream.hh` — the tracks

```cpp
void        Enable(G4int type = 1);
using Filter = std::function<bool(const G4VTrajectory&)>;
Filter      AcceptedBy(const G4VFilter<G4VTrajectory>& filter);
std::size_t SendEvent(GrpcClient& client, const G4Event* event, const Filter& filter = {});
```

These are the polylines Geant4's own viewer draws: `SendEvent()` reads
`G4Event::GetTrajectoryContainer()`, which holds exactly what
`/vis/scene/add/trajectories` renders. No stepping action of your own is involved,
because Geant4 has already built them.

`Enable()` has to be called once, after the run manager exists and before the first
`/run/beamOn`. Geant4 keeps no trajectories unless something asks for them;
interactively the vis system asks, in batch nothing does. It goes through
`/tracking/storeTrajectory`, which is per thread, so applying it on the master is
enough: `G4MTRunManager` replays it on every worker. The argument picks the
trajectory class — 1 for `G4Trajectory`, 2 for the smoothed one that
`/vis/scene/add/trajectories smooth` uses, 3 for `G4RichTrajectory`. `SendEvent()`
reads all three.

`SendEvent()` goes in `EndOfEventAction` and returns how many trajectories went out.
Every event sends, including one with nothing to draw: on the receiver a message is
what clears the previous event off the screen, so an event that stayed silent would
leave the event before it drawn over the right geometry.

To draw less than everything, pass a filter. It is a `std::function`, so a cut is a
lambda where you wire the action up and needs no change in `commons/`:

```cpp
TrajectoryStream::SendEvent(fClient, event, [](const G4VTrajectory& t) {
  return t.GetCharge() != 0.;
});
```

Geant4's own filters work too, through `AcceptedBy()`, which wraps a
`G4VFilter<G4VTrajectory>` into the same signature. One catch, and it is Geant4's:
`G4TrajectoryEncounteredVolumeFilter` reads a volume path that only
`G4RichTrajectory` carries, so an example that wants it has to ask for `Enable(3)`
or it will reject everything and warn on each event. The other three filters Geant4
ships are fine with a plain `G4Trajectory`. The filter is captured by reference, so
keep it alive as long as you are sending.

### Both of these are optional

Geometry and trajectories are two independent choices, and an example that takes
neither is still a first-class citizen here. An example whose point is a number per
event — a dose, a yield, a spectrum — has no reason to ship a detector and a
hundred thousand track points along with it, and saying so costs nothing: leave the
calls out.

| What you want | What to write |
|---------------|---------------|
| your scoring only | the payload, and nothing from `GeometryExport` or `TrajectoryStream` |
| scoring + a detector to look at | add `GeometryExport::SendForRun()` in `BeginOfRunAction` |
| scoring + the picture Geant4's viewer would draw | add `TrajectoryStream::Enable()` in `main` and `SendEvent()` in `EndOfEventAction` |
| the picture and no scoring of your own | both of the above, and no new proto message at all — this is what `geant4/MUonE/` does |

What each omission actually costs is in [the table under the
template](#what-happens-if-you-leave-a-line-out).

## The payload: extending the proto

Geant4 builds a message from `proto/rl4phy.proto` and calls `SendData`. Python
receives it and checks which **payload type** is inside.

The proto uses `oneof payload` — each message carries **one** data type only:

| Payload | Example | Meaning |
|---------|---------|---------|
| `event_scoring` | B1 | total energy deposit in the scoring volume, per event (MeV) |
| `event_trajectories` | MUonE, B5 | every trajectory of one event: the polylines Geant4's viewer draws |
| `b5_event` | B5 | per-event summary of all six sensitive detectors |
| `step_hit` | — | one step of one track, with momentum and kinetic energy. Nothing sends it any more; kept because it is the only way to get per-step kinematics over the wire |

The geometry does not travel this way. It has an rpc of its own, `SendGeometry`,
taking a `GeometryFile` — one field, the GDML bytes — because it is not per event
and has nothing to do with the `oneof`.

Adding a payload is four edits, in this order:

1. A new `message` in `proto/rl4phy.proto`, and a new arm in `oneof payload` with
   the next free field number. Do not renumber or reuse the existing ones.
2. A `Send<Payload>()` in `commons/GrpcClient.hh` that packs it into `rl4phys::Data`
   and calls `Send()`. Take the filled message by const reference and let the caller
   fill it: which hit collections make up an event is the example's business, not
   the transport's.
3. The `elif` in `python/server.py` (see [Python](#python-one-branch-in-senddata)).
4. Nothing in CMake. The stubs are generated from the proto by the build.

Two things worth writing into the message's comment while you remember them: the
units, and that `event_id` is not a unique key — it restarts at 0 on every
`/run/beamOn`, and a multithreaded run delivers events out of order. The receiver
numbers events itself for exactly that reason.

## The standard `main`

This is the whole entry point, in the order it is written. `Name` stands for the
example's own directory name — `B5`, `TestEm3`, whatever it is — so the file is
`Name_rl4phys.cc`, next to `Name/`. It is derived from `B5_rl4phys.cc`; every call
in it exists under that name today.

Lines marked `// optional` can be deleted without touching anything else.

```cpp
// Name_rl4phys.cc - RL4PHYS entry point for the vendored Name example.
// The example itself (Name/src, Name/include) is not touched.

#include "ActionInitialization.hh"
#include "DetectorConstruction.hh"
#include "EventAction.hh"
#include "PrimaryGeneratorAction.hh"
#include "RunAction.hh"

#include "G4MTRunManager.hh"
#include "G4RunManagerFactory.hh"
#include "G4UImanager.hh"
#include "G4Event.hh"
#include "G4SystemOfUnits.hh"

#include "FTFP_BERT.hh"          // whichever physics list the example itself uses

#include "GrpcClient.hh"
#include "GeometryExport.hh"     // optional: geometry
#include "TrajectoryStream.hh"   // optional: trajectories

#include <grpcpp/grpcpp.h>

#include <cstdlib>
#include <cstring>
#include <memory>

using namespace Name;


// End of event: the example's own logic first, then ours.
class GrpcEventAction : public EventAction
{
  public:
    explicit GrpcEventAction(std::shared_ptr<grpc::Channel> channel)
      : fClient(std::move(channel))
    {}

    void EndOfEventAction(const G4Event* event) override
    {
      // Never skip this: it is where the example scores the event.
      EventAction::EndOfEventAction(event);

      // The example's own results, read back through whatever the base class
      // exposes, into the message you added to rl4phy.proto.
      rl4phys::NameEvent message;
      message.set_event_id(event->GetEventID());
      // ... fill it here
      fClient.SendNameEvent(message);

      // optional: the polylines Geant4's own viewer would draw for this event.
      TrajectoryStream::SendEvent(fClient, event);
    }

  private:
    // One client per event action, i.e. one per worker thread.
    GrpcClient fClient;
};


// Begin of run: the geometry, once per /run/beamOn.
// optional: the whole class, if the detector is not wanted on the wire.
class GrpcRunAction : public RunAction
{
  public:
    explicit GrpcRunAction(std::shared_ptr<grpc::Channel> channel)
      : fClient(std::move(channel))
    {}

    void BeginOfRunAction(const G4Run* run) override
    {
      RunAction::BeginOfRunAction(run);

      // Master thread only, and 0 on a worker, so this stays quiet there.
      if (auto sent = GeometryExport::SendForRun(fClient)) {
        G4cout << "Geometry sent over gRPC: " << sent << " bytes" << G4endl;
      }
    }

  private:
    // Held for the life of the run action, not rebuilt per run: see the latch
    // in GrpcClient.hh.
    GrpcClient fClient;
};


class RL4PhysActionInitialization : public ActionInitialization
{
  public:
    explicit RL4PhysActionInitialization(std::shared_ptr<grpc::Channel> channel)
      : fChannel(std::move(channel))
    {}

    // The master runs no event, but it is the thread that ships the geometry.
    // Leave this override out and a multithreaded run sends none at all.
    void BuildForMaster() const override      // optional: geometry
    {
      SetUserAction(new GrpcRunAction(fChannel));
    }

    void Build() const override
    {
      SetUserAction(new PrimaryGeneratorAction);
      SetUserAction(new GrpcEventAction(fChannel));
      SetUserAction(new GrpcRunAction(fChannel));
    }

  private:
    std::shared_ptr<grpc::Channel> fChannel;
};


int main(int argc, char** argv)
{
  if (argc < 2) {
    G4cerr << "Usage:" << G4endl;
    G4cerr << "  " << argv[0]
           << " macro.mac [--threads N] [--grpc-host HOST:PORT]" << G4endl;
    G4cerr << "  " << argv[0] << " --export-gdml geometry.gdml" << G4endl;
    return 1;
  }

  G4String macroFile, gdmlFile;
  G4String grpcHost = "localhost:50051";
  G4int nThreads = 1;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--threads") == 0 && i + 1 < argc) {
      nThreads = std::atoi(argv[++i]);
    }
    else if (std::strcmp(argv[i], "--grpc-host") == 0 && i + 1 < argc) {
      grpcHost = argv[++i];
    }
    else if (std::strcmp(argv[i], "--export-gdml") == 0 && i + 1 < argc) {
      gdmlFile = argv[++i];   // optional: handled after the kernel is initialised
    }
    else {
      macroFile = argv[i];
    }
  }

  auto* runManager = G4RunManagerFactory::CreateRunManager(G4RunManagerType::MT);
  if (auto* mt = dynamic_cast<G4MTRunManager*>(runManager)) {
    mt->SetNumberOfThreads(nThreads);
    G4cout << "Using multithreading with " << nThreads << " threads" << G4endl;
  }

  // One channel for the whole application; every client shares it.
  auto channel = grpc::CreateChannel(grpcHost, grpc::InsecureChannelCredentials());
  G4cout << "gRPC -> " << grpcHost << G4endl;

  // The example's own detector and physics list, copied from its own main
  // (exampleName.cc) unchanged. Only the action initialisation is ours, and it
  // builds the example's own primary generator anyway.
  runManager->SetUserInitialization(new DetectorConstruction);
  runManager->SetUserInitialization(new FTFP_BERT);
  runManager->SetUserInitialization(new RL4PhysActionInitialization(channel));

  // Nothing above this line has a geometry yet.
  runManager->Initialize();

  // optional: an on-disk copy for a person to open, then stop. Nothing is
  // simulated, so this path never touches gRPC.
  if (!gdmlFile.empty()) {
    const G4bool written = GeometryExport::WriteToFile(gdmlFile);
    if (written) G4cout << "Geometry exported to: " << gdmlFile << G4endl;
    delete runManager;
    return written ? 0 : 1;
  }

  // optional: batch runs keep no trajectories unless asked, and the macro will
  // not ask, because interactively it is the vis system that does. Applied on
  // the master, which is how it reaches the workers too.
  TrajectoryStream::Enable();

  if (macroFile.empty()) {
    G4cerr << "No macro file provided" << G4endl;
    delete runManager;
    return 1;
  }

  const G4int status =
    G4UImanager::GetUIpointer()->ApplyCommand("/control/execute " + macroFile);
  if (status != 0) {
    G4cerr << "Error executing macro: " << macroFile << G4endl;
  }

  delete runManager;
  return status;
}
```

Adapt, do not fight, the example's own constructors. B5's `RunAction` takes the
event action, because its ntuple columns point at vectors the event action owns, so
B5's `GrpcRunAction` takes and forwards one too. Read the example's own
`ActionInitialization::Build()` before writing yours and keep whatever it does.

If the example is single-threaded by nature, ask
`G4RunManagerFactory::CreateRunManager(G4RunManagerType::Serial)` for a serial run
manager and drop `--threads` with it; `GeometryExport::SendForRun()` is still right,
because a sequential run manager reports as the master thread.

### What happens if you leave a line out

| Left out | What you get |
|----------|--------------|
| `GeometryExport::SendForRun()` | tracks drawn in an empty world — or, in a session that ran another example first, on that example's detector |
| the `BuildForMaster()` override | no geometry at all in a multithreaded run: the master keeps the example's own run action and never sends |
| `TrajectoryStream::Enable()` | no trajectories are stored, so every `SendEvent()` sends an empty message and the viewer shows a detector and nothing in it |
| `TrajectoryStream::SendEvent()` | no tracks on the wire; your own payload still arrives |
| `--export-gdml` | no way to get a GDML copy by hand; nothing else changes |
| `--threads` | the run manager keeps its own default thread count |
| `--grpc-host` | `localhost:50051`, which is not where the receiver is under Docker Compose — it is `python:50051` |

## CMake: one line per example

`geant4/G4Examples/CMakeLists.txt` stays as short as the upstream `examples/basic`
one. All the plumbing is in `geant4/cmake/`, and an example is a line:

```cmake
rl4phy_add_example(B1)
rl4phy_add_example(B5)
```

`rl4phy_add_example(<Name>)` (`geant4/cmake/RL4PhyExample.cmake`) expects
`<Name>/src`, `<Name>/include` and `<Name>_rl4phys.cc` next to the calling
`CMakeLists.txt`, and fails with a message naming the missing one if either the
entry point or the example directory is not there. Given those, it:

- globs `<Name>/src/*.cc` and `<Name>/include/*.hh` and builds them together with
  `<Name>_rl4phys.cc` into the executable `<Name>_rl4phys`;
- puts `<Name>/include` and `geant4/commons` on that target's include path;
- links `${Geant4_LIBRARIES}` and calls `rl4phy_enable_grpc()`;
- copies the example's `*.mac`, `*.in`, `*.out` and `*.png` to `<build>/<Name>/`,
  the way the upstream `CMakeLists.txt` does, because the executables read their
  macros from the working directory.

`rl4phy_enable_grpc(<target>)` (`geant4/cmake/RL4PhyGrpc.cmake`) is the other half.
Including that module finds gRPC and protobuf — through their CMake configs, or
through a `find_library`/`find_program` fallback for Debian and Ubuntu, which ship
the libraries and the plugin without one — runs `protoc` over `proto/rl4phy.proto`
and puts the generated stubs in an object library called `rl4phy_proto`. The
function then links that library into the target and defines `RL4PHY_ENABLE_GRPC`
for its sources.

Two details these two take care of, both easy to get wrong by hand:

- **Headers are per target, never global.** B1 and B5 both ship a
  `DetectorConstruction.hh`, `EventAction.hh`, `RunAction.hh`,
  `ActionInitialization.hh` and `PrimaryGeneratorAction.hh`, differing only by
  namespace, so a global include path would let one example pick up the other's
  headers.
- **The proto stubs are generated once**, into the shared `rl4phy_proto`.
  Generating them per target would mean two custom commands writing the same
  output, which CMake rejects outright.

An object library rather than a static one, incidentally, because protobuf registers
its descriptors from static initialisers and object files are always linked whole.

`-DRL4PHY_ENABLE_GRPC=OFF` configures the build without any of this.
`rl4phy_enable_grpc()` then does nothing, and an entry point written like the
template above will not compile, because `GrpcClient.hh` needs the generated
headers. That switch is for the MUonE application, which guards its gRPC code with
`#ifdef RL4PHY_ENABLE_GRPC`; do the same if you want an example that builds both
ways.

## Docker: two lines

The image is built from the repository root `Dockerfile`. Both edits are next to the
existing ones.

Install the binary in the `RUN` that configures and builds
`/app/geant4/G4Examples`, chained after the `install` lines already there with
`&& \`:

```dockerfile
    install -m 0755 /app/geant4/G4Examples/build/Name_rl4phys /usr/local/bin/Name_rl4phys
```

and copy the macros the example ships, so they are in the working directory
(`/work`) at run time:

```dockerfile
COPY geant4/G4Examples/Name/run1.mac geant4/G4Examples/Name/run2.mac /work/Name/
```

Then, from the repository root:

```powershell
docker compose build python geant
docker compose up -d python
docker compose run --rm --entrypoint Name_rl4phys geant --grpc-host python:50051 Name/run1.mac
docker compose logs python
```

`--entrypoint` is not optional: the image's own entrypoint runs the MUonE
application. `--grpc-host python:50051` is the receiver's address on the compose
network. To watch it rather than read the log, the `python` service publishes
Rerun's port too:

```powershell
rerun --connect rerun+http://127.0.0.1:9876/proxy
```

## Python: one branch in `SendData`

`python/server.py` dispatches on `request.WhichOneof("payload")`:

```python
elif kind == "name_event":
    self._log_name_event(request.name_event)
```

Write the handler to print the same quantities the example prints itself, so the two
can be read side by side — `_log_b5_event` prints the calorimeter totals for exactly
that reason, since 100 cells per event on the console are unreadable.

Geometry and trajectories need no Python at all. `SendGeometry` parses whatever
arrives and logs the volumes; `_log_event_trajectories` folds the flattened points
back into polylines, colours them the way Geant4's `drawByCharge` does, and logs one
row per event. Both land on the `event_index` timeline, which the server counts
itself: `event_id` restarts at 0 on every `/run/beamOn`, so four runs of three would
otherwise occupy three slots between them.

## Verifying

The example still runs its own code, so it still prints its own output. That is what
to check against, and it is worth doing before believing anything on screen.

- **Scoring.** Take a number the example prints per event and find it in what
  arrived. For B5, `EM Calorimeter has N hits. Total Edep is X (MeV)` must equal the
  sum of that event's `em_cal_edep`. For B1, the cumulative dose in the log and the
  `event_scoring.edep` values have to be consistent.
- **Geometry.** Count the `Geometry sent over gRPC` lines: one per `/run/beamOn`,
  and the same number with `--threads 1` and `--threads 8`. If a macro moves the
  detector, the GDMLs of two runs must differ in the volume it moved.
- **Trajectories.** `SendEvent()` returns how many went out, so print it: that
  number and the one the server prints for the same event have to agree, and the
  picture in Rerun should match what Geant4's own OpenGL viewer draws for the same
  macro with `/vis/scene/add/trajectories`.
- **With nothing listening.** Run it without the `python` service. It has to
  complete: the first geometry waits 30 s for a receiver, then stops waiting, and
  every later failure is reported without stalling the run.

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
The copy in `B5/` is the unmodified 11.3.2 example.

B5 is the guide applied end to end: a payload of its own, the geometry and the
trajectories, with a detector that moves mid-macro. The three screenshots above are
one `B5/run1.mac` session.

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

On top of that, one `event_trajectories` per event — the lines Geant4's own
OpenGL viewer draws. Nothing example specific about it:
`commons/TrajectoryStream.hh` does the whole job, and B5 only calls it.

| Field | Meaning |
|-------|---------|
| `event_id` | as above |
| `trajectories` | one entry per tracked particle |

and per trajectory:

| Field | Meaning |
|-------|---------|
| `track_id`, `parent_id` | the track and the one that produced it (`0` for a primary) |
| `pdg` | PDG code of the particle |
| `charge` | in units of `e`, so `drawByCharge` colouring is reproducible |
| `particle_name` | Geant4's own name, e.g. `e-`, `gamma` |
| `points` | the polyline, flattened as `x,y,z` triples [mm] |
| `initial_e_kin` | kinetic energy at the start of the track [MeV] |

There is no filter: every track the viewer would show is sent. It can afford to,
because a whole event costs one message rather than one per step — on `run1.mac`
that is 12 messages covering 13619 trajectories. Each event prints
`Trajectories sent: N`, next to B5's own per event diagnostics.

### How it is wired

The three classes of the template, with the two places B5 asks for something of its
own:

1. **`GrpcEventAction`** (extends `EventAction`)
   Runs B5's own end-of-event logic first, then reads the results back and sends
   `b5_event`. Cell energies come from the public `GetEmCalEdep()` /
   `GetHadCalEdep()`; hit counts and hodoscope times come from the event's hit
   collections, whose Ids the base class keeps private and this class therefore
   looks up once per worker thread. Then one call to
   `TrajectoryStream::SendEvent()` — no stepping action, because Geant4 has already
   built the trajectories.

2. **`GrpcRunAction`** (extends `RunAction`)
   Runs B5's own begin-of-run logic first, then hands the geometry over with
   `GeometryExport::SendForRun()`. **B5's `RunAction` takes the event action in its
   constructor** — its ntuple columns point at vectors the event action owns — so
   this one takes and forwards one too, which is the one place the template's
   signature does not fit as written.

3. **`RL4PhysActionInitialization`** (extends `ActionInitialization`)
   Wires both in, and overrides `BuildForMaster()` with the body of B5's own rather
   than a call to it: B5's version sets its plain `RunAction`, and `SetUserAction`
   would only drop ours again. The master is the thread that ships the geometry, so
   getting this wrong means no geometry is ever sent.

`main` is the template. Its physics list mirrors `exampleB5.cc` — `FTFP_BERT` plus
`G4StepLimiterPhysics`, in that order — and it adds batch mode, `--threads`,
`--grpc-host` and `--export-gdml`, exactly like B1, plus the
`TrajectoryStream::Enable()` before the macro without which a batch run would store
no trajectories to send.

### Build & run (Docker)

```powershell
docker compose build python geant
docker compose up -d python
docker compose run --rm --entrypoint B5_rl4phys geant --grpc-host python:50051 B5/run1.mac
docker compose logs python
```

- `run1.mac` → 12 events over four detector settings (arm angle 30/0/60/30 deg,
  field 1/0/2/1 tesla).
- `run2.mac` → 90 events, protons / pi+ / e+ at 100 GeV.

### How to check it

The example prints `EM Calorimeter has N hits. Total Edep is X (MeV)` for every
event; the sum of `em_cal_edep` in the matching `b5_event` must be the same number.
On the last event of `run1.mac` both read 123.801 MeV.

The geometry is worth checking separately, because it is the one thing that changes
mid-macro: `run1.mac` prints `Geometry sent over gRPC: N bytes` four times, once per
`/run/beamOn` and never once per worker, and the four GDMLs differ only in
`fSecondArmPhys` — `y="30"`, then no rotation at all and `z="5000"` for 0 deg, then
60 and 30 again, each with the matching `(-5 m sin a, 0, 5 m cos a)` position.

### Key files

| File | Role |
|------|------|
| `B5/` | original Geant4 example, unmodified |
| `B5_rl4phys.cc` | gRPC integration |
| `CMakeLists.txt` | one line: `rl4phy_add_example(B5)` |
| `geant4/cmake/RL4PhyExample.cmake` | builds any vendored example as `<Name>_rl4phys` |
| `geant4/cmake/RL4PhyGrpc.cmake` | gRPC discovery and the shared `rl4phy_proto` stubs |
| `Dockerfile` | installs `B5_rl4phys`, ships `B5/run1.mac`, `B5/run2.mac` |

---

## Other examples in this repo

| Example | Location | What it sends |
|---------|----------|---------------|
| B1 | `G4Examples/B1_rl4phys.cc` | `event_scoring`; geometry once from `main` (`SendOverGrpc`), predating the per-run rule; no trajectories |
| B5 | `G4Examples/B5_rl4phys.cc` | `b5_event` + `event_trajectories`; geometry per run |
| MUonE | `geant4/MUonE/` | `event_trajectories` and nothing of its own; geometry per run. Its own `CMakeLists.txt` rather than `rl4phy_add_example()`, and its gRPC code is `#ifdef`-guarded so it builds without gRPC |

All three send through `commons/GrpcClient.hh`; none holds a protobuf stub of its
own.

---

## Checklist for the next example

0. **Decide what you want on the wire.** The scoring is yours to write; the
   geometry and the trajectories are three calls into `commons/` and both are
   optional. See [Both of these are optional](#both-of-these-are-optional).
1. **Understand the original scoring.** Per step, event or run? Which volume? Which
   of it does the example already expose, and which will you have to mirror or look
   up again?
2. **Extend the proto.** A new `message`, a new arm in `oneof payload` with the next
   free field number, and a `Send<Payload>()` in `commons/GrpcClient.hh`. Do not
   touch the existing arms.
3. **Write `<Name>_rl4phys.cc`** from [the template](#the-standard-main). Subclass
   the example's actions, call the base method first, never edit `<Name>/`.
4. **One line in `CMakeLists.txt`**: `rl4phy_add_example(<Name>)`. The helper does
   sources, headers, gRPC and macros.
5. **Two lines in the `Dockerfile`**: `install` the new binary next to the existing
   ones, `COPY` the macros it ships into `/work/<Name>/`.
6. **One branch in `python/server.py`**, on `request.WhichOneof("payload")`.
   Geometry and trajectories are already handled.
7. **Verify against the example's own output** — see [Verifying](#verifying). The
   original code still runs and still prints; if its numbers and yours disagree, the
   integration is wrong, not the example.
