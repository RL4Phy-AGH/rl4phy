#pragma once

// Same split as GeometryExport.hh: turning the storage on is plain Geant4 and
// works in any build, only the sending half needs gRPC.
#ifdef RL4PHY_ENABLE_GRPC
#include "GrpcClient.hh"
#endif

#include "G4UImanager.hh"
#include "globals.hh"

#ifdef RL4PHY_ENABLE_GRPC
#include "G4Event.hh"
#include "G4RichTrajectory.hh"
#include "G4SmoothTrajectory.hh"
#include "G4SystemOfUnits.hh"
#include "G4Trajectory.hh"
#include "G4TrajectoryContainer.hh"
#include "G4VFilter.hh"
#include "G4VTrajectory.hh"
#include "G4VTrajectoryPoint.hh"

#include <cstddef>
#include <functional>
#endif

#include <string>

// Trajectory hand-off: the polylines Geant4's own viewer draws, sent once per
// event. Geant4 already builds them - G4Event::GetTrajectoryContainer() holds
// exactly what /vis/scene/add/trajectories renders - so an example needs no
// stepping action of its own:
//
//   TrajectoryStream::Enable()                  once, before the first beamOn
//   TrajectoryStream::SendEvent(client, event)  from EndOfEventAction
//
// Free functions rather than a base class on purpose: every example already has
// its own G4UserEventAction to extend, and a second base would collide with it.
namespace TrajectoryStream
{

// Geant4 keeps no trajectories unless something asks for them. Interactively it
// is /vis/scene/add/trajectories that asks; in batch nothing does, which is why
// this has to be called explicitly. The switch itself lives in
// G4TrackingManager, one per thread, so it goes through the UI rather than
// through a pointer: G4MTRunManager stacks the commands the master applies
// between runs and replays them on every worker, which is how the vis manager
// reaches the worker threads too. Call it after the run manager exists and
// before the first /run/beamOn.
//
// `type` is the value of /tracking/storeTrajectory. 1 gives G4Trajectory, the
// polyline through the step points. 2 gives G4SmoothTrajectory, which adds the
// auxiliary points the field propagator used inside a curve - what
// `/vis/scene/add/trajectories smooth` asks for, and what both vis.mac in this
// repo use. 3 gives G4RichTrajectory, needed by
// G4TrajectoryEncounteredVolumeFilter and nothing else here. SendEvent() reads
// all three.
inline void Enable(G4int type = 1)
{
  G4UImanager::GetUIpointer()->ApplyCommand("/tracking/storeTrajectory " +
                                            std::to_string(type));
}

#ifdef RL4PHY_ENABLE_GRPC

// A trajectory goes out when the filter accepts it; an empty filter, the
// default, accepts everything.
//
// std::function rather than Geant4's G4VFilter because the cuts an example
// wants are one-liners in its main - only the tracks that reached a given
// volume, only what is worth drawing - and G4VFilter would turn each of them
// into a class with a name and a messenger. The four filters Geant4 does ship
// (G4TrajectoryParticleFilter, G4TrajectoryChargeFilter,
// G4TrajectoryOriginVolumeFilter, G4TrajectoryEncounteredVolumeFilter) are
// still one line through AcceptedBy() below, so neither choice is closed off.
using Filter = std::function<bool(const G4VTrajectory&)>;

// Wraps one of Geant4's own trajectory filters. The filter is captured by
// reference, so it has to outlive the sending - an example that builds one in
// main and keeps it there is fine.
//
// One catch, and it is Geant4's, not ours: G4TrajectoryEncounteredVolumeFilter
// reads the volume path off the trajectory's attributes, which only
// G4RichTrajectory carries. Used with anything else it warns (modeling0126,
// "Requires G4RichTrajectory") and rejects every trajectory, so an example that
// wants it has to ask for Enable(3). The other three work with plain
// G4Trajectory; G4TrajectoryOriginVolumeFilter locates the first point with a
// navigator instead of reading attributes.
inline Filter AcceptedBy(const G4VFilter<G4VTrajectory>& filter)
{
  return [&filter](const G4VTrajectory& trajectory) { return filter.Accept(trajectory); };
}

namespace detail
{

// GetInitialKineticEnergy() sits on each of the concrete trajectory classes but
// not on G4VTrajectory, so it has to be asked for by type. These three are what
// /tracking/storeTrajectory can produce.
inline G4double InitialKineticEnergy(const G4VTrajectory& trajectory)
{
  if (auto* plain = dynamic_cast<const G4Trajectory*>(&trajectory)) {
    return plain->GetInitialKineticEnergy();
  }
  if (auto* smooth = dynamic_cast<const G4SmoothTrajectory*>(&trajectory)) {
    return smooth->GetInitialKineticEnergy();
  }
  if (auto* rich = dynamic_cast<const G4RichTrajectory*>(&trajectory)) {
    return rich->GetInitialKineticEnergy();
  }
  return 0.;
}

// The same walk G4TrajectoryDrawerUtils does for the viewer: the auxiliary
// points of a step first, then the step point they lead up to. G4Trajectory
// carries none of the former (G4VTrajectoryPoint::GetAuxiliaryPoints() returns
// nullptr), so this is the plain polyline there and the smoothed one for
// G4SmoothTrajectory, without either case being special.
inline void AppendPoints(const G4VTrajectory& trajectory, rl4phys::Trajectory& out)
{
  for (G4int i = 0; i < trajectory.GetPointEntries(); ++i) {
    const G4VTrajectoryPoint* point = trajectory.GetPoint(i);
    if (point == nullptr) continue;

    if (const auto* auxiliary = point->GetAuxiliaryPoints()) {
      for (const auto& aux : *auxiliary) {
        out.add_points(static_cast<float>(aux.x() / mm));
        out.add_points(static_cast<float>(aux.y() / mm));
        out.add_points(static_cast<float>(aux.z() / mm));
      }
    }

    const G4ThreeVector position = point->GetPosition();
    out.add_points(static_cast<float>(position.x() / mm));
    out.add_points(static_cast<float>(position.y() / mm));
    out.add_points(static_cast<float>(position.z() / mm));
  }
}

}  // namespace detail

// Sends every accepted trajectory of `event` as one EventTrajectories message
// and returns how many went out.
//
// Every event sends, including the ones with nothing to say. On the receiver a
// message is what replaces the previous event's trajectories on screen, so an
// event that skipped its send would leave the event before it drawn on top of
// the right geometry - the wrong tracks, silently. An empty message says "this
// event has nothing to draw" and blanks the screen, which is the truth. That
// covers all three ways of ending up with none: no trajectory container at all
// (what an example that never called Enable() gets, on every event), an empty
// one, and a filter that accepted nothing.
inline std::size_t SendEvent(GrpcClient& client, const G4Event* event,
                             const Filter& filter = {})
{
  // The one case that is a caller's mistake rather than an event with nothing
  // in it. There is no event id to put on a message, so there is nothing
  // honest to send.
  if (event == nullptr) return 0;

  rl4phys::EventTrajectories message;
  message.set_event_id(event->GetEventID());

  // Null whenever the event stored nothing at all; the loop is then skipped
  // and the empty message still goes out below.
  if (const G4TrajectoryContainer* container = event->GetTrajectoryContainer()) {
    for (const G4VTrajectory* trajectory : *container->GetVector()) {
      if (trajectory == nullptr) continue;
      if (filter && !filter(*trajectory)) continue;

      auto* out = message.add_trajectories();
      out->set_track_id(trajectory->GetTrackID());
      out->set_parent_id(trajectory->GetParentID());
      out->set_pdg(trajectory->GetPDGEncoding());
      out->set_charge(static_cast<float>(trajectory->GetCharge() / eplus));
      out->set_particle_name(trajectory->GetParticleName());
      out->set_initial_e_kin(
        static_cast<float>(detail::InitialKineticEnergy(*trajectory) / MeV));
      detail::AppendPoints(*trajectory, *out);
    }
  }

  client.SendTrajectories(message);
  return static_cast<std::size_t>(message.trajectories_size());
}

#endif  // RL4PHY_ENABLE_GRPC

}  // namespace TrajectoryStream
