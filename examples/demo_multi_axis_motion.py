from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.loader import create_default_ship_loader
from app.core.simulation_world import SimulationWorld


def main() -> None:
    world = SimulationWorld(create_default_ship_loader(), default_dt=0.1)
    world.loader.set_axis_target("travel", 20.0, velocity=1.0)
    world.loader.set_axis_target("slew", 45.0, velocity=5.0)
    world.loader.set_axis_target("boom_luff", 20.0, velocity=2.0)
    world.loader.set_axis_target("boom_extension", 10.0, velocity=0.5)
    world.loader.set_axis_target("chute_rotate", 30.0, velocity=10.0)
    world.loader.set_belt(speed=3.5, running=True)

    snapshots = []
    for _ in range(300):
        snapshot = world.step()
        snapshots.append(snapshot)

    final_snapshot = snapshots[-1].model_dump(mode="json")
    print(json.dumps(final_snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
