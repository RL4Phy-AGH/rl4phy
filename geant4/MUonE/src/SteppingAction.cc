#include "SteppingAction.hh"
#include "GrpcClient.hh"
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

SteppingAction::SteppingAction(GrpcClient* client) : fGrpcClient(client) {}

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

  const double x_mm = pos.x() / mm;
  const double y_mm = pos.y() / mm;
  const double z_mm = pos.z() / mm;
  const double px_MeV = p.x() / MeV;
  const double py_MeV = p.y() / MeV;
  const double pz_MeV = p.z() / MeV;
  const double e_kin_MeV = pre->GetKineticEnergy() / MeV;

  fGrpcClient->SendStepData(
      static_cast<float>(x_mm), static_cast<float>(y_mm), static_cast<float>(z_mm),
      static_cast<float>(px_MeV), static_cast<float>(py_MeV), static_cast<float>(pz_MeV),
      static_cast<float>(e_kin_MeV));

  std::cout << "STEP "
            << eventID << ' '
            << track->GetTrackID() << ' '
            << track->GetParentID() << ' '
            << track->GetDefinition()->GetParticleName() << ' '
            << x_mm << ' ' << y_mm << ' ' << z_mm << ' '
            << px_MeV << ' ' << py_MeV << ' ' << pz_MeV << ' '
            << pre->GetTotalEnergy() / MeV << ' '
            << e_kin_MeV << ' '
            << pre->GetGlobalTime() / ns << ' '
            << step->GetStepLength() / mm << ' '
            << vol->GetName() << ' '
            << (proc ? proc->GetProcessName() : "initStep") << '\n';
}
