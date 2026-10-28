from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

import numpy as np

from app.core.simulation_world import SimulationWorld
from app.models.pose import Vec3
from app.models.snapshot import SimulationSnapshot

try:
    import pyvista as pv
except ImportError:  # pragma: no cover - exercised when optional GUI dependency is absent.
    pv = None


class ShipLoader3DViewer:
    """PyVista 3D viewer driven only by SimulationSnapshot data."""

    def __init__(
        self,
        title: str = "Shiploader 3D Motion Simulation",
        off_screen: bool = False,
        window_size: tuple[int, int] = (1280, 820),
        max_trajectory_points: int = 240,
        render_quality: str = "fast",
        target_fps: float = 30.0,
        text_update_interval: float = 0.25,
    ) -> None:
        if pv is None:
            raise RuntimeError(
                "PyVista is not installed. Install it with `python -m pip install pyvista`."
            )
        if render_quality not in {"fast", "balanced", "high"}:
            raise ValueError("render_quality must be one of: fast, balanced, high")
        self.title = title
        self.off_screen = off_screen
        self.window_size = window_size
        self.max_trajectory_points = max_trajectory_points
        self.render_quality = render_quality
        self.target_fps = target_fps
        self.text_update_interval = text_update_interval
        self.render_tubes = render_quality == "high"
        self.render_spheres = render_quality in {"balanced", "high"}
        self.show_static_edges = render_quality == "high"
        self.enable_antialias = render_quality in {"balanced", "high"}
        self.plotter = pv.Plotter(
            title=title,
            off_screen=off_screen,
            window_size=window_size,
        )
        self.meshes: dict[str, object] = {}
        self.text_actor = None
        self.trajectory: list[np.ndarray] = []
        self.last_text_update_sim_time = -float("inf")
        self.is_setup = False

    def setup(self, snapshot: SimulationSnapshot) -> None:
        if self.target_fps <= 0:
            raise ValueError("target_fps must be positive")
        self.plotter.set_background("#f7f9fb")
        self.plotter.add_axes()
        self._add_static_scene(snapshot)

        self.meshes["mast"] = self._add_polyline(
            "mast",
            self._mast_points(snapshot),
            color="#4b5563",
            line_width=7,
        )
        self.meshes["boom"] = self._add_polyline(
            "boom",
            self._boom_points(snapshot),
            color="#f59e0b",
            line_width=10,
        )
        self.meshes["chute"] = self._add_polyline(
            "chute",
            self._chute_points(snapshot),
            color="#2563eb",
            line_width=8,
        )
        self.meshes["markers"] = self._add_points(
            "markers",
            self._marker_points(snapshot),
            color="#111827",
            point_size=14,
        )
        self.meshes["discharge"] = self._add_points(
            "discharge",
            [self._vec(snapshot.key_points["discharge_point"])],
            color="#dc2626",
            point_size=20,
        )
        start_point = self._vec(snapshot.key_points["discharge_point"])
        self.trajectory = [start_point.copy()]
        self.meshes["trajectory"] = self._add_polyline(
            "trajectory",
            self._trajectory_points(start_point),
            color="#16a34a",
            line_width=4,
        )
        self.text_actor = self.plotter.add_text(
            self._status_text(snapshot),
            position="upper_left",
            font_size=10,
            color="#111827",
            name="status_text",
        )
        self.plotter.camera_position = [
            (64.0, -54.0, 38.0),
            (15.0, 14.0, 8.0),
            (0.0, 0.0, 1.0),
        ]
        if self.enable_antialias:
            self.plotter.enable_anti_aliasing()
        self.is_setup = True

    def update(self, snapshot: SimulationSnapshot) -> None:
        if not self.is_setup:
            self.setup(snapshot)

        self._update_polyline("mast", self._mast_points(snapshot))
        self._update_polyline("boom", self._boom_points(snapshot))
        self._update_polyline("chute", self._chute_points(snapshot))
        self._update_points("markers", self._marker_points(snapshot))
        discharge_point = self._vec(snapshot.key_points["discharge_point"])
        self._update_points("discharge", [discharge_point])

        self.trajectory.append(discharge_point.copy())
        if len(self.trajectory) > self.max_trajectory_points:
            self.trajectory = self.trajectory[-self.max_trajectory_points :]
        self._update_polyline("trajectory", self._trajectory_points(discharge_point))
        if snapshot.sim_time - self.last_text_update_sim_time >= self.text_update_interval:
            self._update_text(self._status_text(snapshot))
            self.last_text_update_sim_time = snapshot.sim_time

    def animate(
        self,
        world: SimulationWorld,
        steps: int = 300,
        dt: float | None = None,
        realtime: bool = True,
        playback_speed: float = 1.0,
        keep_open: bool = True,
        screenshot_path: str | Path | None = None,
    ) -> SimulationSnapshot:
        snapshot = world.get_snapshot()
        self.setup(snapshot)

        if not self.off_screen:
            self.plotter.show(auto_close=False, interactive_update=True)

        for _ in range(steps):
            frame_started_at = time.perf_counter()
            snapshot = world.step(dt)
            self.update(snapshot)
            if not self.off_screen:
                self.plotter.update()
            self.plotter.render()
            if realtime and not self.off_screen:
                sim_dt = world.default_dt if dt is None else dt
                frame_budget = min(1.0 / self.target_fps, sim_dt / max(playback_speed, 1e-6))
                render_elapsed = time.perf_counter() - frame_started_at
                sleep_seconds = frame_budget - render_elapsed
                time.sleep(max(sleep_seconds, 0.0))

        if screenshot_path is not None:
            self.screenshot(screenshot_path)

        if self.off_screen or not keep_open:
            self.close()
        elif keep_open:
            print("3D animation complete. Close the PyVista window to exit.")
            self.plotter.show()
        return snapshot

    def screenshot(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.plotter.screenshot(str(output_path))
        return output_path

    def close(self) -> None:
        self.plotter.close()

    def _add_static_scene(self, snapshot: SimulationSnapshot) -> None:
        base = self._vec(snapshot.key_points["base_position"])
        ground = pv.Plane(
            center=(base[0] + 16.0, 15.0, -0.05),
            direction=(0.0, 0.0, 1.0),
            i_size=90.0,
            j_size=58.0,
        )
        self.plotter.add_mesh(ground, color="#e5e7eb", opacity=0.45)

        ship = pv.Cube(center=(base[0] + 15.0, 31.0, 2.0), x_length=62.0, y_length=12.0, z_length=4.0)
        self.plotter.add_mesh(
            ship,
            color="#93c5fd",
            opacity=0.24,
            show_edges=self.show_static_edges,
            edge_color="#3b82f6",
        )

        rail_y = (-1.2, 1.2)
        rail_segments = []
        for y in rail_y:
            rail_segments.extend(
                [
                    [base[0] - 35.0, y, 0.0],
                    [base[0] + 45.0, y, 0.0],
                ]
            )
        rail_mesh = self._segment_mesh(rail_segments)
        self.plotter.add_mesh(
            rail_mesh,
            color="#374151",
            line_width=5,
            render_lines_as_tubes=self.render_tubes,
        )

    def _add_polyline(
        self,
        name: str,
        points: Iterable[np.ndarray],
        color: str,
        line_width: int,
    ):
        mesh = self._polyline_mesh(points)
        self.plotter.add_mesh(
            mesh,
            color=color,
            line_width=line_width,
            render_lines_as_tubes=self.render_tubes,
            name=name,
        )
        return mesh

    def _add_points(
        self,
        name: str,
        points: Iterable[np.ndarray],
        color: str,
        point_size: int,
    ):
        mesh = pv.PolyData(np.asarray(list(points), dtype=float))
        self.plotter.add_mesh(
            mesh,
            color=color,
            point_size=point_size,
            render_points_as_spheres=self.render_spheres,
            name=name,
        )
        return mesh

    def _update_polyline(self, name: str, points: Iterable[np.ndarray]) -> None:
        mesh = self.meshes[name]
        new_mesh = self._polyline_mesh(points)
        mesh.points = new_mesh.points
        if len(mesh.lines) != len(new_mesh.lines):
            mesh.lines = new_mesh.lines
        self._modified(mesh)

    def _update_points(self, name: str, points: Iterable[np.ndarray]) -> None:
        mesh = self.meshes[name]
        mesh.points = np.asarray(list(points), dtype=float)
        self._modified(mesh)

    def _update_text(self, text: str) -> None:
        if self.text_actor is not None and hasattr(self.text_actor, "SetInput"):
            self.text_actor.SetInput(text)
            return
        self.plotter.remove_actor("status_text")
        self.text_actor = self.plotter.add_text(
            text,
            position="upper_left",
            font_size=10,
            color="#111827",
            name="status_text",
        )

    def _polyline_mesh(self, points: Iterable[np.ndarray]):
        point_array = np.asarray(list(points), dtype=float)
        if len(point_array) == 1:
            point_array = np.vstack([point_array, point_array])
        mesh = pv.PolyData(point_array)
        mesh.lines = np.hstack([[len(point_array)], np.arange(len(point_array))]).astype(np.int_)
        return mesh

    def _segment_mesh(self, points: list[list[float]]):
        point_array = np.asarray(points, dtype=float)
        cells = []
        for index in range(0, len(point_array), 2):
            cells.extend([2, index, index + 1])
        mesh = pv.PolyData(point_array)
        mesh.lines = np.asarray(cells, dtype=np.int_)
        return mesh

    def _trajectory_points(self, current_point: np.ndarray) -> list[np.ndarray]:
        if not self.trajectory:
            self.trajectory = [current_point.copy()]
        points = list(self.trajectory)
        while len(points) < 2:
            points.append(current_point.copy())
        return points

    def _mast_points(self, snapshot: SimulationSnapshot) -> list[np.ndarray]:
        return [
            self._vec(snapshot.key_points["base_position"]),
            self._vec(snapshot.key_points["boom_root_position"]),
        ]

    def _boom_points(self, snapshot: SimulationSnapshot) -> list[np.ndarray]:
        return [
            self._vec(snapshot.key_points["boom_root_position"]),
            self._vec(snapshot.key_points["boom_tip_position"]),
        ]

    def _chute_points(self, snapshot: SimulationSnapshot) -> list[np.ndarray]:
        return [
            self._vec(snapshot.key_points["chute_top_position"]),
            self._vec(snapshot.key_points["chute_bottom_position"]),
            self._vec(snapshot.key_points["discharge_point"]),
        ]

    def _marker_points(self, snapshot: SimulationSnapshot) -> list[np.ndarray]:
        return [
            self._vec(snapshot.key_points["base_position"]),
            self._vec(snapshot.key_points["boom_root_position"]),
            self._vec(snapshot.key_points["boom_tip_position"]),
            self._vec(snapshot.key_points["chute_bottom_position"]),
        ]

    def _status_text(self, snapshot: SimulationSnapshot) -> str:
        axes = snapshot.axis_states
        return "\n".join(
            [
                f"Shiploader 3D | t={snapshot.sim_time:5.1f}s",
                f"travel: {axes['travel'].current:6.2f} m",
                f"slew: {axes['slew'].current:6.2f} deg",
                f"luff: {axes['boom_luff'].current:6.2f} deg",
                f"extension: {axes['boom_extension'].current:6.2f} m",
                f"chute: {axes['chute_rotate'].current:6.2f} deg",
                f"belt: {'ON' if snapshot.belt_state.running else 'OFF'} {snapshot.belt_state.speed_mps:.1f} m/s",
            ]
        )

    @staticmethod
    def _vec(value: Vec3) -> np.ndarray:
        return np.asarray(value.to_list(), dtype=float)

    @staticmethod
    def _modified(mesh) -> None:
        if hasattr(mesh, "modified"):
            mesh.modified()
        elif hasattr(mesh, "Modified"):
            mesh.Modified()
