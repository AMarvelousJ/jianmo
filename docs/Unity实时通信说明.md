# Unity 实时通信说明

## 当前连接方式

Python FastAPI 是仿真状态的唯一真值源，Unity 通过 HTTP/JSON 读取状态并显示：

1. Unity 进入 Play 模式后访问 `/health`。
2. Unity 注册 `/api/simulation/clock/clients/{client_id}`，后端开始以 `0.1s` 步长推进。
3. Unity 每 `0.1s` 读取 `/api/state`，把五轴状态平滑应用到模型。
4. Unity 每秒续约时钟客户端；退出 Play 模式时释放客户端。
5. 一键装船、暂停、恢复、终止和舱盖操作仍通过现有 REST API 下发。

存在活动 Unity 客户端时，旧版浏览器发来的 `/api/simulation/step` 只读取当前状态，
不会重复推进仿真。

## 启动

在 PowerShell 中运行：

```powershell
cd D:\3D\Python\jianmo
.\scripts\start_unity_backend.ps1
```

也可以前台启动，方便查看日志：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

确认以下地址返回正常：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/api/simulation/clock
```

Unity 的 `Assets/Shiploader/Config/SL15BackendConfig.asset` 已指向
`http://127.0.0.1:8000`。打开 `SL15_Demo` 场景并进入 Play 模式即可连接。

`SL15_Demo` 使用后端默认船舶和舱口坐标，适合联动仿真。
`SL15_VideoPreview` 是放大后的视觉校准场景，不用于验证落料点坐标。

## 联通判定

Game 界面右侧应显示 `FastAPI：已连接`。也可以读取：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/simulation/clock
```

Play 模式下应看到 `active_clients` 大于零且 `running` 为 `true`。
