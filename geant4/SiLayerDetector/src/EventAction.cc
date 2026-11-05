#include "EventAction.hh"
#include "RunAction.hh"

#include "G4EmProcessSubType.hh"
#include "G4Event.hh"
#include "G4HadronicProcessType.hh"
#include "G4ParticleDefinition.hh"
#include "G4Run.hh"
#include "G4RunManager.hh"
#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4SystemOfUnits.hh"
#include "G4Track.hh"
#include "G4VPhysicalVolume.hh"
#include "G4VProcess.hh"

namespace {

void SetPoint(siplate::Point* p, const G4ThreeVector& v) {
  p->set_x(static_cast<float>(v.x() / mm));
  p->set_y(static_cast<float>(v.y() / mm));
  p->set_z(static_cast<float>(v.z() / mm));
}

void SetLorentz(siplate::LorentzVector* l, const G4StepPoint* point) {
  const G4ThreeVector p = point->GetMomentum();
  l->set_e(point->GetTotalEnergy() / MeV);
  l->set_px(p.x() / MeV);
  l->set_py(p.y() / MeV);
  l->set_pz(p.z() / MeV);
}

std::uint32_t InteractionBit(const G4VProcess* proc) {
  if (!proc || proc->GetProcessType() != fHadronic) return siplate::INTERACTION_NONE;
  switch (proc->GetProcessSubType()) {
    case fHadronElastic:
      return siplate::INTERACTION_HADRON_ELASTIC;
    case fHadronInelastic:
      return siplate::INTERACTION_HADRON_INELASTIC;
    default:
      return siplate::INTERACTION_OTHER_HADRONIC;
  }
}

// How a track that ended in the layer ended.
siplate::Fate EndFate(const G4VProcess* proc) {
  if (proc) {
    const auto type = proc->GetProcessType();
    if (type == fHadronic || type == fDecay) return siplate::FATE_DESTROYED;
    if (type == fElectromagnetic && proc->GetProcessSubType() == fAnnihilation) {
      return siplate::FATE_DESTROYED;
    }
  }
  return siplate::FATE_STOPPED;
}

}  // namespace

void EventAction::BeginOfEventAction(const G4Event* event) {
  fEvent.Clear();
  fEvent.set_run_id(G4RunManager::GetRunManager()->GetCurrentRun()->GetRunID());
  fEvent.set_event_id(event->GetEventID());
  fWriteSteps = fRunAction->StepsWanted(event->GetEventID());
  fOpenHits.clear();
  fBirths.clear();
}

G4int EventAction::ProcessIndex(const G4VProcess* process) {
  if (!process) return -1;
  const auto it = fProcessCache.find(process);
  if (it != fProcessCache.end()) return it->second;
  const G4int index = fRunAction->ProcessIndex(process->GetProcessName());
  fProcessCache.emplace(process, index);
  return index;
}

siplate::StepHit& EventAction::OpenHit(const G4Step* step) {
  const G4Track* track = step->GetTrack();
  const G4StepPoint* pre = step->GetPreStepPoint();

  fOpenHits[track->GetTrackID()] = fEvent.hits_size();
  auto& hit = *fEvent.add_hits();
  hit.set_track_id(track->GetTrackID());
  hit.set_event_id(fEvent.event_id());
  hit.set_parent_id(track->GetParentID());
  hit.set_pdg(track->GetDefinition()->GetPDGEncoding());
  hit.set_volume(pre->GetPhysicalVolume()->GetName());
  SetLorentz(hit.mutable_entry(), pre);
  SetPoint(hit.mutable_entry_pos(), pre->GetPosition());
  hit.set_entry_time(static_cast<float>(pre->GetGlobalTime() / ns));
  hit.set_creator_step(-1);

  if (track->GetCurrentStepNumber() == 1) {
    hit.set_origin(siplate::ORIGIN_CREATED_INSIDE);
    // The pointer alone could be a reused address: check parent and vertex.
    const auto it = fBirths.find(track);
    if (it != fBirths.end()) {
      const Birth& b = it->second;
      if (b.parentID == track->GetParentID() && b.vertex == track->GetVertexPosition()) {
        hit.set_creator_step(b.creatorStep);
      }
      fBirths.erase(it);
    }
  } else {
    hit.set_origin(siplate::ORIGIN_ENTERED);
  }
  return hit;
}

void EventAction::RecordStep(const G4Step* step) {
  const G4Track* track = step->GetTrack();
  const G4StepPoint* post = step->GetPostStepPoint();
  const G4VProcess* proc = post->GetProcessDefinedStep();

  const auto open = fOpenHits.find(track->GetTrackID());
  siplate::StepHit& hit =
      open != fOpenHits.end() ? *fEvent.mutable_hits(open->second) : OpenHit(step);

  const G4int k = hit.n_steps();
  hit.set_n_steps(k + 1);
  hit.set_path_length(hit.path_length() + static_cast<float>(step->GetStepLength() / mm));
  hit.set_edep(hit.edep() + static_cast<float>(step->GetTotalEnergyDeposit() / MeV));
  hit.set_interactions(hit.interactions() | InteractionBit(proc));
  SetLorentz(hit.mutable_exit(), post);
  SetPoint(hit.mutable_exit_pos(), post->GetPosition());

  const auto* secondaries = step->GetSecondaryInCurrentStep();
  const int nSecondaries = secondaries ? static_cast<int>(secondaries->size()) : 0;
  for (int i = 0; i < nSecondaries; ++i) {
    const G4Track* s = (*secondaries)[i];
    fBirths[s] = Birth{track->GetTrackID(), k, s->GetPosition()};
  }

  if (fWriteSteps) {
    auto* sp = hit.add_steps();
    SetPoint(sp->mutable_pos(), post->GetPosition());
    SetLorentz(sp->mutable_p(), post);
    sp->set_edep(static_cast<float>(step->GetTotalEnergyDeposit() / MeV));
    sp->set_edep_nonion(static_cast<float>(step->GetNonIonizingEnergyDeposit() / MeV));
    sp->set_step_length(static_cast<float>(step->GetStepLength() / mm));
    sp->set_process(ProcessIndex(proc));
    sp->set_n_secondaries(nSecondaries);
  }

  // Close the hit when the track leaves the layer or ends in it. A track at rest
  // but alive (e.g. a positron before annihilation) keeps its hit open.
  const auto status = track->GetTrackStatus();
  if (post->GetStepStatus() == fGeomBoundary) {
    hit.set_fate(siplate::FATE_EXITED);
    fOpenHits.erase(track->GetTrackID());
  } else if (status == fStopAndKill || status == fKillTrackAndSecondaries) {
    hit.set_fate(EndFate(proc));
    fOpenHits.erase(track->GetTrackID());
  } else if (status == fStopButAlive) {
    hit.set_fate(siplate::FATE_STOPPED);
  }
}

void EventAction::EndOfEventAction(const G4Event*) {
  fRunAction->WriteEvent(fEvent);
}
