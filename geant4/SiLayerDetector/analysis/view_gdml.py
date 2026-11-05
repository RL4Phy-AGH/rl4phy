"""Draw a GDML geometry with matplotlib (no extra dependencies).

    python ../analysis/view_gdml.py siplate.gdml                # -> siplate.png
    python ../analysis/view_gdml.py siplate.gdml --show         # interactive
    python ../analysis/view_gdml.py det.gdml --hide World --out det.png

Supports what a simple detector needs: box and tube solids, nested volumes,
placements with positions and rotations (inline or by reference to <define>),
constants and unit attributes. Other solids are listed and skipped. The world is
drawn as a wireframe, the other volumes as translucent solids coloured by
material. Each volume is listed in the legend with its material and size.
"""

from __future__ import annotations

import argparse
import ast
import operator
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

UNITS = {
    "nm": 1e-6,
    "um": 1e-3,
    "mm": 1.0,
    "cm": 10.0,
    "m": 1e3,
    "km": 1e6,
    "rad": 1.0,
    "mrad": 1e-3,
    "deg": np.pi / 180,
    "degree": np.pi / 180,
}

COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a5cd6", "#d64f8a"]
WORLD_COLOR = "#8a8a85"

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def evaluate(expr: str, names: dict[str, float]) -> float:
    """Arithmetic expression of numbers, constants and units (no function calls)."""

    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"cannot evaluate '{expr}'")

    return ev(ast.parse(expr.strip(), mode="eval").body)


# --------------------------------------------------------------------------- #
# GDML model
# --------------------------------------------------------------------------- #


@dataclass
class Placed:
    """A logical volume placed in the world: its solid and global transform."""

    name: str
    volume: str
    material: str
    solid: ET.Element
    rotation: np.ndarray  # 3x3, local -> global
    translation: np.ndarray  # mm
    depth: int


class Gdml:
    def __init__(self, path: Path):
        root = ET.parse(path).getroot()
        self.names = dict(UNITS)
        self.positions: dict[str, np.ndarray] = {}
        self.rotations: dict[str, np.ndarray] = {}
        define = root.find("define")
        if define is not None:
            self._read_define(define)
        self.solids = {s.get("name"): s for s in root.find("solids")}
        self.volumes = {
            v.get("name"): v for v in root.find("structure") if v.tag == "volume"
        }
        world = root.find("setup/world")
        self.world = world.get("ref")

    def _read_define(self, define: ET.Element):
        for el in define:
            name = el.get("name")
            if el.tag in ("constant", "variable"):
                self.names[name] = evaluate(el.get("value"), self.names)
            elif el.tag == "quantity":
                unit = self.names.get(el.get("unit", ""), 1.0)
                self.names[name] = evaluate(el.get("value"), self.names) * unit
        for el in define:  # positions and rotations may use the constants
            if el.tag == "position":
                self.positions[el.get("name")] = self.vector(el, "lunit")
            elif el.tag == "rotation":
                self.rotations[el.get("name")] = self.vector(el, "aunit")

    def value(self, el: ET.Element, attr: str, unit_attr: str, default=0.0):
        text = el.get(attr)
        if text is None:
            return default
        unit = self.names[el.get(unit_attr, "mm" if unit_attr == "lunit" else "rad")]
        return evaluate(text, self.names) * unit

    def vector(self, el: ET.Element, unit_attr: str) -> np.ndarray:
        if el.get("unit"):  # <position unit="mm"> / <rotation unit="deg">
            el = ET.Element(el.tag, {**el.attrib, unit_attr: el.get("unit")})
        return np.array([self.value(el, a, unit_attr) for a in "xyz"])

    def _placement(self, pv: ET.Element):
        pos = np.zeros(3)
        angles = np.zeros(3)
        for child in pv:
            if child.tag == "position":
                pos = self.vector(child, "lunit")
            elif child.tag == "positionref":
                pos = self.positions[child.get("ref")]
            elif child.tag == "rotation":
                angles = self.vector(child, "aunit")
            elif child.tag == "rotationref":
                angles = self.rotations[child.get("ref")]
        return rotation_matrix(angles), pos

    def placed(self) -> list[Placed]:
        """All volume instances, depth-first from the world."""
        out = []

        def walk(volume, rot, trans, depth, name):
            v = self.volumes[volume]
            solid = self.solids[v.find("solidref").get("ref")]
            material = v.find("materialref").get("ref")
            out.append(Placed(name, volume, material, solid, rot, trans, depth))
            for pv in v.findall("physvol"):
                r, t = self._placement(pv)
                child = pv.find("volumeref").get("ref")
                walk(child, rot @ r, rot @ t + trans, depth + 1, pv.get("name", child))

        walk(self.world, np.eye(3), np.zeros(3), 0, self.world)
        return out


def rotation_matrix(angles: np.ndarray) -> np.ndarray:
    """Active rotation of a GDML placement. Geant4 builds R = Rz Ry Rx from the
    angles and places the daughter with its inverse (G4GDMLReadStructure)."""
    ax, ay, az = angles
    cx, sx, cy, sy, cz, sz = (
        np.cos(ax),
        np.sin(ax),
        np.cos(ay),
        np.sin(ay),
        np.cos(az),
        np.sin(az),
    )
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return (rz @ ry @ rx).T


# --------------------------------------------------------------------------- #
# Meshes
# --------------------------------------------------------------------------- #


def box_mesh(g: Gdml, s: ET.Element):
    """Faces of a box (GDML x, y, z are full lengths) and its size label."""
    dx, dy, dz = (g.value(s, a, "lunit") / 2 for a in "xyz")
    c = np.array(
        [
            [sx * dx, sy * dy, sz * dz]
            for sx in (-1, 1)
            for sy in (-1, 1)
            for sz in (-1, 1)
        ]
    )
    faces = [[0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4],
             [1, 3, 7, 5]]  # fmt: skip
    return [c[f] for f in faces], f"{2 * dx:g} x {2 * dy:g} x {2 * dz:g} mm"


def tube_mesh(g: Gdml, s: ET.Element, n: int = 48):
    rmin = g.value(s, "rmin", "lunit")
    rmax = g.value(s, "rmax", "lunit")
    hz = g.value(s, "z", "lunit") / 2
    phi0 = g.value(s, "startphi", "aunit")
    dphi = g.value(s, "deltaphi", "aunit", default=2 * np.pi)
    phi = phi0 + np.linspace(0, dphi, n + 1)
    faces = []
    for a, b in zip(phi[:-1], phi[1:], strict=True):
        ca, sa, cb, sb = np.cos(a), np.sin(a), np.cos(b), np.sin(b)
        for r in {rmin, rmax} - {0.0}:
            faces.append(
                [[r * ca, r * sa, -hz], [r * cb, r * sb, -hz], [r * cb, r * sb, hz],
                 [r * ca, r * sa, hz]]
            )  # fmt: skip
        for z in (-hz, hz):
            faces.append(
                [[rmin * ca, rmin * sa, z], [rmax * ca, rmax * sa, z],
                 [rmax * cb, rmax * sb, z], [rmin * cb, rmin * sb, z]]
            )  # fmt: skip
    label = f"r {rmin:g}-{rmax:g} mm, length {2 * hz:g} mm"
    return [np.array(f) for f in faces], label


MESHES = {"box": box_mesh, "tube": tube_mesh}


# --------------------------------------------------------------------------- #


def draw(g: Gdml, hide: set[str], alpha: float, out: Path | None, title: str):
    import matplotlib  # noqa: PLC0415 (backend chosen before pyplot)

    if out is not None:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from matplotlib.lines import Line2D  # noqa: PLC0415
    from matplotlib.patches import Patch  # noqa: PLC0415
    from mpl_toolkits.mplot3d.art3d import (  # noqa: PLC0415
        Line3DCollection,
        Poly3DCollection,
    )

    fig = plt.figure(figsize=(9, 7.5))
    ax = fig.add_subplot(projection="3d")
    material_color: dict[str, str] = {}
    handles = []
    points = []
    for p in g.placed():
        if p.name in hide or p.volume in hide:
            continue
        mesh = MESHES.get(p.solid.tag)
        if mesh is None:
            logger.warning(f"{p.name}: solid <{p.solid.tag}> not supported, skipped")
            continue
        faces, size = mesh(g, p.solid)
        faces = [f @ p.rotation.T + p.translation for f in faces]
        points.extend(faces)
        label = f"{p.name}: {p.material}, {size}"
        if p.depth == 0:
            edges = [np.vstack([f, f[:1]]) for f in faces]
            ax.add_collection3d(
                Line3DCollection(edges, colors=WORLD_COLOR, linewidths=0.6)
            )
            handles.append(Line2D([], [], color=WORLD_COLOR, lw=1, label=label))
            continue
        color = material_color.setdefault(
            p.material, COLORS[len(material_color) % len(COLORS)]
        )
        ax.add_collection3d(
            Poly3DCollection(
                faces, facecolors=color, edgecolors=color, linewidths=0.3, alpha=alpha
            )
        )
        handles.append(Patch(facecolor=color, alpha=alpha, label=label))

    if not points:
        raise SystemExit("nothing to draw")
    pts = np.vstack(points)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    pad = 0.05 * (hi - lo).max()
    for setter, a, b in zip(
        (ax.set_xlim, ax.set_ylim, ax.set_zlim), lo - pad, hi + pad, strict=True
    ):
        setter(a, b)
    ax.set_box_aspect(hi - lo + 2 * pad)
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    ax.set_zlabel("z [mm] (beam)")
    ax.view_init(elev=20, azim=-60)
    ax.set_title(title)
    ax.legend(handles=handles, loc="upper left", fontsize=8.5, frameon=False)
    fig.tight_layout()
    if out is None:
        plt.show()
    else:
        fig.savefig(out, dpi=150)
        logger.info(f"geometry drawn to {out}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path, help="image file (default <file>.png)")
    ap.add_argument("--show", action="store_true", help="open a window instead")
    ap.add_argument(
        "--hide", nargs="*", default=[], help="volume or placement names to skip"
    )
    ap.add_argument("--alpha", type=float, default=0.55, help="opacity of solids")
    args = ap.parse_args()

    g = Gdml(args.file)
    for p in g.placed():
        logger.info(
            f"{'  ' * p.depth}{p.name} ({p.solid.tag}, {p.material}) "
            f"at {np.round(p.translation, 4).tolist()} mm"
        )
    out = None if args.show else (args.out or args.file.with_suffix(".png"))
    draw(g, set(args.hide), args.alpha, out, args.file.name)


if __name__ == "__main__":
    main()
