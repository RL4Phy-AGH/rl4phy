import grpc
import rl4phy_pb2
import rl4phy_pb2_grpc

channel = grpc.insecure_channel("localhost:50051")
stub = rl4phy_pb2_grpc.SendServiceStub(channel)

msg = rl4phy_pb2.Data(x=1.0, y=2.0, z=3.0, px=0.1, py=0.2, pz=0.3, energy=160.0)
stub.SendData(msg)
print("Sent test data")
