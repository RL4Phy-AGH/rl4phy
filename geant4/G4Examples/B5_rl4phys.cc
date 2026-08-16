//
// ********************************************************************
// * Main program of the B5 example (batch only) adapted for RL4PHYS  *
// ********************************************************************
//

#include "ActionInitialization.hh"
#include "Constants.hh"
#include "DetectorConstruction.hh"
#include "EventAction.hh"
#include "HodoscopeHit.hh"
#include "PrimaryGeneratorAction.hh"
#include "RunAction.hh"

#include "G4RunManagerFactory.hh"
#include "G4MTRunManager.hh"
#include "G4RunManager.hh"

#include "G4SteppingVerbose.hh"
#include "G4UImanager.hh"

#include "FTFP_BERT.hh"
#include "G4StepLimiterPhysics.hh"

#include "Randomize.hh"

#include "G4Event.hh"
#include "G4HCofThisEvent.hh"
#include "G4SDManager.hh"
#include "G4SystemOfUnits.hh"
#include "G4VHitsCollection.hh"

#include "GeometryExport.hh"
#include "GrpcClient.hh"

#include <grpcpp/grpcpp.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <cstdlib>
#include <limits>
#include <memory>


using namespace B5;


namespace {

// Reported when a hodoscope saw no hit at all in the event.
constexpr float kNoHodoscopeTime = -1.f;


// Same lookup as in B5/src/EventAction.cc, which keeps its helper file local.
// The base class warns about a missing collection for the very same Ids, so
// this one stays quiet and lets the caller substitute a default.
G4VHitsCollection* GetHC(const G4Event* event, G4int collId)
{
  if (collId < 0) return nullptr;

  auto hce = event->GetHCofThisEvent();
  if (!hce) return nullptr;

  return hce->GetHC(collId);
}

}  // namespace


class GrpcEventAction : public EventAction
{
  public:
    explicit GrpcEventAction(std::shared_ptr<grpc::Channel> channel)
      : fClient(std::move(channel))
    {}

    void BeginOfEventAction(const G4Event* event) override
    {
      EventAction::BeginOfEventAction(event);

      // The base class resolves these Ids too but keeps them private, so they
      // are looked up once more here (once per worker thread). The names have
      // to stay in sync with B5/src/EventAction.cc.
      if (fHodHCID[0] < 0) {
        auto sdManager = G4SDManager::GetSDMpointer();

        const std::array<G4String, kDim> hodName = {
          {"hodoscope1/hodoscopeColl", "hodoscope2/hodoscopeColl"}};
        const std::array<G4String, kDim> driftName = {
          {"chamber1/driftChamberColl", "chamber2/driftChamberColl"}};

        for (G4int iDet = 0; iDet < kDim; ++iDet) {
          fHodHCID[iDet] = sdManager->GetCollectionID(hodName[iDet]);
          fDriftHCID[iDet] = sdManager->GetCollectionID(driftName[iDet]);
        }
      }
    }

    void EndOfEventAction(const G4Event* event) override
    {
      // The example fills its histograms, ntuple and the per cell energies
      // here, so it has to run before anything is read back below.
      EventAction::EndOfEventAction(event);

      rl4phys::B5Event b5Event;
      b5Event.set_event_id(event->GetEventID());

      // One value per arm: chamber 1/2 and hodoscope 1/2.
      for (G4int iDet = 0; iDet < kDim; ++iDet) {
        b5Event.add_drift_chamber_hits(NofHits(event, fDriftHCID[iDet]));
        b5Event.add_hodoscope_time(FirstHodoscopeTime(event, fHodHCID[iDet]));
      }

      // One value per calorimeter cell: kNofEmCells then kNofHadCells.
      for (auto edep : GetEmCalEdep()) {
        b5Event.add_em_cal_edep(static_cast<float>(edep / MeV));
      }

      for (auto edep : GetHadCalEdep()) {
        b5Event.add_had_cal_edep(static_cast<float>(edep / MeV));
      }

      // A failed send is reported once per client, i.e. once per worker thread.
      fClient.SendB5Event(b5Event);
    }

  private:
    static G4int NofHits(const G4Event* event, G4int collId)
    {
      auto hc = GetHC(event, collId);
      return hc ? static_cast<G4int>(hc->GetSize()) : 0;
    }

    // A hodoscope collection holds one hit per strip, each already carrying the
    // earliest time seen in that strip, so the smallest of them is the time of
    // the first hit in the hodoscope.
    static float FirstHodoscopeTime(const G4Event* event, G4int collId)
    {
      auto hc = GetHC(event, collId);
      if (!hc || hc->GetSize() == 0) return kNoHodoscopeTime;

      auto first = std::numeric_limits<G4double>::max();

      for (std::size_t i = 0; i < hc->GetSize(); ++i) {
        auto hit = static_cast<HodoscopeHit*>(hc->GetHit(i));
        first = std::min(first, hit->GetTime());
      }

      return static_cast<float>(first / ns);
    }

    // One client per event action, i.e. one per worker thread.
    GrpcClient fClient;
    std::array<G4int, kDim> fHodHCID = {-1, -1};
    std::array<G4int, kDim> fDriftHCID = {-1, -1};
};


class RL4PhysActionInitialization : public ActionInitialization
{
  public:
    explicit RL4PhysActionInitialization(std::shared_ptr<grpc::Channel> channel)
      : fChannel(std::move(channel))
    {}

    void BuildForMaster() const override
    {
      // The master thread runs no event, so it needs no gRPC client.
      ActionInitialization::BuildForMaster();
    }

    void Build() const override
    {
      SetUserAction(new PrimaryGeneratorAction);

      auto eventAction = new GrpcEventAction(fChannel);
      SetUserAction(eventAction);

      // RunAction books the ntuple columns that point at the vectors owned by
      // the event action, so it gets the gRPC one.
      SetUserAction(new RunAction(eventAction));
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
  G4String gdmlFile = "";

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

    else if (std::strcmp(argv[i], "--export-gdml") == 0 && i + 1 < argc)
    {
      gdmlFile = argv[++i]; // handled after the kernel is initialized
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


  auto physicsList = new FTFP_BERT;

  physicsList->RegisterPhysics(new G4StepLimiterPhysics());

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
  // ./B5_rl4phys --export-gdml geometry.gdml
  // ------------------------------------------------------------

  if (!gdmlFile.empty())
  {

    G4bool written =
        GeometryExport::WriteToFile(
            gdmlFile
        );


    if (written)
    {
      G4cout
          << "Geometry exported to: "
          << gdmlFile
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


    if (auto sent = GeometryExport::SendOverGrpc(geometryClient))
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
  // ./B5_rl4phys run1.mac --threads 8
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
