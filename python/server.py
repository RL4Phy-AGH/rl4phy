import colorsys
import hashlib
import os
import threading
import time
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
from gdml_geometry import PlacedCylinder, PlacedMesh, PlacedSolid, parse_gdml

RERUN_GRPC_PORT = 9876

GDML_GRPC_RECEIVED_PATH = os.environ.get(
    "GDML_GRPC_RECEIVED_PATH", "/tmp/rl4phy_received.gdml"
)

MAX_LABELS_DRAWN = int(os.environ.get("RL4PHY_MAX_LABELS", "0"))

# MUonE marks no end of event, so a quiet stream is the only thing left that can
# say its last event is over.
TRACK_IDLE_FLUSH_S = 1.0


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


_PARTICLES: dict[int, tuple[str, list[int]]] = {
    22: ("gamma", [255, 236, 130]),
    11: ("e-", [90, 160, 255]),
    -11: ("e+", [255, 130, 130]),
    13: ("mu-", [80, 220, 210]),
    -13: ("mu+", [255, 170, 80]),
    211: ("pi+", [205, 140, 255]),
    -211: ("pi-", [140, 130, 255]),
    111: ("pi0", [190, 190, 190]),
    2212: ("proton", [255, 120, 200]),
    2112: ("neutron", [150, 205, 150]),
}


def _particle(pdg: int) -> tuple[str, list[int]]:
    known = _PARTICLES.get(pdg)
    if known:
        return known
    hue = (zlib.crc32(str(pdg).encode()) % 997) / 997.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
    return f"pdg {pdg}", [round(r * 255), round(g * 255), round(b * 255)]


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
    initial_e_kin: float | None = None


class AgentServer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self) -> None:
        self.msg = 0
        # Event id first because track ids restart with every event.
        self._pending: dict[int, dict[tuple[int, int], list[list[float]]]] = {}
        self._current_event: int | None = None
        self._event_slots: dict[int, int] = {}
        self._events_seen = 0
        self._points_drawn: dict[int, int] = {}
        # B5 marks the end of every event and MUonE does not, so which rule
        # applies is read off the stream rather than configured.
        self._event_marker_seen = False
        self._steps_pending_draw = False
        self._msg_at_last_check = 0
        # The buffers are reached from the gRPC worker and the idle flusher.
        self._lock = threading.Lock()

    def SendData(self, request, context):
        with self._lock:
            self.msg += 1
            kind = request.WhichOneof("payload")

            if kind == "event_scoring":
                s = request.event_scoring
                logger.info(
                    f"[{self.msg}] B1 event_scoring: event={s.event_id} "
                    f"edep = {s.edep:.6f} MeV"
                )
            elif kind == "step_hit":
                self._log_step_hit(request.step_hit)
            elif kind == "b5_event":
                self._log_b5_event(request.b5_event)
            elif kind == "event_trajectories":
                self._log_event_trajectories(request.event_trajectories)
            else:
                logger.warning(f"[{self.msg}] unknown payload")

        return rl4phy_pb2.Reply()

    def _log_step_hit(self, hit) -> None:
        # A new event id is the only end of event MUonE announces. B5 says so
        # outright and interleaves events across threads, which would make this
        # fire on nearly every step, so it stands down once a marker is seen.
        if (
            not self._event_marker_seen
            and self._current_event is not None
            and self._current_event != hit.event_id
        ):
            self._flush_event(self._current_event, complete=True)

        self._current_event = hit.event_id
        tracks = self._pending.setdefault(hit.event_id, {})
        tracks.setdefault((hit.track_id, hit.pdg), []).append([hit.x, hit.y, hit.z])
        self._steps_pending_draw = True

    # The event id cannot be the timeline position: Geant4 restarts it at 0 on
    # every /run/beamOn and the wire carries no run id, so ids repeat across runs.
    # This counts forward instead, and holds the position until the event is drawn
    # for the last time so an early draw is redrawn where it already was.
    def _event_slot(self, event_id: int) -> int:
        slot = self._event_slots.get(event_id)
        if slot is None:
            slot = self._event_slots[event_id] = self._events_seen
            self._events_seen += 1
        return slot

    # complete says whether the event can still gain steps: when it cannot the
    # buffer goes, when it might a later call redraws it at the same position.
    def _flush_event(self, event_id: int, *, complete: bool) -> None:
        buffered = self._pending.get(event_id, {})
        total_points = sum(len(track) for track in buffered.values())
        slot = self._event_slot(event_id)
        already_drawn = self._points_drawn.get(event_id)
        if complete:
            self._pending.pop(event_id, None)
            self._event_slots.pop(event_id, None)
            self._points_drawn.pop(event_id, None)
            if self._current_event == event_id:
                self._current_event = None
        else:
            self._points_drawn[event_id] = total_points

        if already_drawn == total_points:
            return

        tracks: list[DrawableTrack] = []
        for (track_id, pdg), track in buffered.items():
            name, color = _particle(pdg)
            tracks.append(
                DrawableTrack(
                    np.asarray(track, dtype=np.float32), color, name, track_id
                )
            )
        self._draw_tracks(event_id, slot, tracks)

    # Trajectories arrive whole, only once their stepping is over, so nothing
    # here needs buffering.
    def _log_event_trajectories(self, event) -> None:
        # Taken and given back at once: there will be no second, fuller draw.
        slot = self._event_slot(event.event_id)
        self._event_slots.pop(event.event_id, None)

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
        self._draw_tracks(event.event_id, slot, tracks)

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

        values: dict[str, object] = {"event_id": event_id}
        # Only a trajectory carries this, so the step path leaves it off rather
        # than filling it with zeros.
        if tracks and all(t.initial_e_kin is not None for t in tracks):
            values["initial_e_kin"] = [t.initial_e_kin for t in tracks]

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
            rr.AnyValues(**values),
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
        # EndOfEventAction runs after every step has been sent, however many
        # worker threads B5 was started with.
        self._event_marker_seen = True
        # B5's trajectories were already drawn and gave their slot back, so
        # flushing an empty buffer here would blank that picture on a new slot.
        if event.event_id in self._pending:
            self._flush_event(event.event_id, complete=True)

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

    # Runs on the idle flusher thread.
    def flush_quiet_tracks(self) -> None:
        with self._lock:
            if self.msg != self._msg_at_last_check:
                self._msg_at_last_check = self.msg
                return

            if not self._pending and not self._event_marker_seen:
                return

            if self._steps_pending_draw:
                # One quiet interval could still be a lull mid event, so draw what
                # is held without giving it up.
                self._steps_pending_draw = False
                for event_id in list(self._pending):
                    self._flush_event(event_id, complete=False)
                return

            # Two quiet intervals, so the run has ended. This service outlives any
            # one example, and a MUonE run started after a B5 one would otherwise
            # find the marker rule latched on and never complete an event.
            self._pending.clear()
            self._event_slots.clear()
            self._points_drawn.clear()
            self._event_marker_seen = False
            self._current_event = None

    def SendGeometry(self, request, context):
        with self._lock:
            logger.info(f"Received GDML over gRPC: {len(request.gdml)} bytes")
            try:
                solids = _parse_received_gdml(request.gdml)
            except Exception as exc:
                logger.error(f"Could not parse the GDML received over gRPC: {exc!r}")
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


def watch_and_flush_tracks(servicer: AgentServer) -> None:
    while True:
        time.sleep(TRACK_IDLE_FLUSH_S)
        servicer.flush_quiet_tracks()


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

    # max_workers=1: SendData does all its work holding the lock the flusher also
    # takes, so a second worker would only queue up behind it.
    servicer = AgentServer()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(servicer, server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    logger.info("Listening on port 50051, waiting for Geant4 data...")

    threading.Thread(
        target=watch_and_flush_tracks, args=(servicer,), daemon=True
    ).start()

    server.wait_for_termination()


if __name__ == "__main__":
    rr.init("rl4phy_muone")
    start_server()
