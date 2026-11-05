#ifndef RUN_ACTION_HH
#define RUN_ACTION_HH

#include "G4UserRunAction.hh"
#include "G4String.hh"

#include <fstream>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

class G4GenericMessenger;
class G4Run;

namespace siplate {
class Event;
class RunHeader;
}  // namespace siplate

// Owns the output of one run: <tag>.pb, the stream of siplate::Record messages
// defined in proto/siplate.proto (run header, one Event per event, footer).
//
// Each thread writes its events to a part file; at the end of the run the
// master (or the only thread, in sequential mode) merges the parts by event ID
// into <tag>.pb, framed by the header and the footer. See RecordFile.
//
// UI commands:
//   /siplate/output/tag <name>          file name <name>.pb (default "siplate")
//   /siplate/output/writeSteps <bool>   fill StepHit.steps (default true)
//   /siplate/output/referenceEvents <n> events 0..n-1 form the reference sample,
//                                       the rest the target sample (default 0).
//                                       Recorded in the run header; the split
//                                       itself is done by the analysis.
//   /siplate/output/maxStepEvents <n>   steps for at most n events, counted from
//                                       the first target event (ID referenceEvents);
//                                       -1 = all target events (default). Keeps the
//                                       file manageable (~2.4 kB per event).
//
// One run therefore holds both samples: same setup, and since Geant4 seeds each
// event independently, the first n events are statistically independent of the
// rest.
class RunAction : public G4UserRunAction {
public:
  explicit RunAction(const G4String& physicsList);
  ~RunAction() override;

  void BeginOfRunAction(const G4Run* run) override;
  void EndOfRunAction(const G4Run* run) override;

  // Whether StepHit.steps is filled for this event.
  bool StepsWanted(G4int eventID) const {
    if (!fWriteSteps || eventID < fReferenceEvents) return false;
    return fMaxStepEvents < 0 || eventID < fReferenceEvents + fMaxStepEvents;
  }

  // Index of a process in RunHeader.processes, -1 if unknown.
  G4int ProcessIndex(const G4String& name) const;

  void WriteEvent(const siplate::Event& event);

private:
  G4String Base() const { return fTag; }
  void BuildProcessList();
  void FillHeader(const G4Run* run, siplate::RunHeader& header) const;

  G4String fPhysicsList;
  G4String fTag = "siplate";
  G4bool fWriteSteps = true;
  G4int fReferenceEvents = 0;
  G4int fMaxStepEvents = -1;
  std::unique_ptr<G4GenericMessenger> fMessenger;

  // Process names sorted alphabetically: every thread builds the same list
  // from the same physics list, so the indices agree between threads.
  std::vector<std::string> fProcesses;
  std::unordered_map<std::string, G4int> fProcessIndex;

  std::ofstream fPart;
  std::string fBuffer;
};

#endif
