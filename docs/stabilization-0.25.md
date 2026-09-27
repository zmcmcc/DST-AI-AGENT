# 0.25 稳定化进度

按 Astra 的《DST-AI-AGENT 0.25 Stabilization Rescue》在 `stabilization/0.25` 分支处理。以下均以实机结果作为最终验收。

| 项目 | 当前状态 |
| --- | --- |
| explore coast / early-arrived | 已删除；移动终态停止自身 Locomotor 目标并结束客户端预览。待实机观察。 |
| 8～12 单位原生 `PushAction` | 已接入独立探针，可自动累计 10 次；尚无实机结果。 |
| HARVEST_TARGET / PICKUP_TARGET / FELL_TREE 连贯性 | 0.25.1 实机有 1 次 8～12 单位原生采摘成功；普通动作的接近包装器多次立刻 `failed_approach`。0.25.2 已将这三类和区域收集改为直接提交原生目标动作，尚待实机核对。 |
| COLLECT_NEARBY | 待原生 primitive 稳定后替换现有静态 GUID 区域收集。 |
| 路边资源 Lua 微策略 | 待原生 primitive 稳定后实现；现有 Python STOP 路径仍在。 |
| SafetyMode | 已加入 NORMAL、EVADE、RECOVER 与约 2 秒稳定退出条件；待实机测威胁 episode。 |
| 前两天沼泽 | 规划器、命令接收端和断桥本地逃跑拒绝已知沼泽路线；误入时 Lua 返回最近非沼泽位置。实际 pathfinder 轨迹仍需实机核对。 |
| A～E micro-benchmark | A 的自动探针已备；A～E 均待实机。 |

0.25.1 实机日志表明：白天自主模式选中多株草后，普通 `PICK_TARGET` 多次在接近开始后的约 0.07 秒返回 `failed_approach`；目标因此冷却 20 秒，角色转去找树枝或探图。同场原生 `PushAction` 在约 8～12 单位外有 1 次完成并取得 1 份草。0.25.2 直接移除了普通动作的接近包装器，并缩短执行失败后的冷却，增加 4 单位内可用资源的优先级。游戏内结果尚待验证。

进入世界后普通自主模式自动启动。它选中白天、8～12 单位外、安全的草时，桥接端自动将这次采摘记入原生动作基准，最多累计 10 次；其他行动照常进行。`GET /native-benchmark/status` 返回逐次终态，服务端日志有 `[Wilson native]` 和 `[Wilson timeline]`。独立基准入口 `POST /native-benchmark/start` 仍供开发者在停止自主模式后单独隔离复现。
