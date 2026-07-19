import grpc
from concurrent import futures

import rl4phy_pb2
import rl4phy_pb2_grpc


class AgentServer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self):
        self.msg = 0

    def SendData(self, request, context):
        self.msg += 1
        kind = request.WhichOneof("payload")

        if kind == "event_scoring":
            s = request.event_scoring
            print(f"[{self.msg}] B1 event_scoring: edep = {s.edep:.6f} MeV")
        elif kind == "step_hit":
            h = request.step_hit
            print(
                f"[{self.msg}] MUonE step_hit: "
                f"x={h.x:.2f} y={h.y:.2f} z={h.z:.2f} mm  "
                f"px={h.px:.2f} py={h.py:.2f} pz={h.pz:.2f} MeV/c  "
                f"Ekin={h.e_kin:.2f} MeV"
            )
        else:
            print(f"[{self.msg}] unknown payload")

        return rl4phy_pb2.Reply()


def start_server():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(AgentServer(), server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    print("Listening on port 50051 (rl4phys framework)")
    server.wait_for_termination()


if __name__ == "__main__":
    start_server()
