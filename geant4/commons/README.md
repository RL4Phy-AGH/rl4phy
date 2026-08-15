# commons

Shared tools for Geant4-based apps. Currently holds `GrpcClient.hh`, the gRPC
client used to send data over `rl4phy.proto`. In use by MUonE and by the B5
example; B1 still carries its own stub and is due to follow.

Examples get this directory on their include path from
`rl4phy_add_example()` in `geant4/cmake/RL4PhyExample.cmake`; MUonE adds it
itself in `geant4/MUonE/CMakeLists.txt`.
