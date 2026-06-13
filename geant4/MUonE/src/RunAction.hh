#pragma once
#include "G4UserRunAction.hh"

class RunAction : public G4UserRunAction {
public:
  void BeginOfRunAction(const G4Run*) override;
};
