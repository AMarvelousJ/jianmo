# 堆取料机仿真程序

第一阶段实现独立的机器运动仿真：21 台设备，左侧 7 台堆料角色、右侧 14 台取料角色；支持行走、回转、俯仰、斗轮、皮带及客户端控制租约。Unity 负责交互与表现，Python 保存权威状态。

## 启动

在本目录安装 `uv pip install --python ../.venv/Scripts/python.exe -e ".[test]"`，然后执行：

```powershell
.\scripts\start_backend.ps1
```

默认地址 `http://127.0.0.1:8001`，接口文档 `/docs`。仅监听本机，单进程单 worker。也可以使用 `python -m uvicorn yard_motion.api:app --host 127.0.0.1 --port 8001`。

## Unity 操作

打开现役 Demo 场景进入 Play Mode，点击屏幕中央的“堆场控制”。选择 ST/RC 设备、获取控制权后，输入三轴目标或按住正反向按钮。斗轮和皮带独立设置速度并启停。普通停止减速，急停立即停止并锁定，复位恢复初始姿态且不解除急停。

切换选机只停止原设备 jog；其他运动继续。退出、断线后租约超时触发减速停机，停稳后释放。重连不续跑。后端重启恢复初始状态。

## 参数与边界

`config/machines.json` 为版本化演示配置，轨道与摆位来自两份场景核对；速度、加减速度、角度范围和 1 场景单位/米均为演示参数，不是现场测量。机械几何缩放 0.455 与行走映射独立。

`config/material.json` 与 `config/geometry.json` 属第二阶段（煤堆与堆取料过程）：物料网格、账本、煤料演示参数与作业区候选；几何标定（卸料点、斗轮包络）版本化，行程候选为未应用提案。手动物料堆料作业已实现，取料、自动作业、区域互斥与存档恢复按工单推进。

碰撞保护与真实设备控制仍不在范围内；运行姿态与物料状态仅保存在内存。

## 验证

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

需求和规格见 `docs/`；运行联通及验收证据见工作区 `outputs/yard-machine-motion/`。自动测试与实际 Unity 验收结果分开记录。
