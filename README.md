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

Run with SL15 PLC feedback synchronization on Windows:

```powershell
.\scripts\start_sim_with_plc.ps1 -PlcIp 10.60.97.40 -PlcSlot 0 -WebPort 8765
```

The PLC integration is disabled by default. Before enabling it, import the 14
`SL15_HIL_*` feedback tags from
`work/SL15_P1_feedback_tags_import_v20.csv` and download the reviewed project
to the test controller. Check the live connection state at:

```text
http://127.0.0.1:8765/api/plc/status
```

Scene vessels and hatch counts are API-driven:

```bash
curl http://127.0.0.1:8000/api/scene
curl -X PUT http://127.0.0.1:8000/api/scene -H "Content-Type: application/json" -d @scene.json
```
