import math
import random
import sys

import grpc
from loguru import logger

import rl4phy_pb2
import rl4phy_pb2_grpc

MASS_MU = 105.6583755

# Most probable energy loss and Landau width (MeV) and the Highland angle (rad)
# of a 160 GeV muon in the 10 mm silicon station of the MUonE test geometry,
# and the same for the 300 um plane of the one-plane case.
STATION_10MM = {
    "volume": "Station1",
    "thickness_mm": 10.0,
    "mpv": 3.43,
    "xi": 0.178,
    "theta0": 2.54e-5,
}
PLANE_300UM = {
    "volume": "Plane",
    "thickness_mm": 0.3,
    "mpv": 0.0842,
    "xi": 0.00535,
    "theta0": 3.76e-6,
}


def fake_crossings(
    events: int,
    seed: int,
    *,
    e_in: float = 160_000.0,
    layer: dict = STATION_10MM,
) -> list[rl4phy_pb2.StepHit]:
    rng = random.Random(seed)
    p_in = math.sqrt(e_in**2 - MASS_MU**2)
    hits = []
    for event_id in range(events):
        # -ln(Z^2) of a standard normal Z is Moyal distributed: a Landau look-alike
        # with its most probable value at 0.
        loss = layer["mpv"] + layer["xi"] * -math.log(rng.gauss(0.0, 1.0) ** 2)
        e_out = e_in - loss
        p_out = math.sqrt(e_out**2 - MASS_MU**2)
        tx, ty = (
            math.tan(rng.gauss(0.0, layer["theta0"])),
            math.tan(rng.gauss(0.0, layer["theta0"])),
        )
        norm = math.sqrt(tx**2 + ty**2 + 1.0)
        hits.append(
            rl4phy_pb2.StepHit(
                track_id=1,
                event_id=event_id,
                parent_id=0,
                pdg=13,
                volume=layer["volume"],
                entry=rl4phy_pb2.LorentzVector(e=e_in, px=0.0, py=0.0, pz=p_in),
                exit=rl4phy_pb2.LorentzVector(
                    e=e_out, px=p_out * tx / norm, py=p_out * ty / norm, pz=p_out / norm
                ),
                path_length=layer["thickness_mm"] * norm,
            )
        )
    return hits


def main(host: str = "localhost:50051", events: int = 10_000, seed: int = 0) -> None:
    b1 = rl4phy_pb2.Data(event_scoring=rl4phy_pb2.EventScoring(edep=0.042, event_id=7))

    # Every calorimeter cell is sent, empty ones included: 80 EM, 20 hadronic.
    em_cal_edep = [0.0] * 80
    em_cal_edep[42:45] = [12.5, 48.0, 21.3]
    had_cal_edep = [0.0] * 20
    had_cal_edep[7:9] = [3.1, 7.9]
    b5 = rl4phy_pb2.Data(
        b5_event=rl4phy_pb2.B5Event(
            event_id=7,
            drift_chamber_hits=[5, 4],
            hodoscope_time=[3.21, 11.75],
            em_cal_edep=em_cal_edep,
            had_cal_edep=had_cal_edep,
        )
    )

    trajectories = rl4phy_pb2.Data(
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
                    initial_e_kin=160_000.0 - MASS_MU,
                )
            ],
        )
    )

    crossings = [
        rl4phy_pb2.Data(
            event_step_hits=rl4phy_pb2.EventStepHits(event_id=hit.event_id, hits=[hit])
        )
        for hit in fake_crossings(events, seed)
    ]

    stub = rl4phy_pb2_grpc.SendServiceStub(grpc.insecure_channel(host))
    stub.SendDataStream(iter([b1, b5, trajectories, *crossings]))
    logger.info(f"Sent B1 + B5 + one trajectory event + {events} crossing event(s)")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout)
    main()
