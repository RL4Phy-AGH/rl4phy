#include "ActionInitialization.hh"
#include "PrimaryGeneratorAction.hh"
#include "SteppingAction.hh"
#include "EventAction.hh"
#include "RunAction.hh"

ActionInitialization::ActionInitialization(GrpcClient* client)
    : fGrpcClient(client) {}

// We run single-threaded (see main). On a multithreaded build RunAction would
// also need to go in BuildForMaster().
void ActionInitialization::Build() const {
  SetUserAction(new PrimaryGeneratorAction());
  SetUserAction(new RunAction());
  SetUserAction(new SteppingAction());
  SetUserAction(new EventAction(fGrpcClient));
}
