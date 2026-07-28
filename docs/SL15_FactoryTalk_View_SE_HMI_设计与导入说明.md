# SL15 FactoryTalk View SE HMI 设计与导入说明

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 日期 | 2026-07-28 |
| 适用软件 | FactoryTalk View Studio / View SE 10.0 |
| HMI 工程 | `plc_sl` |
| PLC 数据快捷方式 | `plc_sl` |
| 当前状态 | 已导入 B 主机工程，并完成在线只读验证 |

## 1. 交付范围

本次新增两张 `1920 × 1080` 的 FactoryTalk View SE 画面：

- `SL15_Overview`：运行总览、五轴实际位置、仿真状态、皮带状态、心跳、应答码和三类轴状态掩码。
- `SL15_Diagnostics`：通信诊断、心跳与应答、五轴故障码、运行/到位/故障掩码。

两张画面顶部均明确标注“只读监视·不向 PLC 写入控制命令”。本次 HMI 只读取现有 `SL15_HIL_*` 反馈标签，不包含启动、停止、复位或运动控制写入。

## 2. 文件清单

### 2.1 可重复导入源文件

- `docs/hmi/factorytalk-view-se/SL15_Overview.xml`
- `docs/hmi/factorytalk-view-se/SL15_Diagnostics.xml`
- `docs/hmi/factorytalk-view-se/BatchImport_SL15.xml`
- `docs/hmi/factorytalk-view-se/Gfx-SE11.xsd`
- `docs/hmi/factorytalk-view-se/DisplaysImport.txt`

推荐使用 XML 批量导入文件维护和迁移画面。XML 已通过 Rockwell `Gfx-SE11.xsd` 校验，并在 FactoryTalk View Studio 10.0 中实际导入成功。

### 2.2 原生 GFX 文件

- `docs/hmi/factorytalk-view-se/native/SL15_Overview.gfx`
- `docs/hmi/factorytalk-view-se/native/SL15_Diagnostics.gfx`

原生 `.gfx` 文件是从 B 主机已导入的 `plc_sl` 工程回收的兼容版本。不要在 HMI Server 正在运行或画面正在编辑时直接覆盖工程内 `.gfx` 文件；常规迁移优先使用 XML 导入向导。

### 2.3 在线验证截图

- `docs/hmi/factorytalk-view-se/screenshots/SL15_Overview_live_test.jpg`
- `docs/hmi/factorytalk-view-se/screenshots/SL15_Diagnostics_live_test.jpg`

## 3. 画面设计

### 3.1 运行总览

运行总览采用深色工业界面，信息层级如下：

1. 顶部状态条：PLC 连接、仿真运行、皮带运行、应用心跳。
2. 五轴卡片：大车行走、臂架回转、臂架俯仰、臂架伸缩、溜筒回转。
3. 运行数据：仿真时间、皮带速度、应答代码、最后错误码。
4. 状态掩码：运行、到位、故障，按 bit0 至 bit4 对应五个运动轴。

五轴顺序固定为：

| 索引 | 轴 | 单位 |
|---:|---|---|
| 0 | 大车行走 | m |
| 1 | 臂架回转 | deg |
| 2 | 臂架俯仰 | deg |
| 3 | 臂架伸缩 | m |
| 4 | 溜筒回转 | deg |

### 3.2 PLC 诊断

诊断画面显示：

- 应用心跳、应答序号、应答代码、仿真时间。
- 轴运行掩码、轴到位掩码、轴故障掩码。
- `AxisFaultCode[0]` 至 `AxisFaultCode[4]`。
- 最后错误码。

正常判断建议：

- `AppConnected = 1`。
- `AppHeartbeat` 持续递增。
- 无故障时 `AxisFaultMask = 0`，五个 `AxisFaultCode` 均为 `0`。
- 五轴全部到位时 `AxisAtTargetMask = 31`，即二进制 `11111`。

## 4. PLC 标签绑定

所有直接标签表达式采用：

```text
{[plc_sl]SL15_HIL_标签名}
```

| PLC 标签 | HMI 用途 |
|---|---|
| `SL15_HIL_AppHeartbeat` | 应用心跳 |
| `SL15_HIL_AckSeq` | 应答序号 |
| `SL15_HIL_AckCode` | 应答代码 |
| `SL15_HIL_AppConnected` | PLC/模拟器连接状态 |
| `SL15_HIL_SimRunning` | 仿真运行状态 |
| `SL15_HIL_SimTime_ms` | 仿真时间 |
| `SL15_HIL_AxisActual[0..4]` | 五轴实际位置 |
| `SL15_HIL_AxisRunningMask` | 五轴运行位掩码 |
| `SL15_HIL_AxisAtTargetMask` | 五轴到位位掩码 |
| `SL15_HIL_AxisFaultMask` | 五轴故障位掩码 |
| `SL15_HIL_AxisFaultCode[0..4]` | 五轴故障码 |
| `SL15_HIL_BeltRunning` | 皮带运行状态 |
| `SL15_HIL_BeltSpeed_mps` | 皮带速度 |
| `SL15_HIL_LastErrorCode` | 最后错误码 |

## 5. 在 FactoryTalk View Studio 中导入

1. 打开 View SE 工程 `plc_sl`。
2. 在工程树中展开“图形”，右键“画面”，选择“导入和导出”。
3. 选择“将图形信息导入画面”。
4. 根据现场备份策略选择是否先备份画面。
5. 选择“多画面批量导入文件”。
6. 选择 `BatchImport_SL15.xml`。
7. 首次导入选择“在画面上创建新对象”；更新已有画面选择“更新画面上的现有对象”。
8. 完成后检查 `DisplaysImport.txt`，两张画面都应显示“导入成功完成”。

B 主机本次使用的导入目录为：

```text
D:\SL15_HMI_Import\20260728
```

导入前的工程视觉备份位于：

```text
D:\FTView_Backups\plc_sl_visual_before_SL15_HMI_20260728_161847
```

## 6. 运行与集成

### 6.1 View Studio 单画面测试

打开目标画面后，点击工具栏“测试显示”按钮。进入测试后应能看到实时数值，不应出现 `####` 或 `?`。`####` 在编辑模式中属于占位显示。

在 View Studio 的单画面测试模式下，如果 HMI Server 未处于可执行显示命令的状态，导航按钮可能提示 `Display` 命令被忽略。这不影响标签读取；在已配置的 View SE Client 运行环境中，导航按钮使用：

```text
Display SL15_Overview
Display SL15_Diagnostics
```

### 6.2 接入现有导航

可在现有主画面中增加两个导航按钮，分别执行上述两个 `Display` 命令。是否把 `SL15_Overview` 设置为客户端启动画面，应在确认现有客户端导航结构后单独配置，本次未修改现有启动画面。

## 7. 现场验证记录

2026-07-28 在 B 主机 FactoryTalk View Studio 10.0 中完成在线测试：

- `PLC 已连接` 状态正常。
- 应用心跳从 `51687` 增长到 `51717`，证明实时刷新正常。
- 五轴实际值正常显示：`0.000、0.000、10.000、0.000、0.000`。
- 仿真停止、皮带停止，符合验证时的模拟程序状态。
- 运行掩码为 `0`，到位掩码为 `31`，故障掩码为 `0`。
- 五轴故障码均为 `0`，应答代码和最后错误码均为 `0`。
- 两张画面最终导入日志均为“导入成功完成”。

以上数值是验证时刻的快照，不是固定配置值。

## 8. 当前边界与后续扩展

当前模拟程序向 PLC 同步反馈数据，但没有经过安全评审的 HMI 控制命令标签合同。因此本次画面不写 PLC，这是有意保留的安全边界。

如果后续需要 HMI 发出启动、暂停、复位或轴运动命令，应另行设计 `SL15_HMI_*` 命令标签，至少包含：

- 命令请求序号与 PLC 应答序号。
- 操作权限、模式选择和控制权互锁。
- 急停、安全回路、限位、皮带与机构联锁。
- 命令超时、重复请求幂等和故障复位规则。
- 模拟程序、PLC 和 HMI 三方失联时的安全状态。

在上述合同和 PLC 联锁完成前，不应把现有只读画面改成直接写入 `SL15_HIL_*` 标签。
