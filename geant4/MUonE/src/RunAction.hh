#pragma once
#include "G4UserRunAction.hh"

class GrpcClient;

class RunAction : public G4UserRunAction {
public:
  explicit RunAction(GrpcClient* client = nullptr);
  void BeginOfRunAction(const G4Run*) override;

private:
  GrpcClient* fGrpcClient = nullptr;
};
