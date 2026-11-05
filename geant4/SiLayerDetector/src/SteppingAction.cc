#include "SteppingAction.hh"
#include "EventAction.hh"

#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4VPhysicalVolume.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"

void SteppingAction::UserSteppingAction(const G4Step* step) {
  if (!fPlateLV) {
    fPlateLV = G4LogicalVolumeStore::GetInstance()->GetVolume("SiPlate");
  }

  const G4VPhysicalVolume* vol =
      step->GetPreStepPoint()->GetTouchableHandle()->GetVolume();
  if (!vol || vol->GetLogicalVolume() != fPlateLV) return;

  fEventAction->RecordStep(step);
}
