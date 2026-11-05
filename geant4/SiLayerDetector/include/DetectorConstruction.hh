#ifndef DETECTOR_CONSTRUCTION_HH
#define DETECTOR_CONSTRUCTION_HH

#include "G4VUserDetectorConstruction.hh"
#include "G4SystemOfUnits.hh"

class G4LogicalVolume;
class G4VPhysicalVolume;

// World of vacuum with a single silicon plate centred at the origin, its normal
// along z (the beam axis).
class DetectorConstruction : public G4VUserDetectorConstruction {
public:
  DetectorConstruction() = default;
  ~DetectorConstruction() override = default;

  G4VPhysicalVolume* Construct() override;

  G4LogicalVolume* GetPlateLV() const { return fPlateLV; }
  G4double GetPlateThickness() const { return fPlateThickness; }
  G4double GetPlateSizeXY() const { return fPlateSizeXY; }
  G4double GetMaxStep() const { return fMaxStep; }

private:
  G4LogicalVolume* fPlateLV = nullptr;

  G4double fPlateThickness = 300. * um;
  G4double fPlateSizeXY = 5. * cm;
  // Maximum step inside the plate, so energy loss and scattering can be followed
  // as a function of depth (300 um / 10 um = ~30 steps). Needs
  // G4StepLimiterPhysics, registered in main.cc.
  G4double fMaxStep = 10. * um;
};

#endif
