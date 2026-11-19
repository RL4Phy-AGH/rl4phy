import os
import signal
import sys
import threading
from concurrent import futures

import grpc
from loguru import logger

import rl4phy_pb2
import rl4phy_pb2_grpc
from dataset_writer import ParquetStepWriter
from gdml_geometry import parse_gdml_bytes
from rerun_view import RerunView

HOST = "0.0.0.0"
PORT = 50051
DEFAULT_RERUN_URL = "rerun+http://127.0.0.1:9876/proxy"


class SendServicer(rl4phy_pb2_grpc.SendServiceServicer):
    def __init__(
        self, crossings_file: ParquetStepWriter | None, view: RerunView
    ) -> None:
        self.msg = 0
        self._crossings_file = crossings_file
        self._view = view
        self._open_streams = 0
        self._lock = threading.Lock()

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
                if self._open_streams == 0 and self._crossings_file is not None:
                    self._crossings_file.close()
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
        match kind:
            case "event_scoring":
                self._log_event_scoring(request.event_scoring)
            case "step_hit":
                self._record_crossing(request.step_hit)
            case "event_step_hits":
                for hit in request.event_step_hits.hits:
                    self._record_crossing(hit)
            case "b5_event":
                self._log_b5_event(request.b5_event)
            case "event_trajectories":
                self._view.draw_trajectories(request.event_trajectories)
            case _:
                logger.warning(f"[{self.msg}] unknown payload {kind!r}")

    def _log_event_scoring(self, event) -> None:
        logger.info(
            f"[{self.msg}] event_scoring: event={event.event_id} "
            f"edep = {event.edep:.6f} MeV"
        )

    def _record_crossing(self, hit) -> None:
        if self._crossings_file is None:
            return
        try:
            self._crossings_file.append_step_hit(hit)
        except Exception:
            logger.exception("Dataset: recording disabled after a write error")
            self._crossings_file = None

    def _log_b5_event(self, event) -> None:
        chamber_hits = ", ".join(str(n) for n in event.drift_chamber_hits)
        hodoscope_times = ", ".join(
            "none" if t < 0.0 else f"{t:.2f}" for t in event.hodoscope_time
        )
        logger.info(
            f"[{self.msg}] b5_event: event={event.event_id}  "
            f"chamber hits = [{chamber_hits}]  "
            f"hodoscope t = [{hodoscope_times}] ns  "
            f"EM edep = {sum(event.em_cal_edep):.6f} MeV "
            f"in {len(event.em_cal_edep)} cells  "
            f"Had edep = {sum(event.had_cal_edep):.6f} MeV "
            f"in {len(event.had_cal_edep)} cells"
        )


def serve(crossings_file: ParquetStepWriter | None, view: RerunView) -> None:
    executor = futures.ThreadPoolExecutor(max_workers=64)
    server = grpc.server(executor)
    rl4phy_pb2_grpc.add_SendServiceServicer_to_server(
        SendServicer(crossings_file, view), server
    )
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: server.stop(grace=5))
    try:
        server.add_insecure_port(f"{HOST}:{PORT}")
        server.start()
        logger.info(f"Listening on {HOST}:{PORT}, waiting for Geant4 data...")
        server.wait_for_termination()
    finally:
        executor.shutdown(wait=True)
        view.close()


def main() -> None:
    logger.remove()
    logger.add(sys.stdout)
    directory = os.environ.get("RL4PHY_DATASET_DIR")
    crossings_file = ParquetStepWriter(directory) if directory else None
    view = RerunView(
        url=os.environ.get("RL4PHY_RERUN_URL", DEFAULT_RERUN_URL),
        max_labels=int(os.environ.get("RL4PHY_MAX_LABELS", "0")),
    )
    serve(crossings_file, view)


if __name__ == "__main__":
    main()
