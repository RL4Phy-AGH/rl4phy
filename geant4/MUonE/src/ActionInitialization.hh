#pragma once

#include "G4VUserActionInitialization.hh"

class GrpcClient;

class ActionInitialization : public G4VUserActionInitialization {
public:
  explicit ActionInitialization(GrpcClient* client);
  void Build() const override;

private:
  GrpcClient* fGrpcClient = nullptr;
};
