import colorsys
import math
import os
import random
import threading
import time
from concurrent import futures

import grpc

import rerun as rr

import rl4phy_pb2
import rl4phy_pb2_grpc
from gdml_geometry import StationGeometry, parse_gdml

RERUN_GRPC_PORT = 9876

GDML_EXPORT_PATH = os.environ.get("GDML_EXPORT_PATH", "/export/muone.gdml")
GDML_POLL_INTERVAL_S = 1.0

STATION_COLOR = [51, 153, 255]


def _try_load_gdml() -> list[StationGeometry] | None:
    if not os.path.exists(GDML_EXPORT_PATH):
        return None
    try:
        stations = parse_gdml(GDML_EXPORT_PATH)
    except Exception as exc:  # Geant4 may still be mid-write; retry.
        print(f"GDML at {GDML_EXPORT_PATH} not ready yet ({exc!r}), retrying...")
        return None
    if not stations:
        print(f"GDML at {GDML_EXPORT_PATH} has no box-shaped stations yet, retrying...")
        return None
    return stations


def watch_and_log_geometry() -> None:
    while True:
        stations = _try_load_gdml()
        if stations:
            print(f"Loaded {len(stations)} station(s) from GDML: {GDML_EXPORT_PATH}")
            log_detector(stations)
            return
        time.sleep(GDML_POLL_INTERVAL_S)


def log_detector(stations: list[StationGeometry]) -> None:
    rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Y_UP, static=True)
    rr.log(
        "world/stations",
        rr.Boxes3D(
            centers=[s.center_mm for s in stations],
            half_sizes=[s.half_size_mm for s in stations],
            quaternions=[s.quaternion_xyzw for s in stations],
            colors=STATION_COLOR,
            labels=[s.name for s in stations],
            fill_mode="solid",
        ),
        static=True,
    )


def _random_track_color() -> list[int]:
    r, g, b = colorsys.hsv_to_rgb(random.random(), 0.85, 1.0)
    return [round(r * 255), round(g * 255), round(b * 255)]


_DIRECTION_ARROW_LENGTH_MM = 30.0


def _direction_arrow_mm(px: float, py: float, pz: float) -> list[float]:
    magnitude = math.sqrt(px * px + py * py + pz * pz)
    if magnitude == 0.0:
        return [0.0, 0.0, 0.0]
    scale = _DIRECTION_ARROW_LENGTH_MM / magnitude
    return [px * scale, py * scale, pz * scale]


class AgentServer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self) -> None:
        self._step = 0
        self._tracks: dict[int, list[list[float]]] = {}
        self._track_colors: dict[int, list[int]] = {}

    def SendData(self, request, context):
        print(
            f"track={request.track_id} x={request.x:.2f} y={request.y:.2f} z={request.z:.2f} "
            f"px={request.px:.2f} py={request.py:.2f} pz={request.pz:.2f} "
            f"E={request.energy:.2f}"
        )

        track_id = request.track_id
        if track_id not in self._tracks:
            self._tracks[track_id] = []
            self._track_colors[track_id] = _random_track_color()
        track = self._tracks[track_id]
        color = self._track_colors[track_id]

        point = [request.x, request.y, request.z]
        track.append(point)
        direction = _direction_arrow_mm(request.px, request.py, request.pz)

        rr.set_time("step", sequence=self._step)
        self._step += 1
        rr.log(f"world/tracks/{track_id}/points", rr.Points3D(track, colors=color))
        rr.log(f"world/tracks/{track_id}/line", rr.LineStrips3D([track], colors=color))
        rr.log(
            f"world/tracks/{track_id}/direction",
            rr.Arrows3D(origins=[point], vectors=[direction], colors=color),
        )

        return rl4phy_pb2.Reply()


def start_server():
    server_uri = rr.serve_grpc(grpc_port=RERUN_GRPC_PORT)
    print(f"Rerun gRPC server on port {RERUN_GRPC_PORT} ({server_uri})")
    print(
        "Connect the viewer with: "
        f"rerun --connect rerun+http://127.0.0.1:{RERUN_GRPC_PORT}/proxy"
    )

    # GrpcClient::SendStepData (C++) doesn't retry, so this port must be open
    # before the GDML wait below, not after.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(AgentServer(), server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    print("Listening on port 50051, waiting for Geant4 data...")

    threading.Thread(target=watch_and_log_geometry, daemon=True).start()

    server.wait_for_termination()


if __name__ == "__main__":
    rr.init("rl4phy_muone")
    start_server()
