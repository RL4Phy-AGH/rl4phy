"""Rotation convention: GDML's <rotation x= y= z= unit="deg"/> angles compose
as R = Rz(z) @ Ry(y) @ Rx(x), matching Geant4's G4GDMLReadDefine::GetRotationMatrix
(CLHEP HepRotation::rotateX/Y/Z applied in that order from identity)."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from squaternion import Quaternion

_LENGTH_UNITS_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
_ANGLE_UNITS_RAD = {"deg": math.pi / 180.0, "rad": 1.0}

Vec3 = tuple[float, float, float]
QuaternionXYZW = tuple[float, float, float, float]


@dataclass(frozen=True)
class StationGeometry:
    name: str
    half_size_mm: Vec3
    center_mm: Vec3
    quaternion_xyzw: QuaternionXYZW


class GdmlFormatError(ValueError):
    pass


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _required_attr(el: ET.Element, attr: str) -> str:
    value = el.get(attr)
    if value is None:
        raise GdmlFormatError(f"<{_strip_ns(el.tag)}> is missing required attribute '{attr}'")
    return value


def _required_lookup(table: dict[str, Vec3], ref: str, kind: str) -> Vec3:
    value = table.get(ref)
    if value is None:
        raise GdmlFormatError(f"<{kind}ref> points to undefined <define> entry '{ref}'")
    return value


def _euler_to_quaternion_xyzw(rx: float, ry: float, rz: float) -> QuaternionXYZW:
    q = Quaternion.from_euler(rx, ry, rz)
    return (q.x, q.y, q.z, q.w)


def _read_vec3(el: ET.Element, unit_table: dict[str, float], default_unit: str) -> Vec3:
    unit = unit_table.get(el.get("unit", default_unit), 1.0)
    return (
        float(el.get("x", "0")) * unit,
        float(el.get("y", "0")) * unit,
        float(el.get("z", "0")) * unit,
    )


def parse_gdml(path: str) -> list[StationGeometry]:
    root = ET.parse(path).getroot()

    positions: dict[str, Vec3] = {}
    rotations: dict[str, Vec3] = {}
    define_el = root.find("define")
    if define_el is not None:
        for child in define_el:
            tag = _strip_ns(child.tag)
            name = child.get("name")
            if tag == "position" and name:
                positions[name] = _read_vec3(child, _LENGTH_UNITS_MM, "mm")
            elif tag == "rotation" and name:
                rotations[name] = _read_vec3(child, _ANGLE_UNITS_RAD, "deg")

    box_sizes_mm: dict[str, Vec3] = {}
    solids_el = root.find("solids")
    if solids_el is not None:
        for solid in solids_el:
            if _strip_ns(solid.tag) != "box":
                continue
            unit = _LENGTH_UNITS_MM.get(solid.get("lunit", "mm"), 1.0)
            box_sizes_mm[_required_attr(solid, "name")] = (
                float(_required_attr(solid, "x")) * unit,
                float(_required_attr(solid, "y")) * unit,
                float(_required_attr(solid, "z")) * unit,
            )

    structure_el = root.find("structure")
    if structure_el is None:
        return []

    volume_solid: dict[str, str] = {}
    for volume in structure_el.findall("volume"):
        solidref = volume.find("solidref")
        volume_name = volume.get("name")
        if solidref is not None and volume_name:
            volume_solid[volume_name] = _required_attr(solidref, "ref")

    world_name: str | None = None
    setup_el = root.find("setup")
    if setup_el is not None:
        world_ref = setup_el.find("world")
        if world_ref is not None:
            world_name = world_ref.get("ref")

    world_volume = next(
        (v for v in structure_el.findall("volume") if v.get("name") == world_name), None
    )
    if world_volume is None:
        return []

    stations: list[StationGeometry] = []
    for physvol in world_volume.findall("physvol"):
        volumeref_el = physvol.find("volumeref")
        if volumeref_el is None:
            continue
        volume_ref = _required_attr(volumeref_el, "ref")
        size_mm = box_sizes_mm.get(volume_solid.get(volume_ref, ""))
        if size_mm is None:
            continue

        pos_el = physvol.find("position")
        posref_el = physvol.find("positionref")
        if pos_el is not None:
            center_mm = _read_vec3(pos_el, _LENGTH_UNITS_MM, "mm")
        elif posref_el is not None:
            center_mm = _required_lookup(positions, _required_attr(posref_el, "ref"), "position")
        else:
            center_mm = (0.0, 0.0, 0.0)

        rot_el = physvol.find("rotation")
        rotref_el = physvol.find("rotationref")
        if rot_el is not None:
            rotation_rad = _read_vec3(rot_el, _ANGLE_UNITS_RAD, "deg")
        elif rotref_el is not None:
            rotation_rad = _required_lookup(rotations, _required_attr(rotref_el, "ref"), "rotation")
        else:
            rotation_rad = (0.0, 0.0, 0.0)

        quaternion = _euler_to_quaternion_xyzw(*rotation_rad)

        stations.append(
            StationGeometry(
                name=physvol.get("name") or volume_ref,
                half_size_mm=(size_mm[0] / 2.0, size_mm[1] / 2.0, size_mm[2] / 2.0),
                center_mm=center_mm,
                quaternion_xyzw=quaternion,
            )
        )

    return stations
