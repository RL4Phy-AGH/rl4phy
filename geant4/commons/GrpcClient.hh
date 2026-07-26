#pragma once

#include <grpcpp/grpcpp.h>

#include "rl4phy.grpc.pb.h"

#include <chrono>
#include <iostream>
#include <memory>
#include <string>

class GrpcClient {
public:
  explicit GrpcClient(std::shared_ptr<grpc::Channel> channel)
      : fStub(rl4phys::SendService::NewStub(std::move(channel))) {}

  void SendEventScoring(float edep_MeV, int event_id = -1) {
    rl4phys::Data packet;
    auto* scoring = packet.mutable_event_scoring();
    scoring->set_edep(edep_MeV);
    scoring->set_event_id(event_id);

    rl4phys::Reply reply;
    grpc::ClientContext context;
    fStub->SendData(&context, packet, &reply);
  }

  void SendStepHit(float x, float y, float z,
                   float px, float py, float pz, float e_kin_MeV,
                   int track_id = -1, int event_id = -1, int parent_id = -1,
                   int pdg = 0) {
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

    rl4phys::Reply reply;
    grpc::ClientContext context;
    fStub->SendData(&context, packet, &reply);
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
  std::unique_ptr<rl4phys::SendService::Stub> fStub;
};
