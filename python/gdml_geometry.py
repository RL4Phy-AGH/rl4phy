"""Station geometry read natively with pyg4ometry (architecture decision from
the 2026-05-28 meeting: Python consumes the exported GDML via pyg4ometry).

pyg4ometry evaluates GDML expressions and units for us: box parameters come
back as full lengths in mm, positions in mm, rotations in radians composing as
R = Rz(z) @ Ry(y) @ Rx(x), matching Geant4's G4GDMLReadDefine::GetRotationMatrix."""

from __future__ import annotations

from dataclasses import dataclass

import pyg4ometry.gdml as gdml
from squaternion import Quaternion

Vec3 = tuple[float, float, float]
QuaternionXYZW = tuple[float, float, float, float]


@dataclass(frozen=True)
class StationGeometry:
    name: str
    half_size_mm: Vec3
    center_mm: Vec3
    quaternion_xyzw: QuaternionXYZW


def _euler_to_quaternion_xyzw(rx: float, ry: float, rz: float) -> QuaternionXYZW:
    q = Quaternion.from_euler(rx, ry, rz)
    return (q.x, q.y, q.z, q.w)


def parse_gdml(path: str) -> list[StationGeometry]:
    # reduceNISTMaterialsToPredefined: the GDML written by Geant4 carries
    # temperature/density entries for NIST materials (G4_AIR, G4_Si, ...),
    # which the reader refuses to re-apply to predefined materials otherwise.
    registry = gdml.Reader(path, reduceNISTMaterialsToPredefined=True).getRegistry()
    world = registry.getWorldVolume()

    stations: list[StationGeometry] = []
    for physvol in world.daughterVolumes:
        solid = physvol.logicalVolume.solid
        # Box-shaped direct daughters of the world are our tracking stations.
        # Other solids (cones, trapezoids from the G4 examples) will need mesh
        # rendering; see issue #18.
        if type(solid).__name__ != "Box":
            continue

        full_mm = (
            float(solid.pX.eval()),
            float(solid.pY.eval()),
            float(solid.pZ.eval()),
        )
        center_mm = tuple(float(v) for v in physvol.position.eval())
        rotation_rad = tuple(float(v) for v in physvol.rotation.eval())

        stations.append(
            StationGeometry(
                name=physvol.name,
                half_size_mm=(full_mm[0] / 2.0, full_mm[1] / 2.0, full_mm[2] / 2.0),
                center_mm=center_mm,
                quaternion_xyzw=_euler_to_quaternion_xyzw(*rotation_rad),
            )
        )

    return stations
