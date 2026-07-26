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
from dataset_writer import maybe_create_step_writer
from gdml_geometry import StationGeometry, parse_gdml

RERUN_GRPC_PORT = 9876

GDML_EXPORT_PATH = os.environ.get("GDML_EXPORT_PATH", "/export/muone.gdml")
GDML_POLL_INTERVAL_S = 1.0

# Where the GDML received over gRPC (issue #18) is dumped before parsing.
GDML_GRPC_RECEIVED_PATH = os.environ.get(
    "GDML_GRPC_RECEIVED_PATH", "/tmp/muone_received.gdml"
)

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
        self.msg = 0
        self._tracks: dict[tuple[int, int], list[list[float]]] = {}
        self._track_colors: dict[tuple[int, int], list[int]] = {}
        self._dataset = maybe_create_step_writer()

    def SendData(self, request, context):
        self.msg += 1
        kind = request.WhichOneof("payload")

        if kind == "event_scoring":
            s = request.event_scoring
            print(
                f"[{self.msg}] B1 event_scoring: event={s.event_id} "
                f"edep = {s.edep:.6f} MeV"
            )
        elif kind == "step_hit":
            self._log_step_hit(request.step_hit)
        else:
            print(f"[{self.msg}] unknown payload")

        return rl4phy_pb2.Reply()

    def _log_step_hit(self, hit) -> None:
        if self._dataset is not None:
            self._dataset.append_step_hit(hit)

        print(
            f"[{self.msg}] MUonE step_hit: "
            f"event={hit.event_id} track={hit.track_id} "
            f"parent={hit.parent_id} pdg={hit.pdg}  "
            f"x={hit.x:.2f} y={hit.y:.2f} z={hit.z:.2f} mm  "
            f"px={hit.px:.2f} py={hit.py:.2f} pz={hit.pz:.2f} MeV/c  "
            f"Ekin={hit.e_kin:.2f} MeV"
        )

        # Track ids restart with every event, so the event has to be part of the
        # key (and of the entity path) to keep the polylines apart.
        key = (hit.event_id, hit.track_id)
        if key not in self._tracks:
            self._tracks[key] = []
            self._track_colors[key] = _random_track_color()
        track = self._tracks[key]
        color = self._track_colors[key]

        point = [hit.x, hit.y, hit.z]
        track.append(point)
        direction = _direction_arrow_mm(hit.px, hit.py, hit.pz)

        entity = f"world/tracks/{hit.event_id}/{hit.track_id}"
        rr.set_time("step", sequence=self.msg)
        rr.log(f"{entity}/points", rr.Points3D(track, colors=color))
        rr.log(f"{entity}/line", rr.LineStrips3D([track], colors=color))
        rr.log(
            f"{entity}/direction",
            rr.Arrows3D(origins=[point], vectors=[direction], colors=color),
        )

    def SendGeometry(self, request, context):
        # Geometry hand-off (issue #18): Geant4 ships the exported GDML over
        # gRPC, so the shared volume is no longer required to see the stations.
        print(f"Received GDML over gRPC: {len(request.gdml)} bytes")
        try:
            with open(GDML_GRPC_RECEIVED_PATH, "wb") as gdml_file:
                gdml_file.write(request.gdml)
            stations = parse_gdml(GDML_GRPC_RECEIVED_PATH)
        except Exception as exc:
            print(f"Could not parse the GDML received over gRPC: {exc!r}")
            return rl4phy_pb2.Reply()

        if stations:
            print(f"Loaded {len(stations)} station(s) from gRPC GDML")
            log_detector(stations)
        else:
            print("GDML received over gRPC has no box-shaped stations")
        return rl4phy_pb2.Reply()


def start_server():
    server_uri = rr.serve_grpc(grpc_port=RERUN_GRPC_PORT)
    print(f"Rerun gRPC server on port {RERUN_GRPC_PORT} ({server_uri})")
    print(
        "Connect the viewer with: "
        f"rerun --connect rerun+http://127.0.0.1:{RERUN_GRPC_PORT}/proxy"
    )

    # GrpcClient::SendStepHit (C++) doesn't retry, so this port must be open
    # before the GDML wait below, not after.
    # max_workers=1 is load-bearing: the servicer's counters and dicts are
    # unsynchronized and Rerun's global step sequence assumes handlers run one at
    # a time. Raising it requires adding locks first.
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
