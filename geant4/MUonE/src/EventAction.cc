#include "EventAction.hh"
#ifdef RL4PHY_ENABLE_GRPC
#include "GrpcClient.hh"
#include "TrajectoryStream.hh"
#endif
#include "G4Event.hh"
#include <iostream>

EventAction::EventAction(GrpcClient* client) : fGrpcClient(client) {}

// One message per event with the polylines Geant4's own viewer draws, taken
// from the event's trajectory container (see commons/TrajectoryStream.hh).
// Deliberately not restricted to the stations the way the STEP records are: the
// viewer shows a track whole, and the point of sending these is to put the two
// pictures next to each other. One TRAJECTORIES line goes to stdout so a run
// without a receiver still says what it would have sent.
void EventAction::EndOfEventAction(const G4Event* event) {
#ifdef RL4PHY_ENABLE_GRPC
  if (!fGrpcClient) return;

  const std::size_t sent = TrajectoryStream::SendEvent(*fGrpcClient, event);
  std::cout << "TRAJECTORIES " << event->GetEventID() << ' ' << sent << '\n';
#endif
}
