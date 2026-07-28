# AGENTS.md

## 项目定位

本项目是黄骅 8,000 t/h SL15 装船机仿真系统，提供五轴运动、舱口网格安全定位、整船一键装载、Three.js 三维展示和可选 PLC 反馈同步。

## 运行与验证

```bash
python -m pip install -e .
python -m uvicorn app.main:app --reload
pytest -q
node --check app/web/app.js
```

浏览器入口为 `http://127.0.0.1:8000/`。提交前至少运行与改动相关的测试；修改状态机、路径或 API 时运行完整 `pytest -q`。

## 技术栈

- Python 3.10+、FastAPI、Pydantic。
- 进程内 `SimulationWorld`，不使用数据库。
- 原生 JavaScript、Three.js r160 和程序化 SL15 模型。
- 可选 `pylogix` PLC 反馈同步，默认禁用。

## 目录与约定

- `app/core/` 保存业务与仿真真值，前端不得自行推进装船状态或吨位。
- `app/models/` 保存 API/快照契约；新增字段优先保持向后兼容。
- `app/config/default_loading_plan.json` 是 P0 默认配载计划真值。
- `app/web/` 只通过 API 和快照驱动表现。
- `docs/` 保存现役产品、技术和运维合同；README 只保留入口摘要。
- 测试使用全局仿真单例时必须在前后复位场景和任务。

## 当前状态与边界

- 一键装船 P0 已在本地实现并通过自动化及浏览器验证，尚未据此声明已部署或真实现场验收。
- 默认流程为三轮十二批、`52,100,000 kg`，机械 `12×`、装载 `600×`、排水 14 秒。
- 任务和事件仅保存在进程内；服务重启不恢复。
- 本系统仅用于仿真，不得接管真实 PLC、配载、稳性或吃水决策。
- P1/P2（计划导入、持久化、真实秤重等）只有在明确需求下实施。
