#ifndef EVENT_ACTION_HH
#define EVENT_ACTION_HH

#include "G4UserEventAction.hh"
#include "G4ThreeVector.hh"
#include "globals.hh"

#include "siplate.pb.h"

#include <unordered_map>

class G4Step;
class G4Track;
class G4VProcess;
class RunAction;

// Builds the siplate::Event of one event from the steps taken inside the layer
// (see proto/siplate.proto) and hands it to RunAction at the end of the event.
//
// Each track gets one StepHit per passage through the layer: it is opened at the
// track's first step in the layer (entering through the boundary, or created
// inside) and closed when the track leaves through the boundary or ends. The hit
// holds the entry and exit 4-momenta and positions, the energy deposited, the
// path length, how the track started and ended there and whether it had a
// hadronic interaction. When steps are wanted for the event, every step is also
// stored as a StepPoint (its post-step point).
//
// Only what Geant4 knows directly is stored. Energy loss, kinetic energies and
// angles are derived by the consumer from the 4-vectors.
class EventAction : public G4UserEventAction {
public:
  explicit EventAction(RunAction* runAction) : fRunAction(runAction) {}
  ~EventAction() override = default;

  void BeginOfEventAction(const G4Event* event) override;
  void EndOfEventAction(const G4Event* event) override;

  // Called by SteppingAction for steps whose pre-step point lies in the layer.
  void RecordStep(const G4Step* step);

private:
  // A secondary created in the layer, until its first step there.
  struct Birth {
    G4int parentID;
    G4int creatorStep;
    G4ThreeVector vertex;
  };

  siplate::StepHit& OpenHit(const G4Step* step);
  G4int ProcessIndex(const G4VProcess* process);

  RunAction* fRunAction = nullptr;
  siplate::Event fEvent;
  G4bool fWriteSteps = false;
  std::unordered_map<G4int, int> fOpenHits;  // track ID -> index in fEvent.hits
  std::unordered_map<const G4Track*, Birth> fBirths;
  std::unordered_map<const G4VProcess*, G4int> fProcessCache;
};

#endif
