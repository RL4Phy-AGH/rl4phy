#ifndef ACTION_INITIALIZATION_HH
#define ACTION_INITIALIZATION_HH

#include "G4VUserActionInitialization.hh"
#include "G4String.hh"

class ActionInitialization : public G4VUserActionInitialization {
public:
  // physicsList is only recorded in the run metadata.
  explicit ActionInitialization(const G4String& physicsList)
      : fPhysicsList(physicsList) {}
  ~ActionInitialization() override = default;

  void BuildForMaster() const override;
  void Build() const override;

private:
  G4String fPhysicsList;
};

#endif
