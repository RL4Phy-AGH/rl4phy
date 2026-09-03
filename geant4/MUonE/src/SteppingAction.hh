#pragma once

#include "G4UserSteppingAction.hh"

class G4LogicalVolume;

class SteppingAction : public G4UserSteppingAction {
public:
  void UserSteppingAction(const G4Step* step) override;

private:
  const G4LogicalVolume* fStationLV = nullptr;
};
