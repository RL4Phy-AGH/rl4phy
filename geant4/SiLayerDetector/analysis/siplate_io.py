"""Reading a simulation run and splitting it into samples.

A run with /siplate/output/tag <tag> writes <tag>.pb, a stream of delimited
siplate.Record messages (proto/siplate.proto): the run header, one Event per
event with its StepHits (and, for some events, their StepPoints), the footer.

The file holds what Geant4 knows directly: 4-momenta, positions, deposits.
Everything the analysis uses is derived here, from the 4-vectors:
  kinetic energy    T = E - m, with m^2 = E^2 - p^2 at the entry
  energy loss       E_entry - E_exit (same particle, so equal to Delta T)
  direction         u = p / |p|
  projected angle   theta_x = atan2(p_x, p_z), theta_y = atan2(p_y, p_z)
  space angle       theta = atan2(|p_T|, p_z), phi = atan2(p_y, p_x)
  step deflection   angle between p before and after the step,
                    atan2(|p0 x p1|, p0 . p1), accurate also at ~urad
Angles are measured from the z axis, the beam direction.

They are collected in two tables with the columns of the earlier CSV output:
  events  one row per event (Run.events), see EVENT_COLUMNS
  steps   one row per stored step (Run.steps), see STEP_COLUMNS
Units: positions mm, step length um, energies MeV, angles mrad, phi rad.
Decoding takes a while for millions of events, so both tables are cached next
to the run file (<tag>.cache.npz) and rebuilt when the run file changes.

One run holds both samples of the study, split by event ID:
  reference  events 0 .. n_reference-1   smooth reference distributions
  simulation events n_reference .. end   the target, event-by-event sample
n_reference defaults to /siplate/output/referenceEvents, stored in the run
header. Geant4 seeds every event independently, so the samples are
statistically independent.
"""

from __future__ import annotations

import hashlib
import importlib.util
import mmap
import shutil
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd
from google.protobuf import __version__ as protobuf_version
from google.protobuf.json_format import MessageToDict
from loguru import logger

from theory import PARTICLES, Beam, Material

PROTO = Path(__file__).resolve().parent.parent / "proto" / "siplate.proto"
CACHE_VERSION = 1
FLUSH_ROWS = 200_000

EVENT_COLUMNS = [
    "event",
    "primary_pdg",
    "n_steps",
    "n_secondaries",
    "edep_total",
    "edep_primary",
    "escape_secondary",
    "primary_ekin_in",
    "primary_ekin_out",
    "primary_eloss",
    "primary_x_out",
    "primary_y_out",
    "primary_ux_out",
    "primary_uy_out",
    "primary_uz_out",
    "primary_theta_x",
    "primary_theta_y",
    "primary_theta",
    "primary_phi",
    "primary_exited",
    "primary_hadronic",
]

STEP_COLUMNS = [
    "event",
    "track",
    "parent",
    "particle",
    "step",
    "process",
    "x_pre",
    "y_pre",
    "z_pre",
    "x_post",
    "y_post",
    "z_post",
    "step_len_um",
    "ekin_pre",
    "ekin_post",
    "dekin",
    "edep",
    "edep_nonion",
    "ux_pre",
    "uy_pre",
    "uz_pre",
    "ux_post",
    "uy_post",
    "uz_post",
    "theta_step",
    "theta_post",
    "phi_post",
    "theta_x_post",
    "theta_y_post",
    "leaves_plate",
]

PDG_NAMES = {pdg: name for pdg, (name, _, _) in PARTICLES.items()} | {
    22: "gamma",
    2112: "neutron",
    1000010020: "deuteron",
    1000010030: "triton",
    1000020030: "He3",
}


# --------------------------------------------------------------------------- #
# Generated protobuf module
# --------------------------------------------------------------------------- #


def _pb2():
    """siplate_pb2, generated with protoc from proto/siplate.proto into
    ~/.cache/siplate/proto/, once per version of the schema and of protobuf."""
    text = PROTO.read_bytes()
    key = hashlib.sha1(text + protobuf_version.encode()).hexdigest()[:12]
    out = Path.home() / ".cache" / "siplate" / "proto" / key
    module = out / "siplate_pb2.py"
    if not module.exists():
        protoc = shutil.which("protoc")
        if protoc is None:
            raise RuntimeError("protoc not found: activate the conda environment")
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [protoc, f"-I{PROTO.parent}", f"--python_out={out}", PROTO.name],
            check=True,
        )
    spec = importlib.util.spec_from_file_location("siplate_pb2", module)
    pb2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pb2)
    return pb2


pb2 = _pb2()


def iter_records(path: Path):
    """siplate.Record messages of a run file, in order."""
    record = pb2.Record
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        pos, end = 0, len(mm)
        while pos < end:
            size, shift = 0, 0
            while True:
                b = mm[pos]
                pos += 1
                size |= (b & 0x7F) << shift
                if b < 0x80:
                    break
                shift += 7
            yield record.FromString(mm[pos : pos + size])
            pos += size


# --------------------------------------------------------------------------- #
# Kinematics from 4-vectors
# --------------------------------------------------------------------------- #


def invariant_mass(e, px, py, pz):
    return np.sqrt(np.maximum(e**2 - (px**2 + py**2 + pz**2), 0.0))


def directions(px, py, pz, fallback=None):
    """Unit vectors p/|p|; where |p| = 0 (a track at rest) the fallback
    direction, as Geant4 keeps the last direction of a stopped track."""
    norm = np.sqrt(px**2 + py**2 + pz**2)
    with np.errstate(invalid="ignore", divide="ignore"):
        u = np.stack([px / norm, py / norm, pz / norm])
    if fallback is not None:
        u = np.where(norm > 0, u, fallback)
    return u


def angles(u):
    """Angles of unit vectors from the z axis: theta_x, theta_y, theta [mrad]
    and phi [rad]."""
    ux, uy, uz = u
    return (
        np.arctan2(ux, uz) * 1e3,
        np.arctan2(uy, uz) * 1e3,
        np.arctan2(np.hypot(ux, uy), uz) * 1e3,
        np.arctan2(uy, ux),
    )


def angle_between(u0, u1):
    """Angle between unit vectors [mrad], stable at small angles."""
    cross = np.cross(u0, u1, axis=0)
    return np.arctan2(np.linalg.norm(cross, axis=0), np.sum(u0 * u1, axis=0)) * 1e3


def _event_table(raw: np.ndarray) -> pd.DataFrame:
    """Event columns from the raw per-event values (see _decode)."""
    (event, pdg, n_steps, n_sec, edep, edep_prim, escape, e_in, px_in, py_in,
     pz_in, e_out, px_out, py_out, pz_out, x_out, y_out, exited,
     hadronic) = raw.T  # fmt: skip
    mass = invariant_mass(e_in, px_in, py_in, pz_in)
    u_in = directions(px_in, py_in, pz_in)
    u_out = directions(px_out, py_out, pz_out, fallback=u_in)
    theta_x, theta_y, theta, phi = angles(u_out)
    return pd.DataFrame(
        {
            "event": event.astype(np.int64),
            "primary_pdg": pdg.astype(np.int64),
            "n_steps": n_steps.astype(np.int64),
            "n_secondaries": n_sec.astype(np.int64),
            "edep_total": edep,
            "edep_primary": edep_prim,
            "escape_secondary": escape,
            "primary_ekin_in": e_in - mass,
            "primary_ekin_out": e_out - mass,
            "primary_eloss": e_in - e_out,
            "primary_x_out": x_out,
            "primary_y_out": y_out,
            "primary_ux_out": u_out[0],
            "primary_uy_out": u_out[1],
            "primary_uz_out": u_out[2],
            "primary_theta_x": theta_x,
            "primary_theta_y": theta_y,
            "primary_theta": theta,
            "primary_phi": phi,
            "primary_exited": exited.astype(np.int64),
            "primary_hadronic": hadronic.astype(np.int64),
        }
    )[EVENT_COLUMNS]


def _step_table(raw: np.ndarray) -> pd.DataFrame:
    """Step columns from the raw per-step values (see _decode)."""
    (event, track, parent, pdg, step, process, x0, y0, z0, x1, y1, z1, length,
     e0, px0, py0, pz0, e1, px1, py1, pz1, edep, edep_nonion, leaves,
     mass) = raw.T  # fmt: skip
    u0 = directions(px0, py0, pz0)
    u1 = directions(px1, py1, pz1, fallback=u0)
    theta_x, theta_y, theta, phi = angles(u1)
    return pd.DataFrame(
        {
            "event": event.astype(np.int64),
            "track": track.astype(np.int64),
            "parent": parent.astype(np.int64),
            "particle": pdg.astype(np.int64),
            "step": step.astype(np.int64),
            "process": process.astype(np.int64),
            "x_pre": x0,
            "y_pre": y0,
            "z_pre": z0,
            "x_post": x1,
            "y_post": y1,
            "z_post": z1,
            "step_len_um": length * 1e3,
            "ekin_pre": e0 - mass,
            "ekin_post": e1 - mass,
            "dekin": e0 - e1,
            "edep": edep,
            "edep_nonion": edep_nonion,
            "ux_pre": u0[0],
            "uy_pre": u0[1],
            "uz_pre": u0[2],
            "ux_post": u1[0],
            "uy_post": u1[1],
            "uz_post": u1[2],
            "theta_step": angle_between(u0, u1),
            "theta_post": theta,
            "phi_post": phi,
            "theta_x_post": theta_x,
            "theta_y_post": theta_y,
            "leaves_plate": leaves.astype(np.int64),
        }
    )[STEP_COLUMNS]


# --------------------------------------------------------------------------- #
# Decoding the run file
# --------------------------------------------------------------------------- #


def _decode(path: Path):
    """One pass over the file: header, footer and the raw values of the event
    and step tables (plain numbers; the kinematics is computed vectorised)."""
    exited_fate = pb2.FATE_EXITED
    nan = float("nan")
    header = footer = None
    volume = None
    event_rows, step_rows = [], []
    event_blocks, step_blocks = [], []

    for record in iter_records(path):
        kind = record.WhichOneof("content")
        if kind == "header":
            header = record.header
            volume = header.layers[0].volume if header.layers else None
            continue
        if kind == "footer":
            footer = record.footer
            continue

        ev = record.event
        eid = ev.event_id
        n_steps = 0
        edep = edep_prim = escape = 0.0
        secondaries = set()
        first = last = None
        hadronic = 0
        for h in ev.hits:
            if volume is not None and h.volume != volume:
                continue
            n_steps += h.n_steps
            edep += h.edep
            entry = h.entry
            if h.parent_id == 0:
                edep_prim += h.edep
                hadronic |= h.interactions
                if first is None:
                    first = h
                last = h
            else:
                secondaries.add(h.track_id)
                if h.fate == exited_fate:
                    m2 = entry.e**2 - entry.px**2 - entry.py**2 - entry.pz**2
                    escape += h.exit.e - max(m2, 0.0) ** 0.5
            if not len(h.steps):
                continue

            m2 = entry.e**2 - entry.px**2 - entry.py**2 - entry.pz**2
            mass = max(m2, 0.0) ** 0.5
            pos = h.entry_pos
            prev = (pos.x, pos.y, pos.z, entry.e, entry.px, entry.py, entry.pz)
            n = len(h.steps)
            leaves_last = 1 if h.fate == exited_fate else 0
            for k, s in enumerate(h.steps):
                p, q = s.p, s.pos
                cur = (q.x, q.y, q.z, p.e, p.px, p.py, p.pz)
                step_rows.append(
                    (eid, h.track_id, h.parent_id, h.pdg, k + 1, s.process,
                     prev[0], prev[1], prev[2], cur[0], cur[1], cur[2],
                     s.step_length, prev[3], prev[4], prev[5], prev[6],
                     cur[3], cur[4], cur[5], cur[6], s.edep, s.edep_nonion,
                     leaves_last if k == n - 1 else 0, mass)
                )  # fmt: skip
                prev = cur

        if first is None:
            prim = (0, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, 0, 0)
        else:
            a, b, xo = first.entry, last.exit, last.exit_pos
            prim = (first.pdg, a.e, a.px, a.py, a.pz, b.e, b.px, b.py, b.pz,
                    xo.x, xo.y, 1 if last.fate == exited_fate else 0,
                    1 if hadronic else 0)  # fmt: skip
        event_rows.append(
            (eid, prim[0], n_steps, len(secondaries), edep, edep_prim, escape,
             *prim[1:])
        )  # fmt: skip

        if len(event_rows) >= FLUSH_ROWS:
            event_blocks.append(np.array(event_rows, dtype=np.float64))
            event_rows.clear()
        if len(step_rows) >= FLUSH_ROWS:
            step_blocks.append(np.array(step_rows, dtype=np.float64))
            step_rows.clear()

    if header is None:
        raise ValueError(f"{path}: no run header")
    event_blocks.append(np.array(event_rows, dtype=np.float64).reshape(-1, 19))
    step_blocks.append(np.array(step_rows, dtype=np.float64).reshape(-1, 25))
    return header, footer, np.concatenate(event_blocks), np.concatenate(step_blocks)


def _meta(header) -> dict:
    """Run header as the metadata dict used by the analysis and theory.py."""
    meta = {
        "tag": None,
        "run_id": header.run_id,
        "n_events": header.n_events,
        "n_threads": header.n_threads,
        "write_steps": header.write_steps,
        "reference_events": header.reference_events,
        "max_step_events": header.max_step_events,
        "geant4_version": header.geant4_version,
        "physics_list": header.physics_list,
        "schema_version": header.schema_version,
        "processes": list(header.processes),
    }
    if header.layers:
        layer = header.layers[0]
        de = layer.density_effect
        meta["plate"] = {
            "volume": layer.volume,
            "thickness_mm": layer.thickness_mm,
            "size_xy_mm": layer.size_xy_mm,
            "z_center_mm": layer.z_center_mm,
            "max_step_um": layer.max_step_mm * 1e3,
        }
        meta["material"] = {
            "name": layer.material,
            "density_g_cm3": layer.density_g_cm3,
            "radiation_length_mm": layer.radiation_length_mm,
            "mean_excitation_eV": layer.mean_excitation_ev,
            "density_effect": {
                "C": de.c,
                "x0": de.x0,
                "x1": de.x1,
                "a": de.a,
                "m": de.m,
                "delta0": de.delta0,
            },
            "elements": [
                {
                    "symbol": e.symbol,
                    "Z": e.z,
                    "A_g_mol": e.a_g_mol,
                    "mass_fraction": e.mass_fraction,
                }
                for e in layer.elements
            ],
        }
        meta["production_cuts"] = {
            "range_mm": MessageToDict(layer.cut_range_mm),
            "energy_in_plate_MeV": MessageToDict(layer.cut_energy_mev),
        }
    return meta


def _with_names(steps: pd.DataFrame, processes: list[str]) -> pd.DataFrame:
    """PDG codes and process indices of the step table as names."""
    pdg = steps["particle"].to_numpy()
    codes = np.unique(pdg)
    steps["particle"] = pd.Categorical.from_codes(
        np.searchsorted(codes, pdg), [PDG_NAMES.get(int(c), str(c)) for c in codes]
    )
    names = ["none", *processes]
    steps["process"] = pd.Categorical.from_codes(steps["process"].to_numpy() + 1, names)
    return steps


def read_run_file(path: Path, use_cache: bool = True):
    """(header, complete, raw events, raw steps) of a run file, through the
    cache. complete: the footer is present."""
    stat = path.stat()
    key = np.array([CACHE_VERSION, stat.st_size, stat.st_mtime_ns], dtype=np.int64)
    cache = path.with_suffix(".cache.npz")
    if use_cache and cache.exists():
        with np.load(cache, allow_pickle=False) as z:
            if np.array_equal(z["key"], key):
                header = pb2.RunHeader.FromString(z["header"].tobytes())
                return header, bool(z["complete"]), z["events"], z["steps"]

    logger.info(f"decoding {path} ({stat.st_size / 1e6:.0f} MB)")
    header, footer, events, steps = _decode(path)
    np.savez(
        cache,
        key=key,
        header=np.frombuffer(header.SerializeToString(), dtype=np.uint8),
        complete=footer is not None,
        events=events,
        steps=steps,
    )
    return header, footer is not None, events, steps


# --------------------------------------------------------------------------- #
# Run and samples
# --------------------------------------------------------------------------- #


@dataclass
class Run:
    tag: str
    directory: Path
    meta: dict
    events: pd.DataFrame
    steps: pd.DataFrame

    def split(self, n_reference: int | None = None) -> tuple[Sample, Sample]:
        """(reference, simulation): events with ID < n_reference and the rest."""
        if n_reference is None:
            n_reference = int(self.meta.get("reference_events", 0))
        n_events = len(self.events)
        if not 0 < n_reference < n_events:
            raise ValueError(
                f"n_reference = {n_reference} does not split the {n_events} events "
                f"of run '{self.tag}'; set /siplate/output/referenceEvents in the "
                "macro or pass --n-reference"
            )
        is_ref = self.events["event"] < n_reference
        return (
            Sample("reference", self, self.events[is_ref], 0, n_reference),
            Sample("simulation", self, self.events[~is_ref], n_reference, None),
        )


@dataclass
class Sample:
    """Events first_event <= ID < end_event (None: to the end) of a run."""

    name: str
    run: Run
    events: pd.DataFrame
    first_event: int
    end_event: int | None

    @property
    def meta(self) -> dict:
        return self.run.meta

    @property
    def thickness_mm(self) -> float:
        return self.meta["plate"]["thickness_mm"]

    @cached_property
    def material(self) -> Material:
        return Material.from_meta(self.meta)

    @cached_property
    def beam(self) -> Beam:
        """Primary at the plate entrance (most common PDG code, mean energy)."""
        hit = self.events.dropna(subset=["primary_ekin_in"])
        pdg = int(hit["primary_pdg"].mode().iloc[0])
        return Beam.from_pdg(pdg, float(hit["primary_ekin_in"].mean()))

    @cached_property
    def exited(self) -> pd.DataFrame:
        """Events whose primary left the plate."""
        return self.events[self.events["primary_exited"] == 1]

    @cached_property
    def clean(self) -> pd.DataFrame:
        """Primary left the plate without a hadronic interaction: the sample that
        Landau and Moliere theory describe (both are purely electromagnetic)."""
        return self.exited[self.exited["primary_hadronic"] == 0]

    @cached_property
    def theta_projected(self) -> np.ndarray:
        """theta_x and theta_y of clean events pooled [mrad]: same distribution,
        twice the statistics."""
        c = self.clean
        return np.concatenate([c["primary_theta_x"], c["primary_theta_y"]])

    def load_steps(
        self, columns: list[str], max_events: int | None = None
    ) -> pd.DataFrame | None:
        """Steps of the first max_events events of the sample that have stored
        steps. None if there are none."""
        steps = self.run.steps
        event = steps["event"]
        sel = event >= self.first_event
        if self.end_event is not None:
            sel &= event < self.end_event
        if not sel.any():
            return None
        if max_events is not None:
            first = event[sel].iloc[0]
            sel &= event < first + max_events
        cols = list(dict.fromkeys(["event", *columns]))
        return steps.loc[sel, cols].reset_index(drop=True)


def load_run(directory: str | Path, tag: str, use_cache: bool = True) -> Run:
    directory = Path(directory)
    path = directory / f"{tag}.pb"
    if not path.exists():
        raise FileNotFoundError(f"no run file {path}")
    header, complete, events, steps = read_run_file(path, use_cache)
    if not complete:
        logger.warning(f"{path}: no footer, the run was interrupted")
    meta = _meta(header)
    meta["tag"] = tag
    return Run(
        tag,
        directory,
        meta,
        _event_table(events),
        _with_names(_step_table(steps), meta["processes"]),
    )
