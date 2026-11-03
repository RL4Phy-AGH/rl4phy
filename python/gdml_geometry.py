"""Detector geometry read from GDML with pyg4ometry.

Boxes and plain cylinders stay Rerun primitives because Rerun meshes have no
wireframe mode: a meshed envelope would hide what is inside it. Everything
else is tessellated.

Easy to get wrong:

* GDML stores the rotation of the mother frame, not of the solid, so the
  matrix is transposed before use. Check: B5's second arm is written as
  y = +30 deg and must end up along (-sin 30, 0, cos 30).
* pyg4ometry returns placement rotations in radians but keeps a solid's
  angles in the solid's own aunit.
* GDML lengths are full lengths; Geant4 constructors take half lengths.
"""

from __future__ import annotations

import functools
import math
import re
import tempfile
from dataclasses import dataclass, field

import numpy as np
import pyg4ometry.gdml as gdml
from loguru import logger

Vec3 = tuple[float, float, float]
QuaternionXYZW = tuple[float, float, float, float]
_Mesh = tuple[np.ndarray, np.ndarray, np.ndarray]

# A logical volume reused deep in the tree multiplies out; without a cap it
# takes the server down.
MAX_SOLIDS = 50_000

# Counted as Rerun receives them, three per triangle, over distinct solids:
# copies share one mesh, so repetition is free.
MAX_MESH_VERTICES = 5_000_000

# pyg4ometry's axis ids for x, y, z.
_REPLICA_AXIS_INDEX = {1: 0, 2: 1, 3: 2}

# Geant4 writes the volume pointer into every GDML name.
_POINTER_SUFFIX = re.compile(r"0x[0-9a-fA-F]+")


@dataclass(frozen=True, kw_only=True)
class PlacedSolid:
    """One placement in world coordinates.

    `path` is the volume chain from the world down; Rerun turns it into an
    entity path so a whole subdetector can be toggled at once.
    """

    path: str
    name: str
    copy_number: int
    center_mm: Vec3
    quaternion_xyzw: QuaternionXYZW
    is_container: bool


@dataclass(frozen=True, kw_only=True)
class PlacedBox(PlacedSolid):
    half_size_mm: Vec3


@dataclass(frozen=True, kw_only=True)
class PlacedCylinder(PlacedSolid):
    """Axis along local +Z, matching both G4Tubs and Rerun's Cylinders3D."""

    radius_mm: float
    length_mm: float


@dataclass(frozen=True, kw_only=True)
class PlacedMesh(PlacedSolid):
    """Tessellated solid in its own frame; copies share the arrays and differ
    by pose. Each corner is repeated per triangle with that face's normal, or
    the viewer would shade shared edges as rounded.
    """

    local_vertices_mm: np.ndarray
    triangles: np.ndarray
    vertex_normals: np.ndarray
    solid_type: str


@dataclass
class _Walk:
    solids: list[PlacedSolid] = field(default_factory=list)
    # Tessellating the same solid once per copy is the difference between a
    # snappy load and a stalled server: B5 has 17 solids and 976 placements.
    mesh_per_solid: dict[str, _Mesh | None] = field(default_factory=dict)
    vertices: int = 0
    dropped: bool = False


def _clean(name: str) -> str:
    return _POINTER_SUFFIX.sub("", name)


def _scalar(value) -> float:
    return float(value.eval()) if hasattr(value, "eval") else float(value)


def _vector(value) -> np.ndarray:
    if value is None:
        return np.zeros(3)
    raw = value.eval() if hasattr(value, "eval") else value
    return np.array([float(v) for v in raw], dtype=float)


def _degrees(value, aunit: str) -> float:
    angle = _scalar(value)
    return angle if str(aunit).startswith("deg") else math.degrees(angle)


def _solid_rotation(angles_rad: np.ndarray) -> np.ndarray:
    rx, ry, rz = angles_rad
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)

    # The stored matrix rotates the frame; the solid follows its inverse.
    return (mz @ my @ mx).T


def _matrix_to_quaternion_xyzw(m: np.ndarray) -> QuaternionXYZW:
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return (x, y, z, w)


def _face_normals(corners: np.ndarray) -> np.ndarray:
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    normals /= np.where(length == 0.0, 1.0, length)
    return normals


def _tessellate(solid, walk: _Walk) -> _Mesh | None:
    if solid.name in walk.mesh_per_solid:
        return walk.mesh_per_solid[solid.name]

    try:
        vertices, polygons, _ = solid.mesh().toVerticesAndPolygons()
    except Exception:
        logger.opt(exception=True).warning(
            f"Could not tessellate {_clean(solid.name)!r}, skipping it"
        )
        walk.mesh_per_solid[solid.name] = None
        return None

    triangles = []
    for polygon in polygons:
        for i in range(1, len(polygon) - 1):
            triangles.append((polygon[0], polygon[i], polygon[i + 1]))

    if not triangles:
        walk.mesh_per_solid[solid.name] = None
        return None

    corners = np.asarray(vertices, dtype=np.float32)[np.asarray(triangles)]
    positions = corners.reshape(-1, 3)
    if walk.vertices + len(positions) > MAX_MESH_VERTICES:
        walk.mesh_per_solid[solid.name] = None
        walk.dropped = True
        return None
    walk.vertices += len(positions)

    mesh = (
        positions,
        np.arange(len(positions), dtype=np.uint32).reshape(-1, 3),
        np.repeat(_face_normals(corners), 3, axis=0),
    )
    walk.mesh_per_solid[solid.name] = mesh
    return mesh


def _make_placed(
    solid,
    path: str,
    name: str,
    copy_number: int,
    rotation: np.ndarray,
    center: np.ndarray,
    is_container: bool,
    walk: _Walk,
    dimensions=None,
) -> PlacedSolid | None:
    kind = type(solid).__name__
    common = {
        "path": path,
        "name": name,
        "copy_number": copy_number,
        "center_mm": (float(center[0]), float(center[1]), float(center[2])),
        "quaternion_xyzw": _matrix_to_quaternion_xyzw(rotation),
        "is_container": is_container,
    }

    # A parameterised placement carries its own dimensions, but only the ones
    # that vary per copy; the template solid supplies the rest.
    def param(attr):
        value = getattr(dimensions, attr, None) if dimensions is not None else None
        return value if value is not None else getattr(solid, attr)

    if kind == "Box":
        return PlacedBox(
            **common,
            half_size_mm=(
                _scalar(param("pX")) / 2.0,
                _scalar(param("pY")) / 2.0,
                _scalar(param("pZ")) / 2.0,
            ),
        )

    # Rerun has no hollow or wedge cylinder, so those go through the mesh.
    if kind == "Tubs":
        sweep = _degrees(param("pDPhi"), getattr(solid, "aunit", "deg"))
        if _scalar(param("pRMin")) == 0.0 and sweep >= 359.999:
            return PlacedCylinder(
                **common,
                radius_mm=_scalar(param("pRMax")),
                length_mm=_scalar(param("pDz")),
            )

    mesh = _tessellate(solid, walk)
    if mesh is None:
        return None
    local_vertices, triangles, normals = mesh

    return PlacedMesh(
        **common,
        local_vertices_mm=local_vertices,
        triangles=triangles,
        vertex_normals=normals,
        solid_type=kind,
    )


def _replica_placements(replica) -> list[tuple[int, np.ndarray]]:
    """pyg4ometry's `transforms` on a replica are accumulated over the whole
    subtree (430 entries for a 10 copy replica in B5), so the copies are
    recomputed from the replication parameters.
    """
    axis = _REPLICA_AXIS_INDEX.get(replica.axis)
    if axis is None:
        logger.warning(
            f"Replica {_clean(replica.name)!r} divides along axis {replica.axis} "
            "(rho/phi), which is not supported yet; skipping it"
        )
        return []

    count = int(_scalar(replica.nreplicas))
    width = _scalar(replica.width)
    offset = _scalar(replica.offset)

    placements = []
    for index in range(count):
        shift = np.zeros(3)
        shift[axis] = -0.5 * width * (count - 1) + index * width + offset
        placements.append((index, shift))
    return placements


def _parameterised_placements(
    param,
) -> list[tuple[int, np.ndarray, np.ndarray, object]]:
    dimensions = getattr(param, "paramData", None)
    placements = []
    for index, transform in enumerate(param.transforms):
        rotation, position = transform[0], transform[1]
        placements.append(
            (
                index,
                _vector(position),
                _solid_rotation(_vector(rotation)),
                dimensions[index] if dimensions is not None else None,
            )
        )
    return placements


def _descend(
    logical,
    path: str,
    rotation: np.ndarray,
    center: np.ndarray,
    walk: _Walk,
) -> None:
    for physvol in logical.daughterVolumes:
        if len(walk.solids) >= MAX_SOLIDS:
            return

        name = _clean(physvol.name)
        child_path = f"{path}/{name}"
        child_logical = physvol.logicalVolume
        solid = child_logical.solid
        is_container = bool(child_logical.daughterVolumes)
        kind = type(physvol).__name__

        if kind == "ReplicaVolume":
            local_placements = [
                (index, shift, np.eye(3), None)
                for index, shift in _replica_placements(physvol)
            ]
        elif kind == "ParameterisedVolume":
            local_placements = _parameterised_placements(physvol)
        else:
            local_placements = [
                (
                    int(getattr(physvol, "copyNumber", 0) or 0),
                    _vector(getattr(physvol, "position", None)),
                    _solid_rotation(_vector(getattr(physvol, "rotation", None))),
                    None,
                )
            ]

        for copy_number, local_center, local_rotation, dimensions in local_placements:
            world_rotation = rotation @ local_rotation
            world_center = rotation @ local_center + center

            placed = _make_placed(
                solid,
                child_path,
                name,
                copy_number,
                world_rotation,
                world_center,
                is_container,
                walk,
                dimensions,
            )
            if placed is not None:
                walk.solids.append(placed)

            _descend(child_logical, child_path, world_rotation, world_center, walk)


def parse_gdml(path: str) -> list[PlacedSolid]:
    # Geant4 writes density and temperature for NIST materials; without this
    # flag the reader rejects them.
    registry = gdml.Reader(path, reduceNISTMaterialsToPredefined=True).getRegistry()
    world = registry.getWorldVolume()
    world_name = _clean(world.name)

    walk = _Walk()
    root = _make_placed(
        world.solid,
        world_name,
        world_name,
        0,
        np.eye(3),
        np.zeros(3),
        bool(world.daughterVolumes),
        walk,
    )
    if root is not None:
        walk.solids.append(root)

    _descend(world, world_name, np.eye(3), np.zeros(3), walk)

    if len(walk.solids) >= MAX_SOLIDS:
        logger.warning(
            f"Geometry hit the {MAX_SOLIDS} solid cap; the rest is not shown"
        )
    if walk.dropped:
        logger.warning(
            f"Geometry hit the {MAX_MESH_VERTICES} vertex cap; some meshes are missing"
        )
    return walk.solids


@functools.lru_cache(maxsize=8)
def parse_gdml_bytes(gdml: bytes) -> list[PlacedSolid]:
    # pyg4ometry takes a path, not bytes.
    with tempfile.NamedTemporaryFile(suffix=".gdml", delete_on_close=False) as handle:
        handle.write(gdml)
        handle.close()
        return parse_gdml(handle.name)
