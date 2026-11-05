#include "DetectorConstruction.hh"

#include "G4NistManager.hh"
#include "G4Box.hh"
#include "G4LogicalVolume.hh"
#include "G4PVPlacement.hh"
#include "G4ThreeVector.hh"
#include "G4VisAttributes.hh"
#include "G4Colour.hh"
#include "G4UserLimits.hh"

G4VPhysicalVolume* DetectorConstruction::Construct() {
  auto* nist = G4NistManager::Instance();
  auto* vacuum = nist->FindOrBuildMaterial("G4_Galactic");
  auto* silicon = nist->FindOrBuildMaterial("G4_Si");

  // World: 10 x 10 x 10 cm
  const G4double worldHalf = 5. * cm;
  auto* worldS = new G4Box("World", worldHalf, worldHalf, worldHalf);
  auto* worldLV = new G4LogicalVolume(worldS, vacuum, "World");
  auto* worldPV = new G4PVPlacement(nullptr, G4ThreeVector(), worldLV, "World",
                                    nullptr, false, 0, true);

  // Si plate: 5 x 5 cm, 300 um thick, centred in the world, normal along z
  auto* plateS = new G4Box("SiPlate", fPlateSizeXY / 2, fPlateSizeXY / 2,
                           fPlateThickness / 2);
  fPlateLV = new G4LogicalVolume(plateS, silicon, "SiPlate");
  new G4PVPlacement(nullptr, G4ThreeVector(), fPlateLV, "SiPlate",
                    worldLV, false, 0, true);

  fPlateLV->SetUserLimits(new G4UserLimits(fMaxStep));

  auto* va = new G4VisAttributes(G4Colour(0.2, 0.4, 0.9, 0.6));
  va->SetForceSolid(true);
  fPlateLV->SetVisAttributes(va);
  worldLV->SetVisAttributes(G4VisAttributes::GetInvisible());

  return worldPV;
}
