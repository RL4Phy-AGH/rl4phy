#include "ActionInitialization.hh"
#include "PrimaryGeneratorAction.hh"
#include "SteppingAction.hh"
#include "EventAction.hh"
#include "RunAction.hh"

ActionInitialization::ActionInitialization(GrpcClient* client)
    : fGrpcClient(client) {}

// We run single-threaded (see main). On a multithreaded build RunAction would
// also need to go in BuildForMaster(), and it would matter more than the
// column header it prints: RunAction is what ships the geometry, and the master
// is the only thread that ships it, so a worker-only RunAction would send none
// at all.
void ActionInitialization::Build() const {
  SetUserAction(new PrimaryGeneratorAction());
  SetUserAction(new RunAction(fGrpcClient));
  SetUserAction(new SteppingAction());
  SetUserAction(new EventAction(fGrpcClient));
}
