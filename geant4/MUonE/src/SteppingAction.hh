#pragma once

#include "G4UserSteppingAction.hh"

class G4LogicalVolume;
class GrpcClient;

class SteppingAction : public G4UserSteppingAction {
public:
  explicit SteppingAction(GrpcClient* client);
  void UserSteppingAction(const G4Step* step) override;

private:
  GrpcClient* fGrpcClient = nullptr;
  const G4LogicalVolume* fStationLV = nullptr;
};
