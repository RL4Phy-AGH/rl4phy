import argparse
import math
import sys

import grpc
from loguru import logger

import rl4phy_pb2
import rl4phy_pb2_grpc

MUON_MASS_MEV = 105.6583755
BEAM_ENERGY_MEV = 160_000.0
ENERGY_LOSS_MEV = 3.43
SCATTERING_ANGLE_RAD = 2.54e-5


def fake_crossings(events: int) -> list[rl4phy_pb2.StepHit]:
    p_in = math.sqrt(BEAM_ENERGY_MEV**2 - MUON_MASS_MEV**2)
    e_out = BEAM_ENERGY_MEV - ENERGY_LOSS_MEV
    p_out = math.sqrt(e_out**2 - MUON_MASS_MEV**2)
    entry = rl4phy_pb2.LorentzVector(e=BEAM_ENERGY_MEV, px=0.0, py=0.0, pz=p_in)
    exit_ = rl4phy_pb2.LorentzVector(
        e=e_out,
        px=p_out * math.sin(SCATTERING_ANGLE_RAD),
        py=0.0,
        pz=p_out * math.cos(SCATTERING_ANGLE_RAD),
    )
    return [
        rl4phy_pb2.StepHit(
            track_id=1,
            event_id=event_id,
            parent_id=0,
            pdg=13,
            volume="Station1",
            entry=entry,
            exit=exit_,
            path_length=10.0,
        )
        for event_id in range(events)
    ]


def main(events: int, address: str) -> None:
    event_scoring = rl4phy_pb2.Data(
        event_scoring=rl4phy_pb2.EventScoring(edep=0.042, event_id=7)
    )

    em_cal_edep = [0.0] * 80
    em_cal_edep[42:45] = [12.5, 48.0, 21.3]
    had_cal_edep = [0.0] * 20
    had_cal_edep[7:9] = [3.1, 7.9]
    b5_event = rl4phy_pb2.Data(
        b5_event=rl4phy_pb2.B5Event(
            event_id=7,
            drift_chamber_hits=[5, 4],
            hodoscope_time=[3.21, 11.75],
            em_cal_edep=em_cal_edep,
            had_cal_edep=had_cal_edep,
        )
    )

    event_trajectories = rl4phy_pb2.Data(
        event_trajectories=rl4phy_pb2.EventTrajectories(
            event_id=7,
            trajectories=[
                rl4phy_pb2.Trajectory(
                    track_id=1,
                    parent_id=0,
                    pdg=13,
                    charge=-1.0,
                    particle_name="mu-",
                    points=[0.0, 0.0, -100.0, 0.0, 0.0, 100.0],
                    initial_e_kin=BEAM_ENERGY_MEV - MUON_MASS_MEV,
                )
            ],
        )
    )

    crossings = [
        rl4phy_pb2.Data(
            event_step_hits=rl4phy_pb2.EventStepHits(event_id=hit.event_id, hits=[hit])
        )
        for hit in fake_crossings(events)
    ]

    stub = rl4phy_pb2_grpc.SendServiceStub(grpc.insecure_channel(address))
    stub.SendDataStream(iter([event_scoring, b5_event, event_trajectories, *crossings]))
    logger.info(
        f"Sent event_scoring, b5_event, event_trajectories "
        f"and {events} event_step_hits to {address}"
    )


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout)
    parser = argparse.ArgumentParser(description="Send fake data to a running server.")
    parser.add_argument(
        "events",
        nargs="?",
        type=int,
        default=10_000,
        help="number of fake crossing events to send",
    )
    parser.add_argument(
        "--address", default="localhost:50051", help="host:port of the server"
    )
    args = parser.parse_args()
    main(args.events, args.address)
