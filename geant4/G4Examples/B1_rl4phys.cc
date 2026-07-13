//
// ********************************************************************
// * Main program of the B1 example (batch only) adapted for RL4PHYS  *
// ********************************************************************
//

#include "DetectorConstruction.hh"
#include "ActionInitialization.hh"

#include "G4RunManagerFactory.hh"
#include "G4MTRunManager.hh"

#include "G4SteppingVerbose.hh"
#include "G4UImanager.hh"

#include "QBBC.hh"

#include "G4GDMLParser.hh"
#include "G4TransportationManager.hh"

#include "Randomize.hh"

#include <cstring>
#include <cstdlib>


using namespace B1;


// --------------------------------------------------------------------

int main(int argc, char** argv)
{

  if (argc < 2)
  {
    G4cerr << "Usage:" << G4endl;
    G4cerr << "  " << argv[0]
           << " macro.mac [--threads N]"
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
      new ActionInitialization()
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

    G4GDMLParser parser;


    auto world =
        G4TransportationManager::
        GetTransportationManager()
        ->GetNavigatorForTracking()
        ->GetWorldVolume();


    parser.Write(
        argv[2],
        world
    );


    G4cout
        << "Geometry exported to: "
        << argv[2]
        << G4endl;


    delete runManager;

    return 0;
  }



  // ------------------------------------------------------------
  // Batch macro execution
  //
  // ./exampleB1 run.mac --threads 8
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
