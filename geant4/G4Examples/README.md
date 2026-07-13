# Geant4 / examples / basic / B1

[official code source](https://gitlab.cern.ch/geant4/geant4/-/tree/master/examples/basic/B1)

🎯 Purpose
* Basic validation example of Geant4 simulation chain
* Tests particle transport + energy deposition (Edep)
* Serves as a template for user applications

🧱 Geometry
* Simple box-shaped world volume
* One central scoring volume (box)
* Homogeneous materials (air / simple absorber)
* No segmentation or detector complexity

⚛️ Particle Source
* G4ParticleGun
* Single primary particle
* Fixed energy and direction (typically +Z axis)
* No beam spread or distributions

🧠 Core Simulation Components
* G4RunManager → controls full simulation lifecycle
* DetectorConstruction → defines geometry + materials
* PrimaryGeneratorAction → defines incoming particle
* PhysicsList (e.g. FTFP_BERT) → interaction physics
* ActionInitialization → connects user actions

📊 Scoring / Output
* Energy deposition per step (Edep)
* Accumulated per event
* Recorded via:
  * SteppingAction and/or
  * G4VSensitiveDetector
  * G4AnalysisManager (histograms/ntuples)

🔁 Conceptual Flow
Particle Gun → World → Scoring Volume → Stepping Action → Edep → Histogram/Output
