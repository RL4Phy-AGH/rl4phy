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

  void SendStepData(float x, float y, float z,
                    float px, float py, float pz, float energy, int track_id) {
    rl4phys::Data packet;
    packet.set_x(x);
    packet.set_y(y);
    packet.set_z(z);
    packet.set_px(px);
    packet.set_py(py);
    packet.set_pz(pz);
    packet.set_energy(energy);
    packet.set_track_id(track_id);

    rl4phys::Reply reply;
    grpc::ClientContext context;
    const grpc::Status status = fStub->SendData(&context, packet, &reply);
  }

private:
  std::unique_ptr<rl4phys::SendService::Stub> fStub;
};
