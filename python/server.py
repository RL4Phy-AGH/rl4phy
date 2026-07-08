import math
import os
import threading
import time
from concurrent import futures

import grpc

import rerun as rr

import rl4phy_pb2
import rl4phy_pb2_grpc
from gdml_geometry import StationGeometry, parse_gdml

# Rerun gRPC server port. serve_grpc() binds 0.0.0.0, so publishing this port
# from the container lets the host-side viewer attach with
#   rerun --connect rerun+http://127.0.0.1:9876/proxy
RERUN_GRPC_PORT = 9876

# Geant4 (geant4/MUonE/main.cc, --export-gdml) writes the detector geometry
# here on the shared `gdml_export` volume (see docker-compose.yml). This is
# the real source of truth for the station layout: it comes straight out of
# DetectorConstruction.cc, so a geometry change on the C++ side needs no
# matching edit here. #18's "hand the real geometry over via GDML" is this.
GDML_PATH = os.environ.get("GDML_PATH", "/export/muone.gdml")
GDML_WAIT_TIMEOUT_S = float(os.environ.get("GDML_WAIT_TIMEOUT_S", "60"))
GDML_POLL_INTERVAL_S = 1.0

STATION_COLOR = [51, 153, 255]  # light blue, matching the OpenGL prototype

# Fallback only, used if Geant4 never produces a usable GDML file (e.g. it
# failed to start, or GDML support was compiled out). Kept in lockstep by
# hand with DetectorConstruction.cc as a last resort so the viewer still
# shows *something*; the GDML path above is the one that stays in sync
# automatically and should be what actually runs day to day.
_FALLBACK_HALF_SIZE_MM = (100.0, 100.0, 5.0)
_FALLBACK_CENTERS_MM: list[tuple[float, float, float]] = [
    (0.0, 0.0, -300.0),
    (0.0, 0.0, 0.0),
    (0.0, 0.0, 300.0),
]
_FALLBACK_TILTS_DEG = [0.0, 30.0, 0.0]  # rotation about the beam (z) axis


def _fallback_stations() -> list[StationGeometry]:
    stations = []
    for i, (center, tilt_deg) in enumerate(zip(_FALLBACK_CENTERS_MM, _FALLBACK_TILTS_DEG)):
        half_angle = math.radians(tilt_deg) / 2.0
        stations.append(
            StationGeometry(
                name=f"Station{i + 1}",
                half_size_mm=_FALLBACK_HALF_SIZE_MM,
                center_mm=center,
                quaternion_xyzw=(0.0, 0.0, math.sin(half_angle), math.cos(half_angle)),
            )
        )
    return stations


def load_stations() -> list[StationGeometry]:
    """Wait for Geant4's GDML export and parse it into station geometry.

    Geant4 writes the GDML file right after building the geometry, before it
    opens its gRPC channel to us, so waiting here also means we're ready by
    the time step data starts arriving. Falls back to the hardcoded MUonE
    layout if the file never shows up within the timeout.
    """
    deadline = time.monotonic() + GDML_WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if os.path.exists(GDML_PATH):
            try:
                stations = parse_gdml(GDML_PATH)
            except Exception as exc:  # Geant4 may still be mid-write; retry.
                print(f"GDML at {GDML_PATH} not ready yet ({exc!r}), retrying...")
            else:
                if stations:
                    print(f"Loaded {len(stations)} station(s) from GDML: {GDML_PATH}")
                    return stations
                print(f"GDML at {GDML_PATH} has no box-shaped stations yet, retrying...")
        time.sleep(GDML_POLL_INTERVAL_S)

    print(
        f"WARNING: no usable GDML at {GDML_PATH} after {GDML_WAIT_TIMEOUT_S:.0f}s; "
        "falling back to the hardcoded MUonE layout."
    )
    return _fallback_stations()


def log_detector(stations: list[StationGeometry]) -> None:
    """Log the static station geometry once, before any step data arrives."""
    # Beam runs along +z; use a right-handed, y-up world so the default 3D view
    # frames the stations sensibly.
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
    print(f"Rerun gRPC server on port {RERUN_GRPC_PORT} ({server_uri})")
    print(
        "Connect the viewer with: "
        f"rerun --connect rerun+http://127.0.0.1:{RERUN_GRPC_PORT}/proxy"
    )

    # Bind the step-data gRPC port *before* waiting on the GDML file: Geant4
    # starts trying to connect and stream steps as soon as it's up, and
    # GrpcClient::SendStepData (C++) doesn't retry or surface a connection
    # failure, so any step sent before this port is listening is silently
    # lost. The (up to GDML_WAIT_TIMEOUT_S) geometry wait runs in the
    # background instead, so it never delays opening this port.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(AgentServer(), server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    print("Listening on port 50051, waiting for Geant4 data...")

    def _load_and_log_geometry() -> None:
        log_detector(load_stations())

    threading.Thread(target=_load_and_log_geometry, daemon=True).start()

    server.wait_for_termination()


if __name__ == "__main__":
    rr.init("rl4phy_muone")
    start_server()
