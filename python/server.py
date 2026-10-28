import os
import signal
import sys
from concurrent import futures

import grpc
from loguru import logger

import rl4phy_pb2
import rl4phy_pb2_grpc
from dataset_writer import ParquetStepWriter, maybe_create_step_writer
from gdml_geometry import parse_gdml_bytes
from rerun_view import RerunView

# Every branch of the oneof, read off the proto so the handler table below and
# its test cannot drift from it.
PAYLOADS = {f.name for f in rl4phy_pb2.Data.DESCRIPTOR.oneofs_by_name["payload"].fields}


class SendServicer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self, writer: ParquetStepWriter | None, view: RerunView) -> None:
        self.msg = 0
        self._writer = writer
        self._view = view
        self._handlers = {
            "event_scoring": self._log_b1_event,
            "step_hit": self._record_step_hit,
            "event_step_hits": self._record_event_step_hits,
            "b5_event": self._log_b5_event,
            "event_trajectories": self._draw_trajectories,
        }
        missing = PAYLOADS - set(self._handlers)
        if missing:
            logger.warning(f"No handler for payload(s): {sorted(missing)}")

    def SendDataStream(self, request_iterator, context):
        for request in request_iterator:
            self._handle_data(request)
        return rl4phy_pb2.Reply()

    def SendGeometry(self, request, context):
        logger.info(f"Received GDML over gRPC: {len(request.gdml)} bytes")
        try:
            solids = parse_gdml_bytes(request.gdml)
        except Exception:
            logger.exception("Could not parse the GDML received over gRPC")
            return rl4phy_pb2.Reply()

        if not solids:
            logger.warning("GDML received over gRPC has no drawable volumes")
            return rl4phy_pb2.Reply()

        self._view.geometry(solids)
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

    def _draw_trajectories(self, event) -> None:
        self._view.trajectories(event, self.msg)

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


def serve(writer: ParquetStepWriter | None, view: RerunView, port: int = 50051) -> None:
    # One worker: the handlers share the writer and the view without a lock,
    # and geometry has to be drawn before the stream that follows it.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(
        SendServicer(writer, view), server
    )
    server.add_insecure_port(f"0.0.0.0:{port}")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: server.stop(grace=5))
    try:
        server.start()
        logger.info(f"Listening on port {port}, waiting for Geant4 data...")
        server.wait_for_termination()
    finally:
        if writer is not None:
            writer.close()
        view.close()


def main() -> None:
    logger.remove()
    logger.add(sys.stdout)
    writer = maybe_create_step_writer(os.environ.get("RL4PHY_DATASET_DIR"))
    view = RerunView(max_labels=int(os.environ.get("RL4PHY_MAX_LABELS", "0")))
    serve(writer, view)


if __name__ == "__main__":
    main()
