#pragma once

#include <grpcpp/grpcpp.h>

#include "rl4phy.grpc.pb.h"

#include <iostream>
#include <memory>

class GrpcClient {
public:
  explicit GrpcClient(std::shared_ptr<grpc::Channel> channel)
      : fStub(rl4phys::SendService::NewStub(std::move(channel))) {}

  void SendStepData(float x, float y, float z,
                    float px, float py, float pz, float energy) {
    rl4phys::Data packet;
    packet.set_x(x);
    packet.set_y(y);
    packet.set_z(z);
    packet.set_px(px);
    packet.set_py(py);
    packet.set_pz(pz);
    packet.set_energy(energy);

    rl4phys::Reply reply;
    grpc::ClientContext context;
    const grpc::Status status = fStub->SendData(&context, packet, &reply);
  }

private:
  std::unique_ptr<rl4phys::SendService::Stub> fStub;
};
