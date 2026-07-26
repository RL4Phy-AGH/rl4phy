import grpc
import rl4phy_pb2
import rl4phy_pb2_grpc

channel = grpc.insecure_channel("localhost:50051")
stub = rl4phy_pb2_grpc.SendServiceStub(channel)

b1 = rl4phy_pb2.Data(event_scoring=rl4phy_pb2.EventScoring(edep=0.042, event_id=7))
stub.SendData(b1)

muon = rl4phy_pb2.Data(
    step_hit=rl4phy_pb2.StepHit(
        x=1.0, y=2.0, z=3.0, px=0.1, py=0.2, pz=0.3, e_kin=160.0,
        track_id=1, event_id=7, parent_id=0, pdg=13,
    )
)
stub.SendData(muon)
print("Sent B1 + MUonE test messages")
