#include "G4RunManagerFactory.hh"
#include "G4UImanager.hh"
#include "G4UIExecutive.hh"
#include "G4VisExecutive.hh"
#include "G4GDMLParser.hh"
#include "FTFP_BERT.hh"
#include "DetectorConstruction.hh"
#include "ActionInitialization.hh"
#include <iostream>
#include <string>

// The G4 side: build the detector, optionally dump it to GDML, then run a beam
// or open a viewer.
//   --gdml <file>          load geometry from GDML instead of building it in code
//   --export-gdml <file>   write the geometry out to GDML (for the Python side)
//   --vis [macro]          open the OpenGL viewer (default macros/vis.mac)
//   <macro>                run this macro (default: one beamOn)
int main(int argc, char** argv) {
  std::cout << "RL4PHY-GEANT START" << std::endl;

  std::string gdmlFile, macro, exportGdml;
  bool useVis = false;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--gdml" && i + 1 < argc) gdmlFile = argv[++i];
    else if (a == "--export-gdml" && i + 1 < argc) exportGdml = argv[++i];
    else if (a == "--vis") useVis = true;
    else macro = a;
  }

  auto* runManager =
      G4RunManagerFactory::CreateRunManager(G4RunManagerType::Serial);
  auto* detector = new DetectorConstruction(gdmlFile);
  runManager->SetUserInitialization(detector);
  runManager->SetUserInitialization(new FTFP_BERT());
  runManager->SetUserInitialization(new ActionInitialization());
  runManager->Initialize();

  if (!exportGdml.empty()) {
    G4GDMLParser parser;
    // false keeps the names clean (Station1, ...); otherwise Geant4 tacks a
    // pointer-hash onto every name, and Python has to read this file.
    parser.Write(exportGdml, detector->GetWorldPV(), false);
    std::cout << "GDML EXPORTED: " << exportGdml << std::endl;
  }

  auto* uiMgr = G4UImanager::GetUIpointer();
  if (useVis) {
    int uiArgc = 1;
    char* uiArgv[] = {argv[0]};
    auto* uiExec = new G4UIExecutive(uiArgc, uiArgv);
    auto* visMgr = new G4VisExecutive();
    visMgr->Initialize();
    uiMgr->ApplyCommand("/control/execute " +
                        (macro.empty() ? std::string("macros/vis.mac") : macro));
    uiExec->SessionStart();
    delete uiExec;
    delete visMgr;
  } else if (!macro.empty()) {
    uiMgr->ApplyCommand("/control/execute " + macro);
  } else if (exportGdml.empty()) {
    uiMgr->ApplyCommand("/run/beamOn 1");  // export-only runs skip the beam
  }

  delete runManager;
  std::cout << "RL4PHY-GEANT END" << std::endl;
  return 0;
}
