#include "RunAction.hh"
#include <iostream>

// Print the column names once at the start of a run, so the STEP lines that
// follow are readable without counting fields.
void RunAction::BeginOfRunAction(const G4Run*) {
  std::cout << "# STEP eventID trackID parentID particle "
               "x y z[mm] px py pz[MeV] Etot Ekin[MeV] t[ns] stepLen[mm] "
               "volume process\n";
}
