# 港区设备仿真后端

本仓库包含两个独立的 Python 服务：`ZCJ/` 是装船机仿真，`DQLJ/` 是堆取料机仿真。Unity 客户端在独立的 [Unity 仓库](https://github.com/AMarvelousJ/Unity)；两个仓库均需访问权限。

## Windows 首次安装

需要 Python 3.10 或以上版本。克隆本仓库，在仓库根目录打开 PowerShell，创建独立虚拟环境并安装两个服务：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ./ZCJ -e ./DQLJ
```

如果 `py` 不可用，使用已安装的 Python 3 解释器执行 `-m venv .venv`。环境不会随仓库提供。安装可能需要下载较大的科学计算依赖。

## 启动服务

以下命令从本仓库根目录执行，分别在独立 PowerShell 窗口运行；按 Ctrl+C 停止。启动前确认相应端口未被其他程序占用。

装船机，端口 8000：

```powershell
cd ZCJ
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

视频预览堆取料机，端口 8002：

```powershell
cd DQLJ
..\.venv\Scripts\python.exe -m uvicorn yard_motion.preview:create_preview_app --factory --host 127.0.0.1 --port 8002
```

真实尺度预览使用同一个 8002 端口，不能与视频预览同时运行。停止前一个服务后，在 `DQLJ` 目录启动：

```powershell
..\.venv\Scripts\python.exe -m uvicorn yard_motion.preview:create_real_scale_preview_app --factory --host 127.0.0.1 --port 8002
```

DQLJ 原场景独立服务使用 `yard_motion.api:app`，默认端口 8001；详细说明见 [DQLJ README](DQLJ/README.md)。服务的数据和功能边界各不相同，不要混用。

启动后可在浏览器检查 `http://127.0.0.1:8000/health`、`http://127.0.0.1:8002/api/machines` 和对应 `/api/state`。Unity 中还需要在运行界面的“服务连接”面板分别启用连接，进入 Play 后默认关闭。

更多信息见 [ZCJ README](ZCJ/README.md) 和 [DQLJ README](DQLJ/README.md)。该项目用于仿真，不用于真实设备控制或现场安全决策。
