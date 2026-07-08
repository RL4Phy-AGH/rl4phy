import grpc
from concurrent import futures

import rerun as rr

import rl4phy_pb2
import rl4phy_pb2_grpc

# Rerun gRPC server port. serve_grpc() binds 0.0.0.0, so publishing this port
# from the container lets the host-side viewer attach with
#   rerun --connect rerun+http://127.0.0.1:9876/proxy
RERUN_GRPC_PORT = 9876

# Hardcoded MUonE geometry, kept in lockstep with the Geant4 side
# (geant4/MUonE/src/DetectorConstruction.cc): three 200x200x10 mm silicon
# stations along the beam at z = -300 / 0 / +300 mm, the middle one tilted
# 30 deg about z (stereo readout). #18 replaces this with the real GDML geometry.
STATION_HALF_SIZE = (100.0, 100.0, 5.0)  # mm, half-lengths of the 200x200x10 slab
STATION_CENTERS = [
    [0.0, 0.0, -300.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 300.0],
]
STATION_TILTS_DEG = [0.0, 30.0, 0.0]  # rotation about the beam (z) axis
STATION_COLOR = [51, 153, 255]  # light blue, matching the OpenGL prototype


def log_detector() -> None:
    """Log the static station geometry once, before any step data arrives."""
    # Beam runs along +z; use a right-handed, y-up world so the default 3D view
    # frames the stations sensibly.
    rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Y_UP, static=True)
    rr.log(
        "world/stations",
        rr.Boxes3D(
            centers=STATION_CENTERS,
            half_sizes=[STATION_HALF_SIZE] * len(STATION_CENTERS),
            rotation_axis_angles=[
                rr.RotationAxisAngle(axis=[0.0, 0.0, 1.0], angle=rr.Angle(deg=tilt))
                for tilt in STATION_TILTS_DEG
            ],
            colors=STATION_COLOR,
            labels=[f"Station{i + 1}" for i in range(len(STATION_CENTERS))],
            fill_mode="solid",
        ),
        static=True,
    )


class AgentServer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self) -> None:
        self._step = 0
        self._track: list[list[float]] = []

    def SendData(self, request, context):
        print(
            f"x={request.x:.2f} y={request.y:.2f} z={request.z:.2f} "
            f"px={request.px:.2f} py={request.py:.2f} pz={request.pz:.2f} "
            f"E={request.energy:.2f}"
        )

        point = [request.x, request.y, request.z]
        self._track.append(point)

        # One Rerun step per incoming gRPC message so the viewer timeline can be
        # scrubbed. The accumulated points form the muon's path through the stations.
        rr.set_time("step", sequence=self._step)
        self._step += 1
        rr.log("world/track/points", rr.Points3D(self._track, colors=[255, 64, 64]))
        rr.log("world/track/line", rr.LineStrips3D([self._track], colors=[255, 64, 64]))

        return rl4phy_pb2.Reply()


def start_server():
    # Host the Rerun gRPC server in-process; the standalone viewer connects to it.
    server_uri = rr.serve_grpc(grpc_port=RERUN_GRPC_PORT)
    log_detector()
    print(f"Rerun gRPC server on port {RERUN_GRPC_PORT} ({server_uri})")
    print(
        "Connect the viewer with: "
        f"rerun --connect rerun+http://127.0.0.1:{RERUN_GRPC_PORT}/proxy"
    )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(AgentServer(), server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    print("Listening on port 50051, waiting for Geant4 data...")
    server.wait_for_termination()


if __name__ == "__main__":
    rr.init("rl4phy_muone")
    start_server()
