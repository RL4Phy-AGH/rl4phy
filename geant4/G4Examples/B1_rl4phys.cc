//
// ********************************************************************
// * Main program of the B1 example (batch only) adapted for RL4PHYS  *
// ********************************************************************
//

#include "DetectorConstruction.hh"
#include "ActionInitialization.hh"
#include "PrimaryGeneratorAction.hh"
#include "SteppingAction.hh"
#include "RunAction.hh"
#include "EventAction.hh"

#include "G4RunManagerFactory.hh"
#include "G4MTRunManager.hh"
#include "G4RunManager.hh"

#include "G4SteppingVerbose.hh"
#include "G4UImanager.hh"

#include "QBBC.hh"

#include "Randomize.hh"

#include "G4Event.hh"
#include "G4Step.hh"
#include "G4LogicalVolume.hh"
#include "G4SystemOfUnits.hh"

#include "GeometryStream.hh"
#include "GrpcClient.hh"

#include <grpcpp/grpcpp.h>

#include <cstring>
#include <cstdlib>
#include <memory>


using namespace B1;


class GrpcEventAction : public EventAction
{
  public:
    GrpcEventAction(RunAction* runAction, std::shared_ptr<grpc::Channel> channel)
      : EventAction(runAction),
        fClient(std::move(channel))
    {}

    void BeginOfEventAction(const G4Event* event) override
    {
      EventAction::BeginOfEventAction(event);
      fGrpcEdep = 0.;
    }

    void AddEdepForGrpc(G4double edep) { fGrpcEdep += edep; }

    void EndOfEventAction(const G4Event* event) override
    {
      EventAction::EndOfEventAction(event);

      fClient.SendEventScoring(static_cast<float>(fGrpcEdep / MeV),
                               event->GetEventID());
    }

  private:
    // One client per event action, i.e. one per worker thread.
    GrpcClient fClient;
    G4double fGrpcEdep = 0.;
};


class RL4PhysSteppingAction : public SteppingAction
{
  public:
    RL4PhysSteppingAction(EventAction* eventAction, GrpcEventAction* grpcEventAction)
      : SteppingAction(eventAction), fGrpcEventAction(grpcEventAction)
    {}

    void UserSteppingAction(const G4Step* step) override
    {
      SteppingAction::UserSteppingAction(step);

      if (!fScoringVolume) {
        const auto detConstruction = static_cast<const DetectorConstruction*>(
          G4RunManager::GetRunManager()->GetUserDetectorConstruction());
        fScoringVolume = detConstruction->GetScoringVolume();
      }

      G4LogicalVolume* volume =
        step->GetPreStepPoint()->GetTouchableHandle()
          ->GetVolume()->GetLogicalVolume();

      if (volume != fScoringVolume) return;

      fGrpcEventAction->AddEdepForGrpc(step->GetTotalEnergyDeposit());
    }

  private:
    GrpcEventAction* fGrpcEventAction = nullptr;
    G4LogicalVolume* fScoringVolume = nullptr;
};


class RL4PhysActionInitialization : public ActionInitialization
{
  public:
    explicit RL4PhysActionInitialization(std::shared_ptr<grpc::Channel> channel)
      : fChannel(std::move(channel))
    {}

    void BuildForMaster() const override
    {
      ActionInitialization::BuildForMaster();
    }

    void Build() const override
    {
      SetUserAction(new PrimaryGeneratorAction);

      auto runAction = new RunAction;
      SetUserAction(runAction);

      auto eventAction = new GrpcEventAction(runAction, fChannel);
      SetUserAction(eventAction);

      SetUserAction(new RL4PhysSteppingAction(eventAction, eventAction));
    }

  private:
    std::shared_ptr<grpc::Channel> fChannel;
};


// --------------------------------------------------------------------

int main(int argc, char** argv)
{

  if (argc < 2)
  {
    G4cerr << "Usage:" << G4endl;
    G4cerr << "  " << argv[0]
           << " macro.mac [--threads N] [--grpc-host HOST:PORT]"
           << G4endl;

    G4cerr << "  " << argv[0]
           << " --export-gdml geometry.gdml"
           << G4endl;

    return 1;
  }



  // ------------------------------------------------------------
  // Command line options
  // ------------------------------------------------------------

  G4String macroFile = "";
  G4String grpcHost = "localhost:50051";

  G4int nThreads = 1;


  for (int i = 1; i < argc; i++)
  {

    if (std::strcmp(argv[i], "--threads") == 0)
    {

      if (i + 1 < argc)
      {
        nThreads = std::atoi(argv[++i]);
      }
      else
      {
        G4cerr
            << "Missing value after --threads"
            << G4endl;

        return 1;
      }

    }

    else if (std::strcmp(argv[i], "--grpc-host") == 0 && i + 1 < argc)
    {
      grpcHost = argv[++i];
    }

    else if (std::strcmp(argv[i], "--export-gdml") == 0)
    {
      continue; // handled later
    }

    else
    {
      macroFile = argv[i];
    }

  }



  // ------------------------------------------------------------
  // Verbose stepping
  // ------------------------------------------------------------

  G4int precision = 4;
  G4SteppingVerbose::UseBestUnit(precision);



  // ------------------------------------------------------------
  // Run manager
  // ------------------------------------------------------------

  auto runManager =
      G4RunManagerFactory::CreateRunManager(
          G4RunManagerType::MT
      );


  auto mtRunManager =
      dynamic_cast<G4MTRunManager*>(runManager);



  if (mtRunManager)
  {

    mtRunManager->SetNumberOfThreads(
        nThreads
    );


    G4cout
        << "Using multithreading with "
        << nThreads
        << " threads"
        << G4endl;

  }



  auto channel = grpc::CreateChannel(
      grpcHost, grpc::InsecureChannelCredentials());

  G4cout << "gRPC -> " << grpcHost << G4endl;



  // ------------------------------------------------------------
  // User initialization
  // ------------------------------------------------------------

  runManager->SetUserInitialization(
      new DetectorConstruction()
  );


  auto physicsList = new QBBC;

  physicsList->SetVerboseLevel(1);

  runManager->SetUserInitialization(
      physicsList
  );


  runManager->SetUserInitialization(
      new RL4PhysActionInitialization(channel)
  );



  // ------------------------------------------------------------
  // Initialize kernel
  // ------------------------------------------------------------

  runManager->Initialize();



  // ------------------------------------------------------------
  // GDML export mode
  //
  // ./B1_rl4phys --export-gdml geometry.gdml
  // ------------------------------------------------------------

  if (argc >= 3 &&
      std::strcmp(argv[1], "--export-gdml") == 0)
  {

    G4bool written =
        GeometryStream::WriteToFile(
            argv[2]
        );


    if (written)
    {
      G4cout
          << "Geometry exported to: "
          << argv[2]
          << G4endl;
    }


    delete runManager;

    return written ? 0 : 1;
  }



  // ------------------------------------------------------------
  // Geometry hand-off
  //
  // Every run opens by shipping its geometry to the Python side, so the
  // event data that follows has something to be drawn on. Independent of
  // --export-gdml above, which is only an on-disk copy for us to look at.
  // ------------------------------------------------------------

  {
    GrpcClient geometryClient(channel);


    if (auto sent = GeometryStream::SendOverGrpc(geometryClient))
    {
      G4cout
          << "Geometry sent over gRPC: "
          << sent
          << " bytes"
          << G4endl;
    }
  }



  // ------------------------------------------------------------
  // Batch macro execution
  //
  // ./B1_rl4phys run.mac --threads 8
  //
  // ------------------------------------------------------------


  if (macroFile.empty())
  {
    G4cerr
        << "No macro file provided"
        << G4endl;

    delete runManager;

    return 1;
  }



  auto ui = G4UImanager::GetUIpointer();


  G4int status =
      ui->ApplyCommand(
          "/control/execute " + macroFile
      );



  if (status != 0)
  {

    G4cerr
        << "Error executing macro: "
        << macroFile
        << G4endl;

  }

  // ------------------------------------------------------------
  // Cleanup
  // ------------------------------------------------------------

  delete runManager;
  return status;
}
