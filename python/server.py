import grpc
from concurrent import futures

import rl4phy_pb2
import rl4phy_pb2_grpc


class AgentServer(rl4phy_pb2_grpc.SendServiceServicer):
    def SendData(self, request, context):
        print(
            f"x={request.x:.2f} y={request.y:.2f} z={request.z:.2f} "
            f"px={request.px:.2f} py={request.py:.2f} pz={request.pz:.2f} "
            f"E={request.energy:.2f}"
        )
        return rl4phy_pb2.Reply()


def start_server():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(AgentServer(), server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    print("Listening on port 50051, waiting for Geant4 data...")
    server.wait_for_termination()


if __name__ == "__main__":
    start_server()
