import math
import random

import pytest

import rl4phy_pb2

MASS_MU = 105.6583755


@pytest.fixture
def crossings() -> list[rl4phy_pb2.StepHit]:
    rng = random.Random(1)
    hits = []
    for event_id in range(20):
        e_in = 160_000.0
        e_out = e_in - rng.uniform(2.0, 6.0)
        p_in = math.sqrt(e_in**2 - MASS_MU**2)
        p_out = math.sqrt(e_out**2 - MASS_MU**2)
        px, py = rng.gauss(0.0, 4.0), rng.gauss(0.0, 4.0)
        hits.append(
            rl4phy_pb2.StepHit(
                track_id=1,
                event_id=event_id,
                parent_id=0,
                pdg=13,
                volume="Station1",
                entry=rl4phy_pb2.LorentzVector(e=e_in, px=0.0, py=0.0, pz=p_in),
                exit=rl4phy_pb2.LorentzVector(
                    e=e_out, px=px, py=py, pz=math.sqrt(p_out**2 - px**2 - py**2)
                ),
                path_length=10.0 + rng.uniform(0.0, 0.01),
            )
        )
    return hits
