import colorsys
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

import rl4phy_pb2
import rl4phy_pb2_grpc
from gdml_geometry import PlacedCylinder, PlacedMesh, PlacedSolid, parse_gdml

RERUN_GRPC_PORT = 9876

GDML_EXPORT_PATH = os.environ.get("GDML_EXPORT_PATH", "/export/muone.gdml")
GDML_POLL_INTERVAL_S = 1.0

# Where the GDML received over gRPC (issue #18) is dumped before parsing.
GDML_GRPC_RECEIVED_PATH = os.environ.get(
    "GDML_GRPC_RECEIVED_PATH", "/tmp/muone_received.gdml"
)

# Volume and particle names are always logged, but drawing them on top of the
# geometry buries the detector as soon as a few detectors overlap on screen, so
# nothing is drawn by default. RL4PHY_MAX_LABELS is the number of instances an
# entity may have and still get its labels drawn: 0 turns them off, 8 restores
# the old behaviour, a large number labels everything. The names stay in the
# recording either way, so hovering a volume or a track in the viewer still
# identifies it.
MAX_LABELS_DRAWN = int(os.environ.get("RL4PHY_MAX_LABELS", "0"))

# How long the stream has to stay quiet before whatever is still buffered gets
# drawn anyway. MUonE marks no end of event, so without this its last event of a
# run would sit in the buffer forever. Inside a run the gap between two messages
# is milliseconds, so a second is long enough not to fire by accident, and firing
# early costs nothing anyway: the buffer survives it and the event is drawn again
# at the same point on the timeline once the rest of it turns up.
TRACK_IDLE_FLUSH_S = 1.0


def _try_load_gdml() -> list[PlacedSolid] | None:
    if not os.path.exists(GDML_EXPORT_PATH):
        return None
    try:
        solids = parse_gdml(GDML_EXPORT_PATH)
    except Exception as exc:  # Geant4 may still be mid-write; retry.
        print(f"GDML at {GDML_EXPORT_PATH} not ready yet ({exc!r}), retrying...")
        return None
    if not solids:
        print(f"GDML at {GDML_EXPORT_PATH} has no drawable volumes yet, retrying...")
        return None
    return solids


def watch_and_log_geometry() -> None:
    while True:
        solids = _try_load_gdml()
        if solids:
            print(f"Loaded {len(solids)} volume(s) from GDML: {GDML_EXPORT_PATH}")
            log_detector(solids)
            return
        time.sleep(GDML_POLL_INTERVAL_S)


def _path_color(path: str) -> list[int]:
    # Stable across runs, unlike hash(), so a subdetector keeps its colour.
    hue = (zlib.crc32(path.encode()) % 997) / 997.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.95)
    return [round(r * 255), round(g * 255), round(b * 255)]


def log_detector(solids: list[PlacedSolid]) -> None:
    rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Y_UP, static=True)

    # One entity per volume path rather than per placement: B5's hadronic
    # calorimeter alone is 800 boxes, and batching them keeps the Rerun tree
    # something a human can fold open.
    groups: dict[tuple[str, str], list[PlacedSolid]] = {}
    for solid in solids:
        groups.setdefault((solid.path, type(solid).__name__), []).append(solid)

    for (path, _), group in groups.items():
        color = _path_color(path)
        entity = f"world/{path}"

        if isinstance(group[0], PlacedMesh):
            # Every copy at one path is the same solid, so the mesh is logged
            # once and the copies become poses on top of it.
            template = group[0]
            # Meshes have no wireframe mode, so an envelope that is not a box or
            # a plain tube is made translucent instead of being drawn as a cage.
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
                static=True,
            )
            continue

        shared = {
            "centers": [s.center_mm for s in group],
            "quaternions": [s.quaternion_xyzw for s in group],
            "colors": color,
            "labels": [f"{s.name} #{s.copy_number}" for s in group],
            "show_labels": len(group) <= MAX_LABELS_DRAWN,
            # Envelopes are drawn as cages so they do not hide what they hold.
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
        rr.log(entity, archetype, static=True)


# PDG code to name and colour, for the species a B5 shower is made of. This
# table belongs to the step path and only to it: a step hit carries a PDG code
# and nothing else, so a colour per species is the most that can be made of it.
# A whole trajectory carries the charge as well, and is coloured by
# _charge_color below instead.
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
    # Nuclear fragments and the rarer mesons are not worth naming one by one, but
    # they still deserve a colour that stays the same all run, so it comes off
    # the code the same way _path_color comes off a volume path.
    hue = (zlib.crc32(str(pdg).encode()) % 997) / 997.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
    return f"pdg {pdg}", [round(r * 255), round(g * 255), round(b * 255)]


# Geant4's own drawByCharge palette, exactly as G4Colour names it: negative red,
# positive blue, neutral green. That is the modelling B5's vis.mac switches on,
# so it is what the OpenGL window this view exists to be checked against is
# painted with, and painting the same way is the entire point of the exercise:
# the same track comes out the same colour in both windows, and the two pictures
# can be laid side by side and compared by eye rather than translated first.
# Species colouring would carry more information, but it would carry it in the
# one channel the reference picture has already spent, and the information is not
# actually lost by giving it up: the particle's own name rides on every track as
# its label and is counted in the per-event line, and the two species anyone
# needs to tell apart in an electromagnetic shower, e- and e+, have opposite
# charges and so come out apart anyway.
def _charge_color(charge: float) -> list[int]:
    if charge > 0.0:
        return [0, 0, 255]
    if charge < 0.0:
        return [255, 0, 0]
    return [0, 255, 0]


# One track ready to be drawn. The two things that produce tracks know different
# amounts about them - a buffered step hit carries a PDG code and nothing else, a
# whole trajectory carries Geant4's own name, the charge and the energy the track
# started with - so each turns what it has into one of these, and _draw_tracks
# below is written once and never has to ask which of the two handed it over.
class DrawableTrack(NamedTuple):
    points: np.ndarray  # (N, 3), mm
    color: list[int]
    species: str
    track_id: int
    # Left as None by the step path, which does not keep the energy of a step.
    initial_e_kin: float | None = None


class AgentServer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self) -> None:
        self.msg = 0
        # Steps are collected here and only drawn once the event they belong to
        # is over, so a shower costs one Rerun row instead of one per step. The
        # event is the outer key because track ids restart with every event; the
        # pdg rides along in the inner key because it is fixed for the lifetime
        # of a track, which saves keeping a second dictionary beside this one.
        self._pending: dict[int, dict[tuple[int, int], list[list[float]]]] = {}
        self._current_event: int | None = None
        # Where each event in flight sits on the timeline, and the next free
        # place. See _event_slot for why the event id cannot be that place.
        self._event_slots: dict[int, int] = {}
        self._events_seen = 0
        # How many points an event was last drawn with, kept only for the events
        # the idle flusher drew early, so that confirming one later can tell a
        # picture that has grown from one that has not.
        self._points_drawn: dict[int, int] = {}
        # B5 marks the end of every event explicitly and MUonE does not, so which
        # of the two rules below applies is read off the stream, not configured.
        # It only describes the run in progress, and flush_quiet_tracks clears it
        # when that run ends, since the next one may be a different example.
        self._event_marker_seen = False
        self._steps_pending_draw = False
        self._msg_at_last_check = 0
        # The buffers are reached from the gRPC worker and from the idle flusher
        # thread, so everything that touches them goes through this.
        self._lock = threading.Lock()

    def SendData(self, request, context):
        with self._lock:
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
            elif kind == "b5_event":
                self._log_b5_event(request.b5_event)
            elif kind == "event_trajectories":
                self._log_event_trajectories(request.event_trajectories)
            else:
                print(f"[{self.msg}] unknown payload")

        return rl4phy_pb2.Reply()

    def _log_step_hit(self, hit) -> None:
        # A step hit carrying a new event id is the only end of event MUonE ever
        # announces, so it is what closes the one before it. B5 says so outright
        # and its worker threads interleave events as soon as --threads is raised
        # past one, which would make this rule fire on nearly every step, so it
        # stands down for good once the first marker has been seen.
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

    # Which place on the timeline an event gets. The event id cannot be that
    # place: Geant4 restarts it at 0 on every /run/beamOn and the wire carries no
    # run id, so B5/run1.mac's four runs of three hand out the ids 0,1,2 four
    # times over, and putting them on the timeline directly would leave only the
    # last run of each standing. This counts forward instead and never repeats.
    # The place is held until the event is drawn for the last time, so an event
    # the idle flusher drew early is redrawn where it already was rather than
    # somewhere new.
    def _event_slot(self, event_id: int) -> int:
        slot = self._event_slots.get(event_id)
        if slot is None:
            slot = self._event_slots[event_id] = self._events_seen
            self._events_seen += 1
        return slot

    # Turns what has been buffered for one event into tracks and hands them to
    # be drawn. complete says whether the event can still gain steps: when it
    # cannot the buffer goes, when it might the buffer stays and a later call
    # redraws the event at the same point on the timeline, where the fuller
    # picture simply replaces this one.
    def _flush_event(self, event_id: int, *, complete: bool) -> None:
        buffered = self._pending.get(event_id, {})
        total_points = sum(len(track) for track in buffered.values())
        slot = self._event_slot(event_id)
        # Read rather than taken: an event that is still buffered has to keep its
        # entry, or the next quiet tick would find none, draw the same picture
        # again, put the entry back, and alternate that way for as long as the
        # buffer is held.
        already_drawn = self._points_drawn.get(event_id)
        if complete:
            self._pending.pop(event_id, None)
            self._event_slots.pop(event_id, None)
            self._points_drawn.pop(event_id, None)
            if self._current_event == event_id:
                self._current_event = None
        else:
            self._points_drawn[event_id] = total_points

        # An event the idle flusher already drew is only drawn again once it has
        # grown, so confirming a quiet event costs nothing and the same picture
        # does not take up two places on the slider.
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

    # One event's worth of tracks, arriving whole. Nothing about a trajectory
    # needs buffering: it is only ever sent once its stepping is over, so there
    # is no marker to wait for and no partial picture to improve on later.
    def _log_event_trajectories(self, event) -> None:
        # The place on the timeline is taken and given back in the same breath,
        # because unlike a buffered event there will never be a second, fuller
        # draw to hold it for. It still comes off the step path's counter: what
        # makes a place unique is that the counter never goes back, and the event
        # id does, since /run/beamOn restarts it at 0.
        slot = self._event_slot(event.event_id)
        self._event_slots.pop(event.event_id, None)

        tracks = [
            DrawableTrack(
                # The wire flattens each polyline into x,y,z triples, so its
                # length is always a multiple of 3 and this only folds it back.
                points=np.asarray(t.points, dtype=np.float32).reshape(-1, 3),
                color=_charge_color(t.charge),
                # Geant4's own name, so nothing has to be recovered from the PDG
                # code and a rare species reads as itself rather than as a number.
                species=t.particle_name,
                track_id=t.track_id,
                initial_e_kin=t.initial_e_kin,
            )
            for t in event.trajectories
        ]
        self._draw_tracks(event.event_id, slot, tracks)

    # The one place tracks reach Rerun from. Both sources hand their event over
    # here rather than logging it themselves, so however an event was assembled
    # it lands on the same timeline, in the same two entities, under the same
    # rule about labels, and is announced by the same line.
    def _draw_tracks(
        self, event_id: int, slot: int, tracks: list[DrawableTrack]
    ) -> None:
        # Shaped rather than built as lists because a shower event is hundreds of
        # tracks and hundreds of thousands of points, and repeating a colour per
        # point in Python is the one part of this that would be felt.
        colors = np.array([t.color for t in tracks], dtype=np.uint8).reshape(-1, 3)
        points = (
            np.concatenate([t.points for t in tracks])
            if tracks
            else np.zeros((0, 3), dtype=np.float32)
        )
        point_colors = np.repeat(colors, [len(t.points) for t in tracks], axis=0)

        # Named event_index rather than event so that nobody reads a slider
        # position as a Geant4 event number: the two only agree for the first run.
        # The real id is logged beside the tracks below, where the viewer shows it
        # for whatever the slider is sitting on.
        rr.set_time("event_index", sequence=slot)

        # The number Geant4 printed for this event, which is what a person has in
        # the other window and wants to match against. It rides with the strips
        # instead of on a timeline of its own precisely because it repeats between
        # runs.
        values: dict[str, object] = {"event_id": event_id}
        # The energy a track started with only comes with a trajectory, so rather
        # than filling the step path's in with zeros it is left off there. It is
        # logged and never drawn: clicking a track then says whether it is the
        # primary or one of the hundreds of soft secondaries around it, which is
        # a number worth having and not worth putting on screen per track.
        if tracks and all(t.initial_e_kin is not None for t in tracks):
            values["initial_e_kin"] = [t.initial_e_kin for t in tracks]

        # One row for all of the event's tracks rather than an entity per track:
        # a shower is hundreds of them, and a subtree each would bury everything
        # else in the viewer. Both archetypes are logged even when the event is
        # empty, since that is what clears the previous event off the screen.
        # The polylines and the points they are built from stay apart so the
        # points can be switched off once they turn into fog.
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
        print(
            f"[{self.msg}] tracks: event={event_id} (index {slot})  "
            f"{len(tracks)} track(s), {len(points)} point(s)  "
            f"[{tally}]"
        )

    def _log_b5_event(self, event) -> None:
        # EndOfEventAction runs after every step of the event has been sent, so
        # this is the exact moment the event's tracks are complete, and it stays
        # exact however many worker threads B5 was started with.
        self._event_marker_seen = True
        # Only when there is in fact something buffered to complete. B5 sends this
        # summary alongside its trajectories, which were drawn as they arrived and
        # have already given their place on the timeline back, so flushing an
        # empty buffer here would claim a second place and blank the picture they
        # had just drawn on the first.
        if event.event_id in self._pending:
            self._flush_event(event.event_id, complete=True)

        # The calorimeter cells arrive one value per cell and most of them are
        # empty, so print the totals the way B5's own EndOfEventAction does.
        chamber_hits = ", ".join(str(n) for n in event.drift_chamber_hits)
        # An arm the particle missed reports -1 instead of a hit time.
        hodoscope_times = ", ".join(
            "none" if t < 0.0 else f"{t:.2f}" for t in event.hodoscope_time
        )
        print(
            f"[{self.msg}] B5 b5_event: event={event.event_id}  "
            f"chamber hits = [{chamber_hits}]  "
            f"hodoscope t = [{hodoscope_times}] ns  "
            f"EM edep = {sum(event.em_cal_edep):.6f} MeV "
            f"in {len(event.em_cal_edep)} cells  "
            f"Had edep = {sum(event.had_cal_edep):.6f} MeV "
            f"in {len(event.had_cal_edep)} cells"
        )

    # Runs on the idle flusher thread. The last event of a MUonE run is followed
    # by no marker and by no further step hit, so the one thing left that can say
    # it is over is the stream falling quiet.
    def flush_quiet_tracks(self) -> None:
        with self._lock:
            if self.msg != self._msg_at_last_check:
                # Still arriving, so whatever is buffered is not finished yet.
                self._msg_at_last_check = self.msg
                return

            if not self._pending and not self._event_marker_seen:
                # Nothing held and no marker rule latched on, which is exactly
                # what a stream made only of trajectories leaves behind: they
                # arrive whole and are drawn where they land, so none of the
                # machinery below ever has anything of theirs to finish.
                return

            if self._steps_pending_draw:
                # One quiet interval on its own could still be a lull in the
                # middle of an event, so this draws what is held without giving
                # it up, and a later flush redraws the event where it already is.
                self._steps_pending_draw = False
                for event_id in list(self._pending):
                    self._flush_event(event_id, complete=False)
                return

            # Two quiet intervals in a row, so the run really has ended. All of
            # this is per run, and the compose python service outlives any one
            # example: a MUonE run started after a B5 one would otherwise find
            # the marker rule latched on, never complete an event, and hold every
            # buffer and every slot it ever took until the process died. Nothing
            # is lost by dropping the buffers, since the pass above has already
            # drawn them; only _events_seen carries over, so slots stay unique.
            self._pending.clear()
            self._event_slots.clear()
            self._points_drawn.clear()
            self._event_marker_seen = False
            self._current_event = None

    def SendGeometry(self, request, context):
        # Geometry hand-off (issue #18): Geant4 ships the exported GDML over
        # gRPC, so the shared volume is no longer required to see the stations.
        print(f"Received GDML over gRPC: {len(request.gdml)} bytes")
        try:
            with open(GDML_GRPC_RECEIVED_PATH, "wb") as gdml_file:
                gdml_file.write(request.gdml)
            solids = parse_gdml(GDML_GRPC_RECEIVED_PATH)
        except Exception as exc:
            print(f"Could not parse the GDML received over gRPC: {exc!r}")
            return rl4phy_pb2.Reply()

        if solids:
            print(f"Loaded {len(solids)} volume(s) from gRPC GDML")
            log_detector(solids)
        else:
            print("GDML received over gRPC has no drawable volumes")
        return rl4phy_pb2.Reply()


def watch_and_flush_tracks(servicer: AgentServer) -> None:
    while True:
        time.sleep(TRACK_IDLE_FLUSH_S)
        servicer.flush_quiet_tracks()


def start_server():
    server_uri = rr.serve_grpc(grpc_port=RERUN_GRPC_PORT)
    print(f"Rerun gRPC server on port {RERUN_GRPC_PORT} ({server_uri})")
    print(
        "Connect the viewer with: "
        f"rerun --connect rerun+http://127.0.0.1:{RERUN_GRPC_PORT}/proxy"
    )

    # GrpcClient::SendStepHit (C++) doesn't retry, so this port must be open
    # before the GDML wait below, not after.
    # max_workers=1 is still what the handlers are written for: SendData does all
    # of its work holding AgentServer's lock, which the track flusher below also
    # takes, so a second worker would only ever queue up behind it. The lock is
    # there for that flusher, not to make the handlers concurrent.
    servicer = AgentServer()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(servicer, server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    print("Listening on port 50051, waiting for Geant4 data...")

    threading.Thread(target=watch_and_log_geometry, daemon=True).start()
    threading.Thread(
        target=watch_and_flush_tracks, args=(servicer,), daemon=True
    ).start()

    server.wait_for_termination()


if __name__ == "__main__":
    rr.init("rl4phy_muone")
    start_server()
