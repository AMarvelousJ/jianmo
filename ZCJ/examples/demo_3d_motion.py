from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.loader import create_default_ship_loader
from app.core.simulation_world import SimulationWorld
from app.visualization.viewer_3d import ShipLoader3DViewer


def build_world(dt: float) -> SimulationWorld:
    world = SimulationWorld(create_default_ship_loader(), default_dt=dt)
    world.loader.set_axis_target("travel", 20.0, velocity=1.0)
    world.loader.set_axis_target("slew", 45.0, velocity=5.0)
    world.loader.set_axis_target("boom_luff", 20.0, velocity=2.0)
    world.loader.set_axis_target("boom_extension", 10.0, velocity=0.5)
    world.loader.set_axis_target("chute_rotate", 30.0, velocity=10.0)
    world.loader.set_belt(speed=3.5, running=True)
    return world


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the shiploader 3D motion demo.")
    parser.add_argument("--steps", type=int, default=900, help="Number of simulation steps.")
    parser.add_argument("--dt", type=float, default=1 / 30, help="Simulation time step in seconds.")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier for the interactive window.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Target render frames per second for the interactive window.",
    )
    parser.add_argument(
        "--quality",
        choices=["fast", "balanced", "high"],
        default="fast",
        help="Rendering quality. Use fast for smoother animation and high for prettier stills.",
    )
    parser.add_argument(
        "--trajectory-points",
        type=int,
        default=240,
        help="Maximum discharge trajectory points kept in the 3D scene.",
    )
    parser.add_argument(
        "--off-screen",
        action="store_true",
        help="Render without opening a window. Useful for screenshot verification.",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=None,
        help="Optional PNG path for the rendered final frame.",
    )
    parser.add_argument(
        "--no-keep-open",
        action="store_true",
        help="Close the PyVista window immediately after animation completes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    world = build_world(args.dt)
    viewer = ShipLoader3DViewer(
        off_screen=args.off_screen,
        render_quality=args.quality,
        target_fps=args.fps,
        max_trajectory_points=args.trajectory_points,
    )
    final_snapshot = viewer.animate(
        world,
        steps=args.steps,
        dt=args.dt,
        realtime=not args.off_screen,
        playback_speed=args.speed,
        keep_open=not args.no_keep_open,
        screenshot_path=args.screenshot,
    )
    print(
        "3D demo complete: "
        f"t={final_snapshot.sim_time:.1f}s, "
        f"travel={final_snapshot.axis_states['travel'].current:.2f}m, "
        f"slew={final_snapshot.axis_states['slew'].current:.2f}deg"
    )
    if args.screenshot is not None:
        print(f"Screenshot saved: {args.screenshot}")


if __name__ == "__main__":
    main()
