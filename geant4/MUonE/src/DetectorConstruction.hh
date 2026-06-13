#pragma once
#include "G4VUserDetectorConstruction.hh"
#include <string>

class G4VPhysicalVolume;

// The detector is built in code (BuildMUonE). BuildFromGDML is there as a
// fallback if someone hands us a GDML instead. We keep the world volume around
// so main can export the geometry back out to GDML.
class DetectorConstruction : public G4VUserDetectorConstruction {
public:
  explicit DetectorConstruction(std::string gdmlFile = "");
  G4VPhysicalVolume* Construct() override;
  G4VPhysicalVolume* GetWorldPV() const { return fWorldPV; }

private:
  G4VPhysicalVolume* BuildMUonE();     // geometry in C++ (3 stations)
  G4VPhysicalVolume* BuildFromGDML();  // optional import
  std::string fGdmlFile;
  G4VPhysicalVolume* fWorldPV = nullptr;
};
