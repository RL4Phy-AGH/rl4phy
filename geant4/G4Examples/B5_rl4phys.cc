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
#include "G4EventManager.hh"
#include "G4HCofThisEvent.hh"
#include "G4ParticleDefinition.hh"
#include "G4SDManager.hh"
#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4SystemOfUnits.hh"
#include "G4Track.hh"
#include "G4UserSteppingAction.hh"
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


// The trajectories the OpenGL viewer draws, sent step by step. B5 ships no
// stepping action of its own, so unlike B1 there is no base implementation to
// call first.
//
// No volume filter, unlike MUonE/src/SteppingAction.cc: the flight through the
// air and the curve inside the magnet are what make the picture readable, so
// steps in the World volume are wanted too. What has to go is the shower tail
// in the two calorimeters, thousands of soft steps per event that add nothing
// to look at, and that is what the kinetic energy cut is for.
class RL4PhysSteppingAction : public G4UserSteppingAction
{
  public:
    RL4PhysSteppingAction(std::shared_ptr<grpc::Channel> channel, G4double minEkin)
      : fClient(std::move(channel)), fMinEkin(minEkin)
    {}

    // One line per worker thread once the run manager tears the thread down, so
    // the threshold can be tuned from the log without paying for it per step.
    ~RL4PhysSteppingAction() override
    {
      G4cout << "Step hits sent: " << fSent << ", suppressed below "
             << fMinEkin / MeV << " MeV: " << fSuppressed << G4endl;
    }

    void UserSteppingAction(const G4Step* step) override
    {
      const G4StepPoint* pre = step->GetPreStepPoint();

      // A cut of 0 sends everything, since no step has a negative energy.
      if (pre->GetKineticEnergy() < fMinEkin) {
        ++fSuppressed;
        return;
      }

      const G4Track* track = step->GetTrack();
      const auto pos = pre->GetPosition();
      const auto p = pre->GetMomentum();

      // Read at the pre-step point in mm and MeV, the same convention
      // MUonE/src/SteppingAction.cc uses, so both feed the Python side the same
      // step_hit.
      rl4phys::StepHit hit;
      hit.set_x(static_cast<float>(pos.x() / mm));
      hit.set_y(static_cast<float>(pos.y() / mm));
      hit.set_z(static_cast<float>(pos.z() / mm));
      hit.set_px(static_cast<float>(p.x() / MeV));
      hit.set_py(static_cast<float>(p.y() / MeV));
      hit.set_pz(static_cast<float>(p.z() / MeV));
      hit.set_e_kin(static_cast<float>(pre->GetKineticEnergy() / MeV));
      hit.set_track_id(track->GetTrackID());
      hit.set_event_id(G4EventManager::GetEventManager()
                         ->GetConstCurrentEvent()
                         ->GetEventID());
      hit.set_parent_id(track->GetParentID());
      hit.set_pdg(track->GetDefinition()->GetPDGEncoding());

      fClient.SendStepHit(hit);
      ++fSent;
    }

  private:
    // One client per stepping action, i.e. one per worker thread.
    GrpcClient fClient;
    G4double fMinEkin;
    G4long fSent = 0;
    G4long fSuppressed = 0;
};


class RL4PhysActionInitialization : public ActionInitialization
{
  public:
    RL4PhysActionInitialization(std::shared_ptr<grpc::Channel> channel, G4double minEkin)
      : fChannel(std::move(channel)), fMinEkin(minEkin)
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

      SetUserAction(new RL4PhysSteppingAction(fChannel, fMinEkin));
    }

  private:
    std::shared_ptr<grpc::Channel> fChannel;
    G4double fMinEkin;
};


// --------------------------------------------------------------------

int main(int argc, char** argv)
{

  if (argc < 2)
  {
    G4cerr << "Usage:" << G4endl;
    G4cerr << "  " << argv[0]
           << " macro.mac [--threads N] [--grpc-host HOST:PORT]"
              " [--track-min-ekin MeV]"
           << G4endl;

    G4cerr << "  " << argv[0]
           << " --export-gdml geometry.gdml"
           << G4endl;

    G4cerr << "    --track-min-ekin  drop step hits below this kinetic energy,"
              " 0 sends every step (default 1.0 MeV)"
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

  // The showers in the two calorimeters would otherwise drown the trajectories
  // in soft steps, so only what is worth drawing goes out by default.
  G4double trackMinEkin = 1.0 * MeV;


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

    else if (std::strcmp(argv[i], "--track-min-ekin") == 0 && i + 1 < argc)
    {
      trackMinEkin = std::atof(argv[++i]) * MeV;
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
      new RL4PhysActionInitialization(channel, trackMinEkin)
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
