#include "DetectorConstruction.hh"
#include "G4NistManager.hh"
#include "G4Box.hh"
#include "G4LogicalVolume.hh"
#include "G4PVPlacement.hh"
#include "G4RotationMatrix.hh"
#include "G4VisAttributes.hh"
#include "G4Colour.hh"
#include "G4SystemOfUnits.hh"
#include "G4GDMLParser.hh"
#include <iostream>

DetectorConstruction::DetectorConstruction(std::string gdmlFile)
    : fGdmlFile(std::move(gdmlFile)) {}

G4VPhysicalVolume* DetectorConstruction::Construct() {
  fWorldPV = fGdmlFile.empty() ? BuildMUonE() : BuildFromGDML();
  // The world is just the air box around everything, so don't draw it. Works
  // for both the in-code build and an imported GDML.
  fWorldPV->GetLogicalVolume()->SetVisAttributes(G4VisAttributes::GetInvisible());
  return fWorldPV;
}

// The detector, put together in code: 3 silicon stations along the beam at
// z = -300/0/+300 mm, the middle one tilted 30 deg (stereo readout), no targets
// (that's the MUonE scope). The geometry really lives here; `--export-gdml`
// dumps it back out to GDML for the Python side.
G4VPhysicalVolume* DetectorConstruction::BuildMUonE() {
  auto* nist = G4NistManager::Instance();
  auto* air = nist->FindOrBuildMaterial("G4_AIR");
  auto* si = nist->FindOrBuildMaterial("G4_Si");

  // World box, 2 m a side, with lots of room around the stations at +/-300 mm.
  // (A box is the cheapest shape for Geant4 to navigate.)
  auto* worldSolid = new G4Box("World", 1.0 * m, 1.0 * m, 1.0 * m);  // G4Box wants half-lengths
  auto* worldLV = new G4LogicalVolume(worldSolid, air, "World");
  auto* worldPV =
      new G4PVPlacement(nullptr, {}, worldLV, "World", nullptr, false, 0, true);

  auto* slab = new G4Box("Station", 100.0 * mm, 100.0 * mm, 5.0 * mm);  // 200x200x10 mm
  auto* slabLV = new G4LogicalVolume(slab, si, "Station");
  auto* slabVis = new G4VisAttributes(G4Colour(0.2, 0.6, 1.0));  // light blue
  slabVis->SetForceSolid(true);
  slabLV->SetVisAttributes(slabVis);

  // same slab placed three times; the copy number tells them apart, and the
  // middle one gets the tilt.
  new G4PVPlacement(nullptr, {0, 0, -300 * mm}, slabLV, "Station1", worldLV, false, 1, true);

  auto* stereo = new G4RotationMatrix();
  stereo->rotateZ(30 * deg);
  new G4PVPlacement(stereo, {0, 0, 0}, slabLV, "Station2", worldLV, false, 2, true);

  new G4PVPlacement(nullptr, {0, 0, 300 * mm}, slabLV, "Station3", worldLV, false, 3, true);

  std::cout << "GEOMETRY BUILT (C++): MUonE 3 stations, world daughters="
            << worldLV->GetNoDaughters() << std::endl;
  return worldPV;
}

G4VPhysicalVolume* DetectorConstruction::BuildFromGDML() {
  G4GDMLParser parser;
  parser.Read(fGdmlFile, false);  // false = skip schema validation (offline)
  G4VPhysicalVolume* world = parser.GetWorldVolume();
  std::cout << "GDML LOADED: " << fGdmlFile << std::endl;
  std::cout << "GDML WORLD: " << world->GetName()
            << " daughters=" << world->GetLogicalVolume()->GetNoDaughters()
            << std::endl;
  return world;
}
