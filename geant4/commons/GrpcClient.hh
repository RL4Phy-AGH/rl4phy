#pragma once

#include <grpcpp/grpcpp.h>

#include "rl4phy.grpc.pb.h"

#include <memory>

class GrpcClient {
public:
  explicit GrpcClient(std::shared_ptr<grpc::Channel> channel)
      : fStub(rl4phys::SendService::NewStub(std::move(channel))) {}

  void SendEventScoring(float edep_MeV) {
    rl4phys::Data packet;
    packet.mutable_event_scoring()->set_edep(edep_MeV);

    rl4phys::Reply reply;
    grpc::ClientContext context;
    fStub->SendData(&context, packet, &reply);
  }

  void SendStepHit(float x, float y, float z,
                   float px, float py, float pz, float e_kin_MeV) {
    rl4phys::Data packet;
    auto* hit = packet.mutable_step_hit();
    hit->set_x(x);
    hit->set_y(y);
    hit->set_z(z);
    hit->set_px(px);
    hit->set_py(py);
    hit->set_pz(pz);
    hit->set_e_kin(e_kin_MeV);

    rl4phys::Reply reply;
    grpc::ClientContext context;
    fStub->SendData(&context, packet, &reply);
  }

private:
  std::unique_ptr<rl4phys::SendService::Stub> fStub;
};
