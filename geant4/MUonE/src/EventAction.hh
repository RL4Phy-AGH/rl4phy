#pragma once

#include "G4UserEventAction.hh"

class GrpcClient;

class EventAction : public G4UserEventAction {
public:
  explicit EventAction(GrpcClient* client);
  void EndOfEventAction(const G4Event* event) override;

private:
  GrpcClient* fGrpcClient = nullptr;
};
