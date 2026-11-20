import pytest
from loguru import logger

import rl4phy_pb2
from server import SendServicer


class FakeCrossingsFile:
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


class FakeView:
    def __init__(self) -> None:
        self.events = []

    def draw_trajectories(self, event) -> None:
        self.events.append(event.event_id)


@pytest.fixture
def warnings():
    messages = []
    sink = logger.add(messages.append, level="WARNING")
    yield messages
    logger.remove(sink)


def send(servicer: SendServicer, *messages: rl4phy_pb2.Data) -> None:
    servicer.SendDataStream(iter(messages), None)


def test_every_payload_is_handled(warnings):
    servicer = SendServicer(None, FakeView())
    for field in rl4phy_pb2.Data.DESCRIPTOR.oneofs_by_name["payload"].fields:
        payload = getattr(rl4phy_pb2, field.message_type.name)()
        send(servicer, rl4phy_pb2.Data(**{field.name: payload}))
    assert warnings == []


def test_unknown_payload_is_logged_not_raised(warnings):
    send(SendServicer(None, FakeView()), rl4phy_pb2.Data())
    assert len(warnings) == 1


def test_crossings_go_to_the_file(crossings):
    crossings_file = FakeCrossingsFile()
    send(
        SendServicer(crossings_file, FakeView()),
        rl4phy_pb2.Data(step_hit=crossings[0]),
        rl4phy_pb2.Data(
            event_step_hits=rl4phy_pb2.EventStepHits(event_id=1, hits=crossings[1:4])
        ),
    )
    assert crossings_file.hits == crossings[:4]
    assert crossings_file.closed == 1


def test_recording_ends_with_the_last_stream(crossings):
    crossings_file = FakeCrossingsFile()
    servicer = SendServicer(crossings_file, FakeView())

    def outer_stream():
        yield rl4phy_pb2.Data(step_hit=crossings[0])
        send(servicer, rl4phy_pb2.Data(step_hit=crossings[1]))
        assert crossings_file.closed == 0
        yield rl4phy_pb2.Data(step_hit=crossings[2])

    servicer.SendDataStream(outer_stream(), None)
    assert crossings_file.hits == crossings[:3]
    assert crossings_file.closed == 1


def test_trajectories_go_to_the_view():
    view = FakeView()
    send(
        SendServicer(None, view),
        rl4phy_pb2.Data(event_trajectories=rl4phy_pb2.EventTrajectories(event_id=9)),
    )
    assert view.events == [9]


def test_write_error_disables_recording(crossings):
    crossings_file = FakeCrossingsFile(fail=True)
    servicer = SendServicer(crossings_file, FakeView())
    send(servicer, rl4phy_pb2.Data(step_hit=crossings[0]))
    crossings_file.fail = False
    send(servicer, rl4phy_pb2.Data(step_hit=crossings[1]))
    assert crossings_file.hits == []
