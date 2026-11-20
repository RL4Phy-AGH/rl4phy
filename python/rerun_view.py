import colorsys
import zlib
from collections import Counter

import numpy as np
import rerun as rr
from loguru import logger

from gdml_geometry import PlacedCylinder, PlacedMesh, PlacedSolid

FLUSH_TIMEOUT_S = 2


def _path_color(path: str) -> list[int]:
    hue = (zlib.crc32(path.encode()) % 997) / 997.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.95)
    return [round(r * 255), round(g * 255), round(b * 255)]


def _charge_color(charge: float) -> list[int]:
    if charge > 0.0:
        return [0, 0, 255]
    if charge < 0.0:
        return [255, 0, 0]
    return [0, 255, 0]


class RerunView:
    def __init__(self, url: str, max_labels: int) -> None:
        rr.init("rl4phy")
        rr.connect_grpc(url)
        logger.info(f"Sending to the Rerun viewer at {url}")
        rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Y_UP, static=True)
        self._max_labels = max_labels
        self._events_seen = 0
        self._geometry_entities: set[str] = set()

    def draw_geometry(self, solids: list[PlacedSolid]) -> None:
        slot = self._events_seen
        logger.info(f"Loaded {len(solids)} volume(s) from gRPC GDML (index {slot})")
        rr.set_time("event_index", sequence=slot)

        groups: dict[tuple[str, str], list[PlacedSolid]] = {}
        for solid in solids:
            groups.setdefault((solid.path, type(solid).__name__), []).append(solid)

        entities = {f"world/{path}" for path, _ in groups}
        for gone in self._geometry_entities - entities:
            rr.log(gone, rr.Clear(recursive=False))
        self._geometry_entities = entities

        for (path, _), group in groups.items():
            color = _path_color(path)
            entity = f"world/{path}"

            if isinstance(group[0], PlacedMesh):
                template = group[0]
                alpha = 70 if template.is_container else 255
                rr.log(
                    entity,
                    rr.Mesh3D(
                        vertex_positions=template.local_vertices_mm,
                        vertex_normals=template.vertex_normals,
                        albedo_factor=[*color, alpha],
                    ),
                    rr.InstancePoses3D(
                        translations=[s.center_mm for s in group],
                        quaternions=[s.quaternion_xyzw for s in group],
                    ),
                )
                continue

            shared = {
                "centers": [s.center_mm for s in group],
                "quaternions": [s.quaternion_xyzw for s in group],
                "colors": color,
                "labels": [f"{s.name} #{s.copy_number}" for s in group],
                "show_labels": len(group) <= self._max_labels,
                "fill_mode": "majorwireframe" if group[0].is_container else "solid",
            }
            if isinstance(group[0], PlacedCylinder):
                archetype = rr.Cylinders3D(
                    lengths=[s.length_mm for s in group],
                    radii=[s.radius_mm for s in group],
                    **shared,
                )
            else:
                archetype = rr.Boxes3D(
                    half_sizes=[s.half_size_mm for s in group],
                    **shared,
                )
            rr.log(entity, archetype)

    def draw_trajectories(self, event) -> None:
        tracks = event.trajectories
        polylines = [
            np.asarray(t.points, dtype=np.float32).reshape(-1, 3) for t in tracks
        ]
        colors = np.array([_charge_color(t.charge) for t in tracks], dtype=np.uint8)
        colors = colors.reshape(-1, 3)
        points = (
            np.concatenate(polylines)
            if polylines
            else np.zeros((0, 3), dtype=np.float32)
        )
        point_colors = np.repeat(colors, [len(p) for p in polylines], axis=0)

        slot = self._events_seen
        self._events_seen += 1
        rr.set_time("event_index", sequence=slot)

        rr.log(
            "world/tracks/lines",
            rr.LineStrips3D(
                polylines,
                colors=colors,
                labels=[f"{t.particle_name} #{t.track_id}" for t in tracks],
                show_labels=len(tracks) <= self._max_labels,
            ),
            rr.AnyValues(
                event_id=event.event_id,
                initial_e_kin=[t.initial_e_kin for t in tracks],
            ),
        )
        rr.log("world/tracks/points", rr.Points3D(points, colors=point_colors))

        species = Counter(t.particle_name for t in tracks)
        tally = ", ".join(f"{n} {name}" for name, n in species.most_common())
        logger.info(
            f"tracks: event={event.event_id} (index {slot})  "
            f"{len(tracks)} track(s), {len(points)} point(s)  "
            f"[{tally}]"
        )

    def close(self) -> None:
        try:
            rr.get_global_data_recording().flush(timeout_sec=FLUSH_TIMEOUT_S)
        except Exception:
            logger.warning(
                f"Rerun did not flush in {FLUSH_TIMEOUT_S} s; "
                "the last events may be missing"
            )
        rr.disconnect()
