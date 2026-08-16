# commons

Shared tools for Geant4-based apps. In use by MUonE and by the B5 example; B1
still carries its own stub and is due to follow.

| Header | What it does |
|--------|--------------|
| `GrpcClient.hh` | the gRPC client, one `Send<Payload>()` per message in `rl4phy.proto` |
| `GeometryExport.hh` | writes the geometry to GDML and hands it over once at startup |
| `TrajectoryStream.hh` | turns Geant4's trajectory storage on and sends each event's trajectories |

The last two are why a new example needs no code of its own for the picture:
geometry and trajectories are the same job everywhere, so an example only wires
them into its `main` and its event action and writes its own scoring.

Examples get this directory on their include path from
`rl4phy_add_example()` in `geant4/cmake/RL4PhyExample.cmake`; MUonE adds it
itself in `geant4/MUonE/CMakeLists.txt`.
