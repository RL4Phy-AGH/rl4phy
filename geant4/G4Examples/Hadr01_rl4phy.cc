#include "DetectorConstruction.hh"
#include "EventAction.hh"
#include "HistoManager.hh"
#include "PhysicsList.hh"
#include "PrimaryGeneratorAction.hh"
#include "RunAction.hh"
#include "StackingAction.hh"

#include "G4AntiProton.hh"
#include "G4Electron.hh"
#include "G4Event.hh"
#include "G4Gamma.hh"
#include "G4PhysListFactory.hh"
#include "G4PionMinus.hh"
#include "G4PionPlus.hh"
#include "G4Positron.hh"
#include "G4Proton.hh"
#include "G4RunManagerFactory.hh"
#include "G4Step.hh"
#include "G4SystemOfUnits.hh"
#include "G4Track.hh"
#include "G4UImanager.hh"
#include "G4UserSteppingAction.hh"

#include "GeometryStream.hh"
#include "GrpcClient.hh"
#include "TrajectoryStream.hh"

#include <grpcpp/grpcpp.h>

#include <cstdlib>
#include <cstring>


static rl4phy::Hadr01Event gEvent;

// Geometry of the target, as HistoManager::BeginOfRun sets them up.
static G4double fRadius = 0.;
static G4double fAbsZ0 = 0.;
static G4double fR2 = 0.;

void BeginOfRun()
{
  const HistoManager* histo = HistoManager::GetPointer();
  fRadius = histo->Radius();
  fR2 = fRadius * fRadius;
  fAbsZ0 = 0.5 * histo->Length();
}

// HistoManager::ScoreNewTrack
void ScoreNewTrack(const G4Track* track)
{
  const G4ParticleDefinition* pd = track->GetDefinition();

  if (0 == track->GetParentID()) {
    return;
  }

  gEvent.add_secondary_pdg(pd->GetPDGEncoding());
}

// HistoManager::AddTargetStep
void AddTargetStep(const G4Step* step)
{
  gEvent.set_n_steps(gEvent.n_steps() + 1);  // ++fNstep
  const G4double fEdep = step->GetTotalEnergyDeposit();
  const G4Track* track = step->GetTrack();
  const G4ParticleDefinition* pd = track->GetDefinition();
  if (fEdep > 0.0) {
    // scoring
    gEvent.set_edep(gEvent.edep() + fEdep / MeV);  // fEdepEvt += fEdep

    if (pd == G4Gamma::Gamma() || pd == G4Electron::Electron() || pd == G4Positron::Positron()) {
      gEvent.set_edep_em(gEvent.edep_em() + fEdep / MeV);  // fEdepEM += fEdep
    }
    else if (pd == G4PionPlus::PionPlus() || pd == G4PionMinus::PionMinus()) {
      gEvent.set_edep_pi(gEvent.edep_pi() + fEdep / MeV);  // fEdepPI += fEdep
    }
    else if (pd == G4Proton::Proton() || pd == G4AntiProton::AntiProton()) {
      gEvent.set_edep_p(gEvent.edep_p() + fEdep / MeV);  // fEdepP += fEdep
    }
  }
}

void AddLeakingParticle(const G4Track* track)
{
  const G4ParticleDefinition* pd = track->GetDefinition();
  const G4StepPoint* sp = track->GetStep()->GetPreStepPoint();
  const G4double ekin = sp->GetKineticEnergy();
  if (ekin <= 0.0) {
    G4cout << "### AddLeakingParticle " << pd->GetParticleName() << "  Eprestep(MeV)=" << ekin
           << " trackID=" << track->GetTrackID() << G4endl;
    return;
  }

  const G4ThreeVector& pos = sp->GetPosition();
  const G4ThreeVector& dir = sp->GetMomentumDirection();
  G4double x = pos.x();
  G4double y = pos.y();
  G4double z = pos.z();
  G4double vx = dir.x();
  G4double vy = dir.y();
  G4double vz = dir.z();

  G4bool isLeaking = false;
  G4int leakDir = -1;  // 0 forward, 1 backward, 2 side (fNneu_forw/_back/_leak)

  // Forward
  const G4double del = 0.001 * CLHEP::mm;
  if (std::abs(z - fAbsZ0) < del && vz > 0.0) {
    isLeaking = true;
    leakDir = 0;

    // Backward
  }
  else if (std::abs(z + fAbsZ0) < del && vz < 0.0) {
    isLeaking = true;
    leakDir = 1;

    // Side
  }
  else if (std::abs(z) <= fAbsZ0 + del && x * vx + y * vy > 0.0
           && std::abs(x * x + y * y - fR2) < del * fRadius)
  {
    isLeaking = true;
    leakDir = 2;
  }

  if (isLeaking) {
    gEvent.add_leak_pdg(pd->GetPDGEncoding());
    gEvent.add_leak_dir(leakDir);
  }
}

class GrpcStackingAction : public StackingAction
{
public:
  G4ClassificationOfNewTrack ClassifyNewTrack(const G4Track* aTrack) override
  {
    G4ClassificationOfNewTrack status = StackingAction::ClassifyNewTrack(aTrack);

    if (aTrack->GetTrackStatus() == fAlive) {
      ScoreNewTrack(aTrack);
    }

    return status;
  }
};

class GrpcSteppingAction : public G4UserSteppingAction
{
public:
  void UserSteppingAction(const G4Step* aStep) override
  {
    const G4String& volume = aStep->GetPreStepPoint()->GetPhysicalVolume()->GetName();

    if (volume == "Target") {
      AddTargetStep(aStep);
    }
    else if (volume == "Check") {
      const G4Track* track = aStep->GetTrack();
      if (track->GetTrackID() > 1) {
        AddLeakingParticle(track);
      }
    }
  }
};

class GrpcEventAction : public EventAction
{
public:
  explicit GrpcEventAction(std::shared_ptr<grpc::Channel> channel) : fClient(channel) {}

  void BeginOfEventAction(const G4Event* evt) override
  {
    EventAction::BeginOfEventAction(evt);
    gEvent.Clear();
    gEvent.set_event_id(evt->GetEventID());
  }

  void EndOfEventAction(const G4Event* evt) override
  {
    EventAction::EndOfEventAction(evt);
    fClient.SendHadr01Event(gEvent);
    TrajectoryStream::SendEvent(fClient, evt);
  }

private:
  GrpcClient fClient;
};

class GrpcRunAction : public RunAction
{
public:
  explicit GrpcRunAction(std::shared_ptr<grpc::Channel> channel) : fClient(channel) {}

  void BeginOfRunAction(const G4Run* aRun) override
  {
    RunAction::BeginOfRunAction(aRun);
    BeginOfRun();
    if (auto sent = GeometryStream::SendForRun(fClient)) {
      G4cout << "Geometry sent over gRPC: " << sent << " bytes" << G4endl;
    }
  }

private:
  GrpcClient fClient;
};



int main(int argc, char** argv)
{
  if (argc < 2) {
    G4cerr << "Usage: " << argv[0] << " macro.in [--physics NAME] [--grpc-host HOST:PORT]"
           << G4endl;
    return 1;
  }

  G4String macroFile, physName, grpcHost = "localhost:50051";
  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--grpc-host") == 0 && i + 1 < argc) {
      grpcHost = argv[++i];
    }
    else if (std::strcmp(argv[i], "--physics") == 0 && i + 1 < argc) {
      physName = argv[++i];
    }
    else {
      macroFile = argv[i];
    }
  }

  auto* runManager = G4RunManagerFactory::CreateRunManager(G4RunManagerType::SerialOnly);

  auto channel = grpc::CreateChannel(grpcHost, grpc::InsecureChannelCredentials());
  G4cout << "gRPC -> " << grpcHost << G4endl;

  G4VModularPhysicsList* phys = nullptr;
  char* path = std::getenv("PHYSLIST");
  if (physName.empty() && path) {
    physName = G4String(path);
  }
  G4cout << "PhysicsList: " << physName << G4endl;
  G4PhysListFactory factory;
  if (!physName.empty() && factory.IsReferencePhysList(physName)) {
    phys = factory.GetReferencePhysList(physName);
  }
  if (!phys) {
    phys = new PhysicsList();
  }

  runManager->SetUserInitialization(new DetectorConstruction());
  runManager->SetUserInitialization(phys);

  runManager->SetUserAction(new PrimaryGeneratorAction());
  runManager->SetUserAction(new GrpcRunAction(channel));
  runManager->SetUserAction(new GrpcEventAction(channel));
  runManager->SetUserAction(new GrpcStackingAction());
  runManager->SetUserAction(new GrpcSteppingAction());

  TrajectoryStream::Enable();

  // Batch mode
  G4UImanager* UI = G4UImanager::GetUIpointer();
  G4String command = "/control/execute ";
  const G4int status = UI->ApplyCommand(command + macroFile);

  delete runManager;
  return status;
}
