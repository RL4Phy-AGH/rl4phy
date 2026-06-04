#include "SteppingAction.hh"
#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4Track.hh"
#include "G4VProcess.hh"
#include "G4VPhysicalVolume.hh"
#include "G4ParticleDefinition.hh"
#include "G4Event.hh"
#include "G4EventManager.hh"
#include "G4SystemOfUnits.hh"
#include <iostream>

// One line per step. We read it at the pre-step point (where the track is when
// the step begins) plus whatever process ended the step. Position, momentum and
// energy are all Python needs to line its own track up against ours; the
// scattering angles fall straight out of the momentum, so we don't log them
// separately. Stdout for now, gRPC later. Column order lives in RunAction.
void SteppingAction::UserSteppingAction(const G4Step* step) {
  const G4Track* track = step->GetTrack();
  const G4StepPoint* pre = step->GetPreStepPoint();
  const G4VPhysicalVolume* vol = pre->GetPhysicalVolume();
  const G4VProcess* proc = step->GetPostStepPoint()->GetProcessDefinedStep();

  const auto pos = pre->GetPosition();
  const auto p = pre->GetMomentum();
  const int eventID =
      G4EventManager::GetEventManager()->GetConstCurrentEvent()->GetEventID();

  std::cout << "STEP "
            << eventID << ' '
            << track->GetTrackID() << ' '
            << track->GetParentID() << ' '
            << track->GetDefinition()->GetParticleName() << ' '
            << pos.x() / mm << ' ' << pos.y() / mm << ' ' << pos.z() / mm << ' '
            << p.x() / MeV << ' ' << p.y() / MeV << ' ' << p.z() / MeV << ' '
            << pre->GetTotalEnergy() / MeV << ' '
            << pre->GetKineticEnergy() / MeV << ' '
            << pre->GetGlobalTime() / ns << ' '
            << step->GetStepLength() / mm << ' '
            << (vol ? vol->GetName() : "OutOfWorld") << ' '
            << (proc ? proc->GetProcessName() : "initStep") << '\n';
}
