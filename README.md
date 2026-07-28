# Shiploader Motion Simulation

黄骅 8,000 t/h 装船机多自由度仿真系统。项目以 FastAPI 维护权威仿真状态，以原生 JavaScript 和 Three.js 提供浏览器三维操作界面。

当前 P0 能力包括：

- SL15 五轴匀速运动、正运动学和稳定状态快照。
- 船舶、货舱、舱盖及 `10 × 8` 舱口网格场景。
- 单目标网格预览和六阶段安全路径任务。
- “华元503”三轮十二批一键装船，目标总量 `52,100 t`。
- 暂停、继续、终止、重置、幂等、联锁和结构化事件。
- 装载进度、活动舱高亮、计划完成度填充和煤流表现。
- 可选的 Allen-Bradley PLC 反馈同步；默认关闭。

> 一键装船仅用于仿真演示，不连接或控制真实 PLC，也不替代真实配载、稳性或吃水计算。

## 快速开始

要求 Python 3.10 或更高版本。

```bash
python -m pip install -e .
pytest -q
python -m uvicorn app.main:app --reload
```

打开：

```text
http://127.0.0.1:8000/
```

右侧“一键装船”使用默认演示倍率：

- 机械定位：`12×`
- 装载业务时间：`600×`
- 首轮排水：`50,400s → 14s`

完整本地演示约 4.5 分钟。吨位内部以整数千克累计，完成值严格为 `52,100,000 kg`。任务、事件和幂等映射仅保存在当前进程内，服务重启后不恢复。

## 主要 API

```text
GET  /api/state
POST /api/simulation/step|pause|resume|reset
GET  /api/scene
PUT  /api/scene

POST /api/path-plans/preview
POST /api/path-tasks
GET  /api/path-tasks/current

GET  /api/loading-plans/current
POST /api/loading-plans/{plan_id}/validate
POST /api/loading-tasks
GET  /api/loading-tasks/current
GET  /api/loading-tasks/{task_id}
POST /api/loading-tasks/{task_id}/pause|resume|cancel|reset
GET  /api/loading-tasks/{task_id}/events
```

活动整船任务持有设备控制权。此时公共路径创建、手动轴命令和手动启动皮带会返回结构化 `409` 错误。

## 项目结构

```text
app/
  api/                 FastAPI 依赖、命令服务和路由
  config/              装船机、场景、PLC 和默认配载计划
  core/                仿真、路径规划、装船编排和 PLC 同步
  models/              Pydantic 数据契约
  web/                 Three.js 页面与程序化 SL15 模型
docs/                  PRD、技术设计、部署和交接文档
examples/              Python/PyVista 离线演示
scripts/               PLC 启动和验收脚本
tests/                 单元、API、流程和视觉基线
```

## 其他演示

```bash
python examples/demo_multi_axis_motion.py
python examples/demo_3d_motion.py
python examples/demo_3d_motion.py --off-screen --screenshot work/shiploader_3d_demo.png
```

## PLC 反馈同步

PLC 集成默认关闭。Windows 联调入口：

```powershell
.\scripts\start_sim_with_plc.ps1 -PlcIp 10.60.97.40 -PlcSlot 0 -WebPort 8765
```

启用前应按 [SL15 PLC 实时同步部署说明](docs/SL15_PLC实时同步部署说明.md) 完成标签导入和测试控制器审查。状态接口：

```text
http://127.0.0.1:8765/api/plc/status
```

## 现役文档

- [当前开发交接](docs/开发交接任务清单.md)
- [一键装船 PRD](docs/一键装船全流程模拟_PRD.md)
- [一键装船技术实现](docs/一键装船全流程模拟_技术实现文档.md)
- [舱口网格路径规划 PRD](docs/装船机舱口网格目标点路径规划_PRD.md)
- [SL15 三维模型重设计 PRD](docs/黄骅8000装船机模型重设计_PRD.md)

更改公开 API、状态机、默认配载计划或演示倍率时，应同步相应 PRD/技术文档和自动化测试。
