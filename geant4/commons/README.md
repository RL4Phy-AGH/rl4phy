# commons

Shared tools for Geant4-based apps. In use by MUonE, B5 and B1: none of them
holds a protobuf stub of its own any more.

| Header | What it does |
|--------|--------------|
| `GrpcClient.hh` | the gRPC client, one `Send<Payload>()` per message in `rl4phy.proto` |
| `GeometryStream.hh` | writes the geometry to GDML and hands it over once per run |
| `TrajectoryStream.hh` | turns Geant4's trajectory storage on and sends each event's trajectories |

The last two are why a new example needs no code of its own for the picture:
geometry and trajectories are the same job everywhere, so an example only wires
them into its run action and its event action and writes its own scoring.

Once per run rather than once per job because a detector can move between runs —
B5's `/B5/detector/armAngle` does, three times over its own `run1.mac` — and the
geometry is what the trajectories are drawn on. `GeometryStream::SendForRun()`
goes in `BeginOfRunAction`; it sends on the master thread only, so a
multithreaded example does not send one copy per worker.

The first geometry of a job waits up to 30 s for the receiver, because it goes
out before the first event and the Python side may still be starting. Only the
first one waits: with nothing listening, `B5/run1.mac` pauses once rather than
once per run, and still says on every run that its geometry reached nobody.

Examples get this directory on their include path from
`rl4phy_add_example()` in `geant4/cmake/RL4PhyExample.cmake`; MUonE adds it
itself in `geant4/MUonE/CMakeLists.txt`.
