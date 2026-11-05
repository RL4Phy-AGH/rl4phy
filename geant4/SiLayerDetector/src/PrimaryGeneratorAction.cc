#include "PrimaryGeneratorAction.hh"

#include "G4ParticleGun.hh"
#include "G4ParticleTable.hh"
#include "G4SystemOfUnits.hh"
#include "G4ThreeVector.hh"
#include "G4Event.hh"

PrimaryGeneratorAction::PrimaryGeneratorAction() {
  fGun = new G4ParticleGun(1);
  auto* p = G4ParticleTable::GetParticleTable()->FindParticle("proton");
  fGun->SetParticleDefinition(p);
  fGun->SetParticleEnergy(100. * MeV);
  fGun->SetParticleMomentumDirection(G4ThreeVector(0, 0, 1));
  fGun->SetParticlePosition(G4ThreeVector(0, 0, -4. * cm));
}

PrimaryGeneratorAction::~PrimaryGeneratorAction() {
  delete fGun;
}

void PrimaryGeneratorAction::GeneratePrimaries(G4Event* event) {
  fGun->GeneratePrimaryVertex(event);
}
