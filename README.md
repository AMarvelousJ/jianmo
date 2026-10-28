# 港区设备仿真后端工作区

本仓库按设备类型存放 Python 仿真程序：

| 目录 | 内容 | 当前状态 |
| --- | --- | --- |
| [`ZCJ/`](ZCJ/) | 现有 SL15 装船机 FastAPI 仿真服务、Three.js 页面、配置、文档与测试 | 已实现；从该目录启动 |
| [`DQLJ/`](DQLJ/) | 堆取料机 Python 仿真程序的预留位置 | 尚未建立仿真程序 |

运行现有装船机后端：

```powershell
cd D:\3D\Python\jianmo\ZCJ
python -m pip install -e .
python -m uvicorn app.main:app --reload
```

浏览器入口为 `http://127.0.0.1:8000/`。详细功能、API 和测试命令见 [`ZCJ/README.md`](ZCJ/README.md)。仓库根目录的 `.venv` 是现有本地虚拟环境；`ZCJ/scripts` 也支持使用 `ZCJ/.venv`。`DQLJ` 的启动方式将在其程序建立后确定。
