import colorsys
import hashlib
import os
import sys
import zlib
from collections import Counter
from concurrent import futures
from typing import NamedTuple

import grpc
import numpy as np
import rerun as rr
from loguru import logger

import rl4phy_pb2
import rl4phy_pb2_grpc
from dataset_writer import ParquetStepWriter, maybe_create_step_writer
from gdml_geometry import PlacedCylinder, PlacedMesh, PlacedSolid, parse_gdml

RERUN_GRPC_PORT = 9876

GDML_GRPC_RECEIVED_PATH = os.environ.get(
    "GDML_GRPC_RECEIVED_PATH", "/tmp/rl4phy_received.gdml"
)

MAX_LABELS_DRAWN = int(os.environ.get("RL4PHY_MAX_LABELS", "0"))

# Every branch of the oneof, read off the proto so the handler table below and
# its test cannot drift from it.
PAYLOADS = {f.name for f in rl4phy_pb2.Data.DESCRIPTOR.oneofs_by_name["payload"].fields}


_PARSED_GDML: dict[str, list[PlacedSolid]] = {}
_PARSED_GDML_MAX = 8


def _parse_received_gdml(gdml: bytes) -> list[PlacedSolid]:
    # Written on every arrival, cached or not: pyg4ometry takes a path, not bytes.
    with open(GDML_GRPC_RECEIVED_PATH, "wb") as gdml_file:
        gdml_file.write(gdml)

    digest = hashlib.sha256(gdml).hexdigest()
    cached = _PARSED_GDML.get(digest)
    if cached is not None:
        return cached

    solids = parse_gdml(GDML_GRPC_RECEIVED_PATH)
    if len(_PARSED_GDML) >= _PARSED_GDML_MAX:
        del _PARSED_GDML[next(iter(_PARSED_GDML))]
    _PARSED_GDML[digest] = solids
    return solids


def _path_color(path: str) -> list[int]:
    # Stable across runs, unlike hash(), so a subdetector keeps its colour.
    hue = (zlib.crc32(path.encode()) % 997) / 997.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.95)
    return [round(r * 255), round(g * 255), round(b * 255)]


_geometry_entities: set[str] = set()


def log_detector(solids: list[PlacedSolid], slot: int) -> None:
    # On the timeline rather than static, because B5 rebuilds its detector mid
    # session and scrubbing back must show the geometry of that event's run.
    rr.set_time("event_index", sequence=slot)

    groups: dict[tuple[str, str], list[PlacedSolid]] = {}
    for solid in solids:
        groups.setdefault((solid.path, type(solid).__name__), []).append(solid)

    entities = {f"world/{path}" for path, _ in groups}
    # Flat rather than recursive: world is an ancestor of every entity here, so a
    # recursive clear would reach the ones this geometry is about to fill.
    for gone in _geometry_entities - entities:
        rr.log(gone, rr.Clear(recursive=False))
    _geometry_entities.clear()
    _geometry_entities.update(entities)

    for (path, _), group in groups.items():
        color = _path_color(path)
        entity = f"world/{path}"

        if isinstance(group[0], PlacedMesh):
            template = group[0]
            # Meshes have no wireframe mode, so an envelope is made translucent.
            alpha = 70 if template.is_container else 255
            rr.log(
                entity,
                rr.Mesh3D(
                    vertex_positions=template.local_vertices_mm,
                    triangle_indices=template.triangles,
                    albedo_factor=[*color, alpha],
                ),
                rr.InstancePoses3D(
                    translations=[s.center_mm for s in group],
                    quaternions=[s.quaternion_xyzw for s in group],
                ),
            )
            continue

        shared = {
            "centers": [s.center_mm for s in group],
            "quaternions": [s.quaternion_xyzw for s in group],
            "colors": color,
            "labels": [f"{s.name} #{s.copy_number}" for s in group],
            "show_labels": len(group) <= MAX_LABELS_DRAWN,
            "fill_mode": "majorwireframe" if group[0].is_container else "solid",
        }
        if isinstance(group[0], PlacedCylinder):
            archetype = rr.Cylinders3D(
                lengths=[s.length_mm for s in group],
                radii=[s.radius_mm for s in group],
                **shared,
            )
        else:
            archetype = rr.Boxes3D(
                half_sizes=[s.half_size_mm for s in group],
                **shared,
            )
        rr.log(entity, archetype)


# Geant4's drawByCharge palette, exactly as G4Colour names it, so a track comes
# out the same colour here as in the OpenGL window this view is checked against.
def _charge_color(charge: float) -> list[int]:
    if charge > 0.0:
        return [0, 0, 255]
    if charge < 0.0:
        return [255, 0, 0]
    return [0, 255, 0]


class DrawableTrack(NamedTuple):
    points: np.ndarray  # (N, 3), mm
    color: list[int]
    species: str
    track_id: int
    initial_e_kin: float


class AgentServer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self, writer: ParquetStepWriter | None) -> None:
        self.msg = 0
        self._events_seen = 0
        self._writer = writer
        self._handlers = {
            "event_scoring": self._log_b1_event,
            "step_hit": self._record_step_hit,
            "event_step_hits": self._record_event_step_hits,
            "b5_event": self._log_b5_event,
            "event_trajectories": self._log_event_trajectories,
        }
        missing = PAYLOADS - set(self._handlers)
        if missing:
            logger.warning(f"No handler for payload(s): {sorted(missing)}")

    def SendDataStream(self, request_iterator, context):
        for request in request_iterator:
            self._handle_data(request)
        return rl4phy_pb2.Reply()

    def _handle_data(self, request) -> None:
        self.msg += 1
        kind = request.WhichOneof("payload")
        handler = self._handlers.get(kind)
        if handler is None:
            logger.warning(f"[{self.msg}] unknown payload {kind!r}")
            return
        handler(getattr(request, kind))

    def _log_b1_event(self, event) -> None:
        logger.info(
            f"[{self.msg}] B1 event_scoring: event={event.event_id} "
            f"edep = {event.edep:.6f} MeV"
        )

    def _record_event_step_hits(self, event) -> None:
        logger.info(
            f"[{self.msg}] crossings: event={event.event_id}  "
            f"{len(event.hits)} crossing(s)"
        )
        for hit in event.hits:
            self._record_step_hit(hit)

    def _record_step_hit(self, hit) -> None:
        if self._writer is None:
            return
        if not hit.HasField("exit"):
            # A crossing without an exit is not a crossing, and a zeroed exit
            # would read as the whole beam energy lost.
            logger.warning(
                f"[{self.msg}] step_hit without exit: "
                f"event={hit.event_id} track={hit.track_id}"
            )
            return
        try:
            self._writer.append_step_hit(hit)
        except Exception:
            logger.exception("Dataset: recording disabled after a write error")
            self._writer = None

    # The event id cannot be the timeline position: Geant4 restarts it at 0 on
    # every /run/beamOn and the wire carries no run id, so ids repeat across runs.
    # This counts forward instead.
    def _next_slot(self) -> int:
        slot = self._events_seen
        self._events_seen += 1
        return slot

    # Trajectories arrive whole, only once their stepping is over, so nothing
    # here needs buffering.
    def _log_event_trajectories(self, event) -> None:
        tracks = [
            DrawableTrack(
                # The wire flattens each polyline into x,y,z triples.
                points=np.asarray(t.points, dtype=np.float32).reshape(-1, 3),
                color=_charge_color(t.charge),
                species=t.particle_name,
                track_id=t.track_id,
                initial_e_kin=t.initial_e_kin,
            )
            for t in event.trajectories
        ]
        self._draw_tracks(event.event_id, self._next_slot(), tracks)

    def _draw_tracks(
        self, event_id: int, slot: int, tracks: list[DrawableTrack]
    ) -> None:
        colors = np.array([t.color for t in tracks], dtype=np.uint8).reshape(-1, 3)
        points = (
            np.concatenate([t.points for t in tracks])
            if tracks
            else np.zeros((0, 3), dtype=np.float32)
        )
        point_colors = np.repeat(colors, [len(t.points) for t in tracks], axis=0)

        # Named event_index so nobody reads a slider position as a Geant4 event
        # number; the real id is logged beside the tracks below.
        rr.set_time("event_index", sequence=slot)

        # Both archetypes are logged even for an empty event, since that is what
        # clears the previous one off the screen.
        rr.log(
            "world/tracks/lines",
            rr.LineStrips3D(
                [t.points for t in tracks],
                colors=colors,
                labels=[f"{t.species} #{t.track_id}" for t in tracks],
                show_labels=len(tracks) <= MAX_LABELS_DRAWN,
            ),
            rr.AnyValues(
                event_id=event_id,
                initial_e_kin=[t.initial_e_kin for t in tracks],
            ),
        )
        rr.log("world/tracks/points", rr.Points3D(points, colors=point_colors))

        species = Counter(t.species for t in tracks)
        tally = ", ".join(f"{n} {name}" for name, n in species.most_common())
        logger.info(
            f"[{self.msg}] tracks: event={event_id} (index {slot})  "
            f"{len(tracks)} track(s), {len(points)} point(s)  "
            f"[{tally}]"
        )

    def _log_b5_event(self, event) -> None:
        chamber_hits = ", ".join(str(n) for n in event.drift_chamber_hits)
        # An arm the particle missed reports -1 instead of a hit time.
        hodoscope_times = ", ".join(
            "none" if t < 0.0 else f"{t:.2f}" for t in event.hodoscope_time
        )
        logger.info(
            f"[{self.msg}] B5 b5_event: event={event.event_id}  "
            f"chamber hits = [{chamber_hits}]  "
            f"hodoscope t = [{hodoscope_times}] ns  "
            f"EM edep = {sum(event.em_cal_edep):.6f} MeV "
            f"in {len(event.em_cal_edep)} cells  "
            f"Had edep = {sum(event.had_cal_edep):.6f} MeV "
            f"in {len(event.had_cal_edep)} cells"
        )

    def SendGeometry(self, request, context):
        logger.info(f"Received GDML over gRPC: {len(request.gdml)} bytes")
        try:
            solids = _parse_received_gdml(request.gdml)
        except Exception:
            logger.exception("Could not parse the GDML received over gRPC")
            return rl4phy_pb2.Reply()

        if not solids:
            logger.warning("GDML received over gRPC has no drawable volumes")
            return rl4phy_pb2.Reply()

        # Where the next event will land, which is where geometry has to go
        # for Rerun's latest-at lookup to pair every event with the detector
        # it was simulated on. Logged even when the bytes were already parsed:
        # B5/run1.mac ends at the arm angle it started at, and skipping the
        # log would resolve its last run back to the geometry before it.
        slot = self._events_seen
        logger.info(f"Loaded {len(solids)} volume(s) from gRPC GDML (index {slot})")
        log_detector(solids, slot)
        return rl4phy_pb2.Reply()


def start_server():
    server_uri = rr.serve_grpc(grpc_port=RERUN_GRPC_PORT)
    logger.info(f"Rerun gRPC server on port {RERUN_GRPC_PORT} ({server_uri})")
    logger.info(
        "Connect the viewer with: "
        f"rerun --connect rerun+http://127.0.0.1:{RERUN_GRPC_PORT}/proxy"
    )

    # A property of the recording, not of any one detector, so a producer that
    # sends no geometry still gets its tracks drawn the right way up.
    rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Y_UP, static=True)

    # One worker: the handlers share the slot counter and the writer without a
    # lock, and geometry has to be drawn before the stream that follows it.
    servicer = AgentServer(maybe_create_step_writer())
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(servicer, server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    logger.info("Listening on port 50051, waiting for Geant4 data...")
    server.wait_for_termination()


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout)
    rr.init("rl4phy")
    start_server()
