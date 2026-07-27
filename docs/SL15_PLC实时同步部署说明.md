# SL15 模拟程序与 PLC 实时同步部署说明

版本：1.0  
日期：2026-07-27

## 1. 本期目标

主机 B 运行 SL15 模拟程序后，以 100ms 周期将五轴位置、运行状态、到位状态、皮带状态、仿真时间和软件心跳写入测试 PLC `10.60.97.40`。

昨天建立的 66 个 `SL15_IF_*` P0 标签继续保持 `External Access = Read Only`，用于 PLC 状态监视和目标 PLC 身份校验。本期新增 14 个 `SL15_HIL_*` 反馈标签，全部为 Controller Scope、Standard、`External Access = Read/Write`，专门承载模拟软件到 PLC 的数据，避免放开安全和控制标签的外部写权限。

## 2. 五轴数组顺序

| 索引 | 模拟轴 | 单位 |
|---:|---|---|
| 0 | `travel` | m |
| 1 | `slew` | deg |
| 2 | `boom_luff` | deg |
| 3 | `boom_extension` | m |
| 4 | `chute_rotate` | deg |

## 3. 新增反馈标签

| 标签 | 类型 | 运行含义 |
|---|---|---|
| `SL15_HIL_AppHeartbeat` | DINT | 软件每秒递增 |
| `SL15_HIL_AckSeq` | DINT | 命令确认序号，本期固定 0 |
| `SL15_HIL_AckCode` | DINT | 命令确认结果，本期固定 0 |
| `SL15_HIL_AppConnected` | BOOL | 最近一次批量写入成功 |
| `SL15_HIL_SimRunning` | BOOL | 仿真数据在 0.5 秒内持续更新 |
| `SL15_HIL_SimTime_ms` | DINT | 仿真时间，毫秒 |
| `SL15_HIL_AxisActual` | REAL[5] | 五轴实际位置 |
| `SL15_HIL_AxisRunningMask` | DINT | 五轴运行位掩码 |
| `SL15_HIL_AxisAtTargetMask` | DINT | 五轴到位位掩码 |
| `SL15_HIL_AxisFaultMask` | DINT | 五轴故障位掩码 |
| `SL15_HIL_AxisFaultCode` | DINT[5] | 五轴故障码 |
| `SL15_HIL_BeltRunning` | BOOL | 皮带运行反馈 |
| `SL15_HIL_BeltSpeed_mps` | REAL | 皮带速度 |
| `SL15_HIL_LastErrorCode` | DINT | 最近接口错误码 |

RSLogix v20.05 导入文件：`work/SL15_P1_feedback_tags_import_v20.csv`。

## 4. 运行配置

程序默认关闭 PLC 写入。主机 B 使用以下命令启动：

```powershell
cd D:\SL_plc\jianmo
.\scripts\start_sim_with_plc.ps1 -PlcIp 10.60.97.40 -PlcSlot 0 -WebPort 8765
```

状态接口：

```text
GET http://127.0.0.1:8765/api/plc/status
```

`connected=true`、`successful_cycles` 持续递增且 `last_error=null` 表示通讯正常。

## 5. 运行保护

- 启动前读取 `SL15_IF_Version` 和 `SL15_IF_PLCHeartbeat`，确认目标 PLC 中存在 SL15 P0 标记标签。
- 单一后台线程持有 PLC 连接，不在每个仿真周期反复建立连接。
- 批量写入失败后关闭连接，2 秒后自动重连，只保留最新仿真快照。
- 仿真快照超过 0.5 秒没有更新时，将 `SL15_HIL_SimRunning` 写为 0。
- 程序正常退出时尝试将 `SL15_HIL_AppConnected` 和 `SL15_HIL_SimRunning` 清零。
- PLC 通讯失败不阻塞仿真 API，也不向运动轴注入控制命令。

## 6. 验收步骤

1. 在 RSLogix 中离线导入 14 个反馈标签，确认无错误和警告。
2. 保存新的 ACD 工作副本。
3. 现场设备停机且确认安全后，再下载至测试 PLC。
4. PLC 恢复 `Remote Run` 后启动主机 B 模拟程序。
5. 检查 `/api/plc/status` 为已连接。
6. 在模型中移动大车、回转、俯仰、伸缩和溜筒，确认 `SL15_HIL_AxisActual[0..4]` 对应变化。
7. 确认 `SL15_HIL_AppHeartbeat` 每秒递增，`SL15_HIL_SimTime_ms` 随仿真推进。
8. 暂停或关闭浏览器仿真步进，确认 `SL15_HIL_SimRunning` 在 0.5 秒后变为 0。
