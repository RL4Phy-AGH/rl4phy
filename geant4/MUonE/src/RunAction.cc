#include "RunAction.hh"

// Both guards: the geometry is written with GDML and sent with gRPC, and either
// half can be missing from a build - see the two options in CMakeLists.txt.
#ifdef RL4PHY_ENABLE_GDML
#ifdef RL4PHY_ENABLE_GRPC
#include "GeometryStream.hh"
#include "GrpcClient.hh"
#endif
#endif

#include <iostream>

RunAction::RunAction(GrpcClient* client) : fGrpcClient(client) {}

// Hand the geometry over, then print the column names, so the STEP lines that
// follow are readable without counting fields.
//
// The geometry goes out here rather than once from main because it is what the
// run's tracks will be drawn on, and a run is where a detector can have changed
// - MUonE's does not have a command that moves anything, but B5 next door does,
// and the rule belongs in one place. See GeometryStream::SendForRun, which
// sends on the master thread only; we run single-threaded, so that is this one.
void RunAction::BeginOfRunAction(const G4Run*) {
#ifdef RL4PHY_ENABLE_GDML
#ifdef RL4PHY_ENABLE_GRPC
  // No world volume passed: after Initialize() the tracking navigator holds
  // exactly the one DetectorConstruction returned, whether it was built in code
  // or read from a GDML file, so there is nothing to carry around for it.
  if (fGrpcClient) {
    if (auto sent = GeometryStream::SendForRun(*fGrpcClient)) {
      std::cout << "GDML SENT OVER GRPC: " << sent << " bytes" << std::endl;
    }
  }
#endif
#endif

  std::cout << "# STEP eventID trackID parentID particle "
               "x y z[mm] px py pz[MeV] Etot Ekin[MeV] t[ns] stepLen[mm] "
               "volume process\n";
}
