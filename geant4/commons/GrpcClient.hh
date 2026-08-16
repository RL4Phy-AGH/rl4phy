#pragma once

#include <grpcpp/grpcpp.h>

#include "rl4phy.grpc.pb.h"

#include <chrono>
#include <iostream>
#include <memory>
#include <string>

// Threading: one client instance per thread; the grpc::Channel handed to the
// constructor is thread-safe and may be shared between them.
class GrpcClient {
public:
  explicit GrpcClient(std::shared_ptr<grpc::Channel> channel)
      : fStub(rl4phys::SendService::NewStub(std::move(channel))) {}

  void SendEventScoring(float edep_MeV, int event_id) {
    rl4phys::Data packet;
    auto* scoring = packet.mutable_event_scoring();
    scoring->set_edep(edep_MeV);
    scoring->set_event_id(event_id);
    Send(packet);
  }

  // No example sends these any more - the trajectories below replaced them -
  // but they stay for the same reason StepHit stays in the proto: they are the
  // only way to get per-step kinematics over the wire.
  void SendStepHit(float x, float y, float z,
                   float px, float py, float pz, float e_kin_MeV,
                   int track_id, int event_id, int parent_id, int pdg) {
    rl4phys::Data packet;
    auto* hit = packet.mutable_step_hit();
    hit->set_x(x);
    hit->set_y(y);
    hit->set_z(z);
    hit->set_px(px);
    hit->set_py(py);
    hit->set_pz(pz);
    hit->set_e_kin(e_kin_MeV);
    hit->set_track_id(track_id);
    hit->set_event_id(event_id);
    hit->set_parent_id(parent_id);
    hit->set_pdg(pdg);
    Send(packet);
  }

  void SendStepHit(const rl4phys::StepHit& hit) {
    rl4phys::Data packet;
    *packet.mutable_step_hit() = hit;
    Send(packet);
  }

  // One summary per event for the double arm spectrometer (B5). The caller
  // fills the message, since which hit collections make up an event is the
  // example's business, not the transport's.
  void SendB5Event(const rl4phys::B5Event& event) {
    rl4phys::Data packet;
    *packet.mutable_b5_event() = event;
    Send(packet);
  }

  // Every trajectory of one event, filled by TrajectoryStream.hh. One call per
  // event and not one per step: a trajectory only means anything whole, and the
  // per-step version cost thousands of round trips per event for the same
  // picture.
  void SendTrajectories(const rl4phys::EventTrajectories& trajectories) {
    rl4phys::Data packet;
    *packet.mutable_event_trajectories() = trajectories;
    Send(packet);
  }

  // One-off geometry hand-off (issue #18). Unlike the per-step calls this one
  // waits for the server: geometry is sent once at startup and the Python side
  // may still be coming up.
  bool SendGeometry(const std::string& gdmlContent) {
    rl4phys::GeometryFile packet;
    packet.set_gdml(gdmlContent);

    rl4phys::Reply reply;
    grpc::ClientContext context;
    context.set_wait_for_ready(true);
    context.set_deadline(std::chrono::system_clock::now() +
                         std::chrono::seconds(30));
    const grpc::Status status = fStub->SendGeometry(&context, packet, &reply);
    if (!status.ok()) {
      std::cerr << "SendGeometry failed: " << status.error_message()
                << std::endl;
    }
    return status.ok();
  }

private:
  // Every payload goes out the same way: one unary call, no retry, no waiting
  // for the server to come up.
  void Send(const rl4phys::Data& packet) {
    rl4phys::Reply reply;
    grpc::ClientContext context;
    Report(fStub->SendData(&context, packet, &reply));
  }

  // The per-step senders are fire-and-forget, but a dead server would otherwise
  // fail silently for the whole run, so say it once.
  void Report(const grpc::Status& s) {
    if (s.ok() || fWarned) return;
    fWarned = true;
    std::cerr << "gRPC send failed (" << s.error_message()
              << "); further failures suppressed." << std::endl;
  }

  std::unique_ptr<rl4phys::SendService::Stub> fStub;
  bool fWarned = false;
};
