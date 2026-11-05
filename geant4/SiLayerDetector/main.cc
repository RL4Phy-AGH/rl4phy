// Minimal Geant4 application: a world with a single silicon plate.
//
// Usage:
//   siplate                        interactive session with visualisation
//   siplate <macro>                batch, e.g. macros/sim.mac
//   siplate --gdml <file>          export the geometry to GDML and exit
//   siplate --gdml <file> <macro>  run the macro, then export the geometry
//
// The GDML volume names are the Geant4 names (no pointer suffixes), so they
// match StepHit.volume in the output.
//
// The physics list is taken from the PHYSLIST environment variable (any Geant4
// reference list, e.g. FTFP_BERT, FTFP_BERT_EMZ). The default, FTFP_BERT_EMZ,
// uses G4EmStandardPhysics_option4, the most accurate EM option for energy-loss
// fluctuations and multiple scattering in thin layers.

#include "G4GDMLParser.hh"
#include "G4PhysListFactory.hh"
#include "G4RunManagerFactory.hh"
#include "G4StepLimiterPhysics.hh"
#include "G4TransportationManager.hh"
#include "G4UIExecutive.hh"
#include "G4UImanager.hh"
#include "G4VModularPhysicsList.hh"
#include "G4VPhysicalVolume.hh"
#include "G4VisExecutive.hh"

#include "ActionInitialization.hh"
#include "DetectorConstruction.hh"

#include <cstdlib>
#include <filesystem>
#include <string>

namespace {

void Usage() {
  G4cerr << "usage: siplate [--gdml <file>] [<macro>]" << G4endl;
}

// Writes the world volume as built by DetectorConstruction to a GDML file.
bool ExportGDML(const G4String& file) {
  const G4VPhysicalVolume* world = G4TransportationManager::GetTransportationManager()
                                       ->GetNavigatorForTracking()
                                       ->GetWorldVolume();
  if (!world) {
    G4cerr << "GDML export: the geometry is not built (/run/initialize)" << G4endl;
    return false;
  }
  std::filesystem::remove(file.c_str());  // G4GDMLParser refuses to overwrite
  G4GDMLParser parser;
  parser.Write(file, world, false);  // false: no pointer suffixes in the names
  G4cout << "GDML export: geometry written to " << file << G4endl;
  return true;
}

}  // namespace

int main(int argc, char** argv) {
  G4String macro;
  G4String gdmlFile;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--gdml") {
      if (++i == argc) {
        Usage();
        return 1;
      }
      gdmlFile = argv[i];
    } else if (macro.empty() && arg.rfind("--", 0) != 0) {
      macro = arg;
    } else {
      Usage();
      return 1;
    }
  }

  G4UIExecutive* ui = nullptr;
  if (macro.empty() && gdmlFile.empty()) ui = new G4UIExecutive(argc, argv);

  const char* env = std::getenv("PHYSLIST");
  const G4String physListName = (env && *env) ? env : "FTFP_BERT_EMZ";
  G4PhysListFactory factory;
  G4VModularPhysicsList* physicsList = factory.GetReferencePhysList(physListName);
  if (!physicsList) {
    G4cerr << "Unknown physics list: " << physListName << G4endl;
    return 1;
  }
  physicsList->RegisterPhysics(new G4StepLimiterPhysics);  // G4UserLimits in SiPlate

  auto* runManager = G4RunManagerFactory::CreateRunManager(G4RunManagerType::Default);
  runManager->SetUserInitialization(new DetectorConstruction);
  runManager->SetUserInitialization(physicsList);
  runManager->SetUserInitialization(new ActionInitialization(physListName));

  auto* visManager = new G4VisExecutive;
  visManager->Initialize();

  auto* UImanager = G4UImanager::GetUIpointer();

  if (ui) {
    UImanager->ApplyCommand("/run/initialize");
    UImanager->ApplyCommand("/vis/open OGL 600x600-0+0");
    UImanager->ApplyCommand("/vis/drawVolume");
    UImanager->ApplyCommand("/vis/viewer/set/viewpointThetaPhi 70 20");
    UImanager->ApplyCommand("/vis/scene/add/trajectories smooth");
    UImanager->ApplyCommand("/vis/scene/endOfEventAction accumulate");
    ui->SessionStart();
    delete ui;
  } else if (!macro.empty()) {
    UImanager->ApplyCommand("/control/execute " + macro);
  } else {
    runManager->Initialize();  // export only: build the geometry, no events
  }

  const G4bool ok = gdmlFile.empty() || ExportGDML(gdmlFile);

  delete visManager;
  delete runManager;
  return ok ? 0 : 1;
}
