import os
import signal
import sys
import threading
from concurrent import futures

import grpc
from loguru import logger

import rl4phy_pb2
import rl4phy_pb2_grpc
from dataset_writer import ParquetStepWriter, maybe_create_step_writer
from gdml_geometry import parse_gdml_bytes
from rerun_view import DEFAULT_VIEWER_URL, RerunView

PAYLOAD_KINDS = {
    f.name for f in rl4phy_pb2.Data.DESCRIPTOR.oneofs_by_name["payload"].fields
}

# Each Geant4 thread keeps one stream open for the whole job, and the next
# run's geometry call still needs a free worker. Idle workers cost nothing,
# so the number is high.
MAX_GEANT4_THREADS = 63


class SendServicer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(self, writer: ParquetStepWriter | None, view: RerunView) -> None:
        self.msg = 0
        self._writer = writer
        self._view = view
        self._open_streams = 0
        # Held per message, not per stream, or SendGeometry would wait for the
        # whole job.
        self._lock = threading.Lock()
        self._handlers = {
            "event_scoring": self._log_b1_event,
            "step_hit": self._record_step_hit,
            "event_step_hits": self._record_event_step_hits,
            "b5_event": self._log_b5_event,
            "event_trajectories": self._draw_trajectories,
        }
        missing = PAYLOAD_KINDS - set(self._handlers)
        if missing:
            logger.warning(f"No handler for payload(s): {sorted(missing)}")

    def SendDataStream(self, request_iterator, context):
        with self._lock:
            self._open_streams += 1
        try:
            for request in request_iterator:
                with self._lock:
                    self._handle_data(request)
        finally:
            with self._lock:
                self._open_streams -= 1
                # A job's streams end together, so its file closes with the last one.
                if self._open_streams == 0 and self._writer is not None:
                    self._writer.close()
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

        with self._lock:
            self._view.draw_geometry(solids)
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

    def _record_step_hit(self, hit) -> None:
        logger.info(f"[{self.msg}] crossing: event={hit.event_id} track={hit.track_id}")
        self._record_crossing(hit)

    def _record_event_step_hits(self, event) -> None:
        logger.info(
            f"[{self.msg}] crossings: event={event.event_id}  "
            f"{len(event.hits)} crossing(s)"
        )
        for hit in event.hits:
            self._record_crossing(hit)

    def _record_crossing(self, hit) -> None:
        if not hit.HasField("exit") or hit.exit.e == 0.0:
            # An exit energy of 0 would be read as the whole beam energy lost.
            logger.warning(
                f"[{self.msg}] crossing without a usable exit: "
                f"event={hit.event_id} track={hit.track_id}"
            )
            return
        if self._writer is None:
            return
        try:
            self._writer.append_step_hit(hit)
        except Exception:
            logger.exception("Dataset: recording disabled after a write error")
            self._writer = None

    def _draw_trajectories(self, event) -> None:
        logger.info(f"[{self.msg}] event_trajectories: event={event.event_id}")
        self._view.draw_trajectories(event)

    def _log_b5_event(self, event) -> None:
        chamber_hits = ", ".join(str(n) for n in event.drift_chamber_hits)
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
    executor = futures.ThreadPoolExecutor(max_workers=MAX_GEANT4_THREADS + 1)
    server = grpc.server(executor)
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(
        SendServicer(writer, view), server
    )
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: server.stop(grace=5))
    try:
        server.add_insecure_port(f"0.0.0.0:{port}")
        server.start()
        logger.info(f"Listening on port {port}, waiting for Geant4 data...")
        server.wait_for_termination()
    finally:
        # A handler can still be mid-message when the grace period cuts the
        # stream; let it finish before the writer and the view go away.
        executor.shutdown(wait=True)
        try:
            if writer is not None:
                writer.close()
        except Exception:
            logger.exception("Dataset: the last file could not be closed")
        finally:
            view.close()


def main() -> None:
    logger.remove()
    logger.add(sys.stdout)
    view = RerunView(
        url=os.environ.get("RL4PHY_RERUN_URL", DEFAULT_VIEWER_URL),
        max_labels=int(os.environ.get("RL4PHY_MAX_LABELS", "0")),
    )
    writer = maybe_create_step_writer(os.environ.get("RL4PHY_DATASET_DIR"))
    serve(writer, view)


if __name__ == "__main__":
    main()
