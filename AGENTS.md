# AGENTS.md

## 项目定位

本目录是港区设备 Python 仿真后端工作区，包含两套已实现的服务：

- `ZCJ/`：黄骅 8,000 t/h SL15 装船机仿真，提供五轴运动、舱口网格安全定位、整船一键装载、Three.js 展示和可选 PLC 反馈同步。
- `DQLJ/`：堆取料机仿真，包含机器运动、原场景物料作业，以及独立的视频预览 RC01 取料试验。三者的配置、库存与能力不能混用。
- Unity 工程位于工作区 `D:\3D\Unity`，不是本 Python 仓库的子目录。跨工程修改时先读取目标目录适用的指令。

本文件适用于 `Python/jianmo/` 及其子目录；以下跨工程说明用于约束联调。执行前核对实际代码、配置、规格和验证记录，历史摘要及 README 不能替代当前实现。根 README 仍含 DQLJ 未实现的旧描述，`DQLJ/README.md` 主要描述原场景路线，不能直接套用到视频预览。

## 运行与验证

以下 PowerShell 命令从 `D:\3D\Python\jianmo` 开始。优先使用现有共享 `.venv\Scripts\python.exe`，不要依赖 WindowsApps 的 Python 占位程序。缺少依赖时才安装相应子项目，不随意重建环境或升级无关依赖。

装船机服务与验证：

```powershell
cd ZCJ
..\.venv\Scripts\python.exe -m pip install -e .
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
..\.venv\Scripts\python.exe -m pytest -q
node --check app/web/app.js
```

堆取料机原场景服务与验证：

```powershell
cd DQLJ
..\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\scripts\start_backend.ps1
..\.venv\Scripts\python.exe -m pytest -q
```

视频预览服务（同样在 `DQLJ/` 执行）：

```powershell
.\start-video-preview.ps1
# 前台启动的等效命令，8002 已有正确服务时不要重复运行：
..\.venv\Scripts\python.exe -m uvicorn yard_motion.preview:create_preview_app --factory --host 127.0.0.1 --port 8002
```

| 路线 | 地址 | 入口与配置 |
| --- | --- | --- |
| ZCJ 装船机 | `http://127.0.0.1:8000` | `app.main:app`；浏览器入口 `/` |
| DQLJ 原场景 | `http://127.0.0.1:8001` | `yard_motion.api:app`；`config/machines.json` |
| DQLJ 视频预览 | `http://127.0.0.1:8002` | `yard_motion.preview:create_preview_app`；`yard-video-preview-v3` |

- DQLJ 使用本机单进程、单 worker；进程内真值不能由多个 worker 各自维护。
- 启动前核对监听进程、`GET /api/machines` 的配置版本和 `GET /api/state` 的能力、运动与控制权状态。端口可连接不代表服务正确。
- 不接管用户正在使用的服务、不抢控制权、不自动终止活跃设备进程。测试使用独立实例和输出目录；预览测试必须沿用 v3 工厂，可用独立端口（既有探针为 18002）。
- `start-video-preview.ps1` 会核对配置与能力；升级旧预览进程前必须全部停稳且无控制权，不能绕过脚本保护。
- `DQLJ_BACKEND_URL` 是 Unity 客户端地址覆盖变量；只对指定测试子进程设置，不修改用户全局环境或源场景地址。
- Unity 的 8000/8002 连接开关每次 Play 默认关闭，由用户分别启用；断开、重连后重新取得控制权，不自动续跑。

## 技术栈

- Python 3.10+、FastAPI、Pydantic。
- ZCJ 使用进程内 `SimulationWorld`，DQLJ 使用 `World` / `PreviewWorld`；当前不使用数据库。
- ZCJ 浏览器使用原生 JavaScript、Three.js r160 和程序化 SL15 模型；Unity 负责跨工程三维联调。
- 可选 `pylogix` PLC 反馈同步，默认禁用。

## 目录与约定

- `ZCJ/app/core/` 保存业务与仿真真值，前端不得自行推进装船状态或吨位。
- `ZCJ/app/models/` 保存 API/快照契约；新增字段优先保持向后兼容。
- `ZCJ/app/config/default_loading_plan.json` 是 P0 默认配载计划真值。
- `ZCJ/app/web/` 只通过 API 和快照驱动表现。
- `ZCJ/docs/` 保存现役产品、技术和运维合同；README 只保留入口摘要。
- 测试使用全局仿真单例时必须在前后复位场景和任务。

DQLJ 主要入口与职责：

- `yard_motion/api.py`：HTTP 命令、控制租约和快照契约；`world.py` / `motion.py`：权威步进和机器运动。
- `material.py`、`cutting.py`、`jobs.py`、`geometry.py`、`persistence.py`：原场景物料、作业、几何和存档。
- `preview.py`：视频预览工厂及接口隔离；原场景 `start_job`、`reset_material` 等操作不能用于预览试验。
- `reclaim_pilot.py`：RC01 独立测试煤堆、实际切削、轮体/臂架煤面保护和 m³ 账本。
- `auto_reclaim.py` / `layer_coverage.py`：RC01 自动取料调度、分层库存及覆盖报告。
- `config/`：版本化设备、物料与几何参数；`docs/` / `GLOSSARY.md`：契约和术语；`tests/`：各能力验证。
- 需求与工单在工作区 `.scratch/`，验收证据在工作区 `outputs/`，均相对于 `D:\3D`，不在 Python 仓库内。

## 数据与控制契约

- Python 保存姿态、煤堆和账本真值；Unity/浏览器通过命令和快照表现，不自行积分扣煤量或推进任务。
- 命令沿用控制租约、顺序与幂等校验；机器运动、轮带试转、物料作业和自动任务必须明确区分。
- 原场景物料已有演示密度、吨位及存档接口；RC01 预览试验只计 m³，禁止将原场景演示密度当作已确认密度引入。
- 原场景默认存档 `DQLJ/data/material-snapshot.json`，可用 `DQLJ_SNAPSHOT_PATH` 覆盖；测试不得写用户存档。损坏档保留证据并验证备份，不能静默清空库存。
- 预览工厂使用 `snapshot_path=None`，RC01 试验不承诺服务重启后恢复煤堆或自动任务；不得套用原场景存档语义。
- 快照应保持版本一致，Unity 先应用同版煤面再应用 RC01 姿态，不能将旧煤面与新姿态混合插值。
- 字段缺失、JSON `null`、对象和数组是不同输入。Newtonsoft 的 JSON `null` 是 `JValue`，访问子字段前先确认 `JObject` / `JArray`，不能仅依赖 `?.`。
- GUI 绘制不得因正常空状态中断 GUILayout 配对；新增面板至少验证未初始化、运行中及报告已生成的显示状态。

## Unity 联调与取料边界

- 本轮主要场景为 `Unity/Assets/Shiploader/Scenes/SL15_VideoPreview.unity`。保留现有 7 台堆料机、14 台取料机的编号、位置、外形和已有修改。
- `SL15_Demo.unity` 是原场景，禁止为预览需求直接重建或覆盖。只改运行时组件即可实现的功能，不重生成场景、模型和煤堆。
- 堆料机尾部斜传送带只随整机行走；取料机下部中央溜槽不随上部回转。保持已验收的运动、煤流与启停行为。
- RC01 试验煤堆为 0.5 m 网格柱体；体积由实际柱高扣减乘单元面积累计，剩余库存与累计取量必须守恒，禁止用扫过面积或计划量冒充实际取量。
- 斗轮有效齿/斗作用区域接触可切煤，且轮、带运行、控制权及任务状态有效时才扣煤。离开煤堆、停轮、停带、停止、急停或控制权失效必须停止扣减。
- 保留现有完整轮体和臂架煤面保护；浅层齿/斗切削不允许演变成轮体、机身或臂架埋入煤堆。规划路径与执行步进都检查保护，不通过放宽机械限位绕过阻挡。
- 恢复测试煤堆前停稳并安全退出；恢复清零试验累计量且使旧计划失效。
- 当前 `rc01-auto-layers-v1` 支持单带、两带往复与有限两层演示，两层模式每层最多三带。带数预算完成不代表整层或全堆取净。
- 下层仅切当前已露出柱体，上层残煤仍参与碰撞保护；更低未规划煤量单独报告。层覆盖按实际库存计算，不按路径覆盖面积判断。
- `coverage_report.settled=true` 表示停止时冻结报告；后续手动取料改变当前库存，不能改写旧任务结算。报告版本与当前库存版本需明确区分。
- 暂停、断连或手动接管后显式重新规划并开始；当前未实现断点续作。复杂滑坡、真实颗粒、扬尘、贴地取净、全场调度与工业控制需另行确认范围。

## 变更与验证要求

- 修改前读取实际代码、相关场景/配置和已有证据；先说明数据表示、作用区域、计量方法及验收方式，再推进新的物料能力。用户已批准的范围无需重复确认。
- 保留用户现有未提交修改。`Python/jianmo` 和 `Unity` 是独立 Git 仓库，`D:\3D` 不是共同 Git 根；限定差异和暂存路径，不执行整库覆盖、清理或回滚。
- Python 功能修改先跑相关测试；涉及状态机、路径、几何、扣量或 API 契约时，再跑受影响子项目的完整测试。纯文档修改检查路径、命令和事实即可。
- DQLJ 优先通过公开命令 → 实际步进 → 快照验证，不用 mock 自有几何/物料来代替真实守恒、碰撞与联锁验证。
- 取料验收覆盖：计划无副作用、实际扣量、守恒、层底、煤面保护、停轮/停带/急停/失控零扣减、过期计划、恢复清零及未覆盖残煤。涉及换层时额外核对露出柱体限制和换层阶段零扣煤。
- Unity 改动在独立测试工程验证编译和必要的 Play/GUI 行为，避免与主编辑器争用工程。既有测试工程为 `outputs/yard-machine-reference-20261003/preview-build`；先确认没有其他任务使用。
- Unity 启动器返回成功不等于编译或 Play 成功；核对最终日志、探针结果及进程完成状态。相机截图不能替代真实 OnGUI 测试。
- 验证记录保存运行命令、测试结果、配置/能力版本、日志、必要截图及场景哈希；明确区分代码实现、自动测试、Unity 联通和用户实测。
- 相关证据：`outputs/stage2-reclaimer-flow-20261005/`、`outputs/stage2-stacker-flow-20261003/`、`outputs/stage4-rc01-layers-20261005/`、`outputs/stage4-ui-null-report-fix-20261006/`。查最新证据，不把历史通过数当作当前提交结果。

## ZCJ 已有状态与仿真边界

- 一键装船 P0 已在本地实现并通过自动化及浏览器验证，尚未据此声明已部署或真实现场验收。
- 默认流程为三轮十二批、`52,100,000 kg`，机械 `12×`、装载 `600×`、排水 14 秒。
- 任务和事件仅保存在进程内；服务重启不恢复。
- 本系统仅用于仿真，不得接管真实 PLC、配载、稳性或吃水决策。
- P1/P2（计划导入、持久化、真实秤重等）只有在明确需求下实施。
