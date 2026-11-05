#include "RunAction.hh"
#include "DetectorConstruction.hh"
#include "RecordFile.hh"

#include "siplate.pb.h"

#include "G4Element.hh"
#include "G4GenericMessenger.hh"
#include "G4IonisParamMat.hh"
#include "G4LogicalVolume.hh"
#include "G4LossTableManager.hh"
#include "G4VEmProcess.hh"
#include "G4Material.hh"
#include "G4MaterialCutsCouple.hh"
#include "G4PhysicalVolumeStore.hh"
#include "G4ProcessTable.hh"
#include "G4ProductionCuts.hh"
#include "G4ProductionCutsTable.hh"
#include "G4Run.hh"
#include "G4RunManager.hh"
#include "G4SystemOfUnits.hh"
#include "G4Threading.hh"
#include "G4VPhysicalVolume.hh"
#include "G4Version.hh"
#include "G4ios.hh"

#include <algorithm>

namespace {

constexpr unsigned kSchemaVersion = 1;

enum class Role { Sequential, Master, Worker };

Role CurrentRole() {
  if (!G4Threading::IsMultithreadedApplication()) return Role::Sequential;
  return G4Threading::IsMasterThread() ? Role::Master : Role::Worker;
}

}  // namespace

RunAction::RunAction(const G4String& physicsList) : fPhysicsList(physicsList) {
  fMessenger = std::make_unique<G4GenericMessenger>(this, "/siplate/output/",
                                                    "SiPlate output control");
  fMessenger->DeclareProperty("tag", fTag, "Output file name: <tag>.pb");
  fMessenger->DeclareProperty("writeSteps", fWriteSteps,
                              "Store the steps of each hit (StepHit.steps)");
  fMessenger->DeclareProperty("referenceEvents", fReferenceEvents,
                              "Events with ID < n form the reference sample, "
                              "the rest the target sample (recorded in the "
                              "run header, split by the analysis)");
  fMessenger->DeclareProperty("maxStepEvents", fMaxStepEvents,
                              "Store steps for at most n events, starting at "
                              "the first target event (-1 = all target events)");
}

RunAction::~RunAction() {
  if (fPart.is_open()) fPart.close();
}

void RunAction::BuildProcessList() {
  fProcesses.clear();
  fProcessIndex.clear();
  const auto* names = G4ProcessTable::GetProcessTable()->GetNameList();
  if (names) {
    for (const auto& n : *names) fProcesses.push_back(n);
  }
  // EM processes wrapped by a general process (e.g. "phot", "compt" inside
  // G4GammaGeneralProcess) are not in the process table but do define steps.
  for (const auto* proc : G4LossTableManager::Instance()->GetEmProcessVector()) {
    if (proc) fProcesses.push_back(proc->GetProcessName());
  }
  std::sort(fProcesses.begin(), fProcesses.end());
  fProcesses.erase(std::unique(fProcesses.begin(), fProcesses.end()), fProcesses.end());
  for (std::size_t i = 0; i < fProcesses.size(); ++i) {
    fProcessIndex[fProcesses[i]] = static_cast<G4int>(i);
  }
}

G4int RunAction::ProcessIndex(const G4String& name) const {
  const auto it = fProcessIndex.find(name);
  return it == fProcessIndex.end() ? -1 : it->second;
}

void RunAction::BeginOfRunAction(const G4Run*) {
  const Role role = CurrentRole();
  BuildProcessList();

  // Parts of an earlier, interrupted run with the same tag must not be merged
  // into this one.
  if (role != Role::Worker) RecordFile::RemoveParts(Base());

  if (role != Role::Master) {
    const int id = role == Role::Worker ? G4Threading::G4GetThreadId() : 0;
    fPart.open(RecordFile::PartPath(Base(), id), std::ios::binary);
  }
}

void RunAction::WriteEvent(const siplate::Event& event) {
  event.SerializeToString(&fBuffer);
  RecordFile::WriteEventFrame(fPart, event.event_id(), fBuffer);
}

void RunAction::EndOfRunAction(const G4Run* run) {
  const Role role = CurrentRole();
  if (fPart.is_open()) fPart.close();
  if (role == Role::Worker) return;

  // Master: the workers have finished their runs and closed their parts by now.
  siplate::Record header;
  FillHeader(run, *header.mutable_header());
  const long events = RecordFile::Merge(Base(), header);
  if (events != run->GetNumberOfEvent()) {
    G4cerr << "RunAction: " << Base() << ".pb has " << events
           << " events, expected " << run->GetNumberOfEvent() << G4endl;
  }
  G4cout << "RunAction: run " << run->GetRunID() << " (" << run->GetNumberOfEvent()
         << " events) written to " << Base() << ".pb" << G4endl;
}

// Everything the analysis needs to compute theory predictions without hard-coding
// the setup: layer geometry, material constants (incl. Sternheimer density-effect
// parameters) and production thresholds. The beam is not here: the master thread
// has no particle gun in MT mode, so the consumer takes the primary's PDG code
// and energy from the hits.
void RunAction::FillHeader(const G4Run* run, siplate::RunHeader& h) const {
  h.set_schema_version(kSchemaVersion);
  h.set_run_id(run->GetRunID());
  h.set_n_events(run->GetNumberOfEventToBeProcessed());
  h.set_reference_events(fReferenceEvents);
  h.set_geant4_version(std::to_string(G4VERSION_NUMBER));
  h.set_physics_list(fPhysicsList);
  h.set_n_threads(G4RunManager::GetRunManager()->GetNumberOfThreads());
  h.set_write_steps(fWriteSteps);
  h.set_max_step_events(fMaxStepEvents);
  for (const auto& p : fProcesses) h.add_processes(p);

  const auto* det = dynamic_cast<const DetectorConstruction*>(
      G4RunManager::GetRunManager()->GetUserDetectorConstruction());
  if (!det || !det->GetPlateLV()) return;

  const G4LogicalVolume* lv = det->GetPlateLV();
  const G4Material* mat = lv->GetMaterial();
  const G4IonisParamMat* ion = mat->GetIonisation();
  const G4VPhysicalVolume* pv =
      G4PhysicalVolumeStore::GetInstance()->GetVolume(lv->GetName(), false);

  auto* layer = h.add_layers();
  layer->set_volume(pv ? pv->GetName() : lv->GetName());
  layer->set_material(mat->GetName());
  layer->set_thickness_mm(det->GetPlateThickness() / mm);
  layer->set_size_xy_mm(det->GetPlateSizeXY() / mm);
  layer->set_z_center_mm(pv ? pv->GetTranslation().z() / mm : 0.);
  layer->set_max_step_mm(det->GetMaxStep() / mm);
  layer->set_density_g_cm3(mat->GetDensity() / (g / cm3));
  layer->set_radiation_length_mm(mat->GetRadlen() / mm);
  layer->set_mean_excitation_ev(ion->GetMeanExcitationEnergy() / eV);

  auto* de = layer->mutable_density_effect();
  de->set_c(ion->GetCdensity());
  de->set_x0(ion->GetX0density());
  de->set_x1(ion->GetX1density());
  de->set_a(ion->GetAdensity());
  de->set_m(ion->GetMdensity());
  de->set_delta0(ion->GetD0density());

  const auto* elements = mat->GetElementVector();
  const G4double* fractions = mat->GetFractionVector();
  for (std::size_t i = 0; i < elements->size(); ++i) {
    const G4Element* el = (*elements)[i];
    auto* e = layer->add_elements();
    e->set_symbol(el->GetSymbol());
    e->set_z(el->GetZ());
    e->set_a_g_mol(el->GetA() / (g / mole));
    e->set_mass_fraction(fractions[i]);
  }

  auto* cutsTable = G4ProductionCutsTable::GetProductionCutsTable();
  const G4ProductionCuts* cuts = cutsTable->GetDefaultProductionCuts();
  auto* range = layer->mutable_cut_range_mm();
  range->set_gamma(cuts->GetProductionCut("gamma") / mm);
  range->set_electron(cuts->GetProductionCut("e-") / mm);
  range->set_positron(cuts->GetProductionCut("e+") / mm);
  range->set_proton(cuts->GetProductionCut("proton") / mm);
  if (const G4MaterialCutsCouple* couple = cutsTable->GetMaterialCutsCouple(mat, cuts)) {
    const G4int idx = couple->GetIndex();
    auto threshold = [&](G4ProductionCutsIndex kind) {
      return (*cutsTable->GetEnergyCutsVector(kind))[idx] / MeV;
    };
    auto* energy = layer->mutable_cut_energy_mev();
    energy->set_gamma(threshold(idxG4GammaCut));
    energy->set_electron(threshold(idxG4ElectronCut));
    energy->set_positron(threshold(idxG4PositronCut));
    energy->set_proton(threshold(idxG4ProtonCut));
  }
}
