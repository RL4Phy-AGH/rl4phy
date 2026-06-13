#include "SteppingAction.hh"
#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4Track.hh"
#include "G4VProcess.hh"
#include "G4VPhysicalVolume.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4ParticleDefinition.hh"
#include "G4Event.hh"
#include "G4EventManager.hh"
#include "G4SystemOfUnits.hh"
#include <iostream>

// One STEP line per step, but only inside the stations: Air and World steps are
// not detector data. Read at the pre-step point; column order lives in RunAction.
void SteppingAction::UserSteppingAction(const G4Step* step) {
  if (!fStationLV) {
    fStationLV = G4LogicalVolumeStore::GetInstance()->GetVolume("Station");
  }

  const G4StepPoint* pre = step->GetPreStepPoint();
  const G4VPhysicalVolume* vol = pre->GetTouchableHandle()->GetVolume();
  if (!vol || vol->GetLogicalVolume() != fStationLV) return;

  const G4Track* track = step->GetTrack();
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
            << vol->GetName() << ' '
            << (proc ? proc->GetProcessName() : "initStep") << '\n';
}
