from loguru import logger

import rl4phy_pb2
from server import PAYLOAD_KINDS, SendServicer


class RecordingWriter:
    def __init__(self, fail: bool = False) -> None:
        self.hits = []
        self.fail = fail
        self.closed = 0

    def append_step_hit(self, hit) -> None:
        if self.fail:
            raise OSError("disk full")
        self.hits.append(hit)

    def close(self) -> None:
        self.closed += 1


class RecordingView:
    def __init__(self) -> None:
        self.events = []

    def draw_geometry(self, solids) -> None:
        pass

    def draw_trajectories(self, event) -> None:
        self.events.append(event.event_id)

    def close(self) -> None:
        pass


def send(servicer: SendServicer, *messages: rl4phy_pb2.Data) -> None:
    servicer.SendDataStream(iter(messages), None)


def test_every_payload_has_a_handler():
    servicer = SendServicer(writer=None, view=RecordingView())
    assert PAYLOAD_KINDS <= set(servicer._handlers)


def test_crossings_go_to_the_writer(crossings):
    writer = RecordingWriter()
    servicer = SendServicer(writer, RecordingView())
    send(
        servicer,
        rl4phy_pb2.Data(step_hit=crossings[0]),
        rl4phy_pb2.Data(
            event_step_hits=rl4phy_pb2.EventStepHits(event_id=1, hits=crossings[1:4])
        ),
    )
    assert writer.hits == crossings[:4]
    assert writer.closed == 1


def test_trajectories_go_to_the_view():
    view = RecordingView()
    servicer = SendServicer(writer=None, view=view)
    send(
        servicer,
        rl4phy_pb2.Data(event_scoring=rl4phy_pb2.EventScoring()),
        rl4phy_pb2.Data(event_trajectories=rl4phy_pb2.EventTrajectories(event_id=9)),
    )
    assert view.events == [9]


def test_crossing_without_exit_is_skipped(crossings):
    writer = RecordingWriter()
    servicer = SendServicer(writer, RecordingView())
    half = rl4phy_pb2.StepHit(track_id=1, event_id=2, entry=crossings[0].entry)
    zeroed = rl4phy_pb2.StepHit(track_id=1, event_id=3, exit=rl4phy_pb2.LorentzVector())
    send(servicer, rl4phy_pb2.Data(step_hit=half), rl4phy_pb2.Data(step_hit=zeroed))
    assert writer.hits == []


def test_unknown_payload_is_logged_not_raised():
    messages = []
    sink = logger.add(messages.append, level="WARNING")
    try:
        send(SendServicer(writer=None, view=RecordingView()), rl4phy_pb2.Data())
    finally:
        logger.remove(sink)
    assert any("unknown payload" in message for message in messages)


def test_write_error_disables_recording(crossings):
    writer = RecordingWriter(fail=True)
    servicer = SendServicer(writer, RecordingView())
    send(servicer, rl4phy_pb2.Data(step_hit=crossings[0]))
    writer.fail = False
    send(servicer, rl4phy_pb2.Data(step_hit=crossings[1]))
    assert writer.hits == []
