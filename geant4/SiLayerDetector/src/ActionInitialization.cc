#include "ActionInitialization.hh"
#include "EventAction.hh"
#include "PrimaryGeneratorAction.hh"
#include "RunAction.hh"
#include "SteppingAction.hh"

// The master only merges the workers' files and writes the run metadata.
void ActionInitialization::BuildForMaster() const {
  SetUserAction(new RunAction(fPhysicsList));
}

void ActionInitialization::Build() const {
  SetUserAction(new PrimaryGeneratorAction);

  auto* runAction = new RunAction(fPhysicsList);
  SetUserAction(runAction);

  auto* eventAction = new EventAction(runAction);
  SetUserAction(eventAction);
  SetUserAction(new SteppingAction(eventAction));
}
