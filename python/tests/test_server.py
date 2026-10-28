from loguru import logger

import rl4phy_pb2
from server import PAYLOADS, AgentServer


class RecordingWriter:
    def __init__(self, fail: bool = False) -> None:
        self.hits = []
        self.fail = fail

    def append_step_hit(self, hit) -> None:
        if self.fail:
            raise OSError("disk full")
        self.hits.append(hit)


def test_every_payload_has_a_handler():
    servicer = AgentServer(writer=None)
    assert PAYLOADS <= set(servicer._handlers)


def test_crossings_go_to_the_writer(crossings):
    writer = RecordingWriter()
    servicer = AgentServer(writer)
    servicer._handle_data(rl4phy_pb2.Data(step_hit=crossings[0]))
    servicer._handle_data(
        rl4phy_pb2.Data(
            event_step_hits=rl4phy_pb2.EventStepHits(event_id=1, hits=crossings[1:4])
        )
    )
    assert writer.hits == crossings[:4]


def test_crossing_without_exit_is_skipped(crossings):
    writer = RecordingWriter()
    servicer = AgentServer(writer)
    half = rl4phy_pb2.StepHit(track_id=1, event_id=2, entry=crossings[0].entry)
    servicer._handle_data(rl4phy_pb2.Data(step_hit=half))
    assert writer.hits == []


def test_unknown_payload_is_logged_not_raised():
    messages = []
    sink = logger.add(messages.append, level="WARNING")
    try:
        AgentServer(writer=None)._handle_data(rl4phy_pb2.Data())
    finally:
        logger.remove(sink)
    assert any("unknown payload" in message for message in messages)


def test_write_error_disables_recording(crossings):
    writer = RecordingWriter(fail=True)
    servicer = AgentServer(writer)
    servicer._handle_data(rl4phy_pb2.Data(step_hit=crossings[0]))
    assert servicer._writer is None
    writer.fail = False
    servicer._handle_data(rl4phy_pb2.Data(step_hit=crossings[1]))
    assert writer.hits == []
