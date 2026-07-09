# Shiploader Motion Simulation

Python MVP for a single ship loader multi-degree-of-freedom motion simulation.

The first delivery focuses on:

- uniform-speed motion axes
- ship loader geometry configuration
- forward kinematics key point calculation
- simulation time stepping
- stable state snapshots
- lightweight command/state API boundaries

Run tests:

```bash
pytest
```

Run the acceptance demo:

```bash
python examples/demo_multi_axis_motion.py
```

Run the 3D motion demo:

```bash
python examples/demo_3d_motion.py
```

Run a smoother 3D preview:

```bash
python examples/demo_3d_motion.py --quality fast --fps 30 --dt 0.033333 --steps 900
```

Run a prettier but heavier 3D preview:

```bash
python examples/demo_3d_motion.py --quality high --fps 20
```

Render one final 3D frame without opening a window:

```bash
python examples/demo_3d_motion.py --off-screen --screenshot work/shiploader_3d_demo.png
```

Run the API server:

```bash
uvicorn app.main:app --reload
```

Open the Web 3D visualization:

```text
http://127.0.0.1:8000/
```

Scene vessels and hatch counts are API-driven:

```bash
curl http://127.0.0.1:8000/api/scene
curl -X PUT http://127.0.0.1:8000/api/scene -H "Content-Type: application/json" -d @scene.json
```
