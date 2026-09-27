# 0.25 稳定化进度

按 Astra 的《DST-AI-AGENT 0.25 Stabilization Rescue》在 `stabilization/0.25` 分支处理。以下均以实机结果作为最终验收。

| 项目 | 当前状态 |
| --- | --- |
| explore coast / early-arrived | 已删除；移动终态停止自身 Locomotor 目标并结束客户端预览。待实机观察。 |
| 8～12 单位原生 `PushAction` | 独立探针入口保留；自动生存不再触发该探针。 |
| HARVEST_TARGET / PICKUP_TARGET / FELL_TREE 连贯性 | 0.25.3 实机多次提交后约 0.03～0.1 秒立即失败，近处草也失败。0.25.4 改由客户端预览到位后按游戏动作按钮流程请求，服务端核对成功或失败；待实机验证。 |
| COLLECT_NEARBY | 待原生 primitive 稳定后替换现有静态 GUID 区域收集。 |
| 路边资源 Lua 微策略 | 待原生 primitive 稳定后实现；现有 Python STOP 路径仍在。 |
| SafetyMode | 已加入 NORMAL、EVADE、RECOVER 与约 2 秒稳定退出条件；待实机测威胁 episode。 |
| 前两天沼泽 | 规划器、命令接收端和断桥本地逃跑拒绝已知沼泽路线；误入时 Lua 返回最近非沼泽位置。实际 pathfinder 轨迹仍需实机核对。 |
| A～E micro-benchmark | 独立探针可运行；A～E 完整验收待实机。 |

0.25.1 实机日志表明：白天自主模式选中多株草后，普通 `PICK_TARGET` 多次在接近开始后的约 0.07 秒返回 `failed_approach`；目标因此冷却 20 秒，角色转去找树枝或探图。同场原生 `PushAction` 在约 8～12 单位外有 1 次完成并取得 1 份草。0.25.2 直接移除了普通动作的接近包装器，并缩短执行失败后的冷却，增加 4 单位内可用资源的优先级。用户观察采集时角色滑行，随后角色被海面种子卡住；0.25.2 日志中种子目标 `112097` 开始拾取后位置停在距目标约 5.6 单位，观测没有传递目标地形可通行字段。0.25.3 为原生动作增加客户端动作预览，将目标所在地形可通行性传给规划器，并在执行前重查；寻路结束后若持续 2.5 秒没有接近目标则放弃。游戏内结果尚待验证。

0.25.3 实机选中了草和地面树枝，但多次 `PICK_TARGET` / `PICKUP_TARGET` 在提交后约 0.03～0.1 秒返回 `failed_or_interrupted`，包括距角色约 1.3 单位的草。随后规划器按失败冷却跳过这些目标。查看本机 DST `PlayerController` 与 `Locomotor` 脚本后，0.25.4 将普通玩家动作改成客户端 `PreviewAction` 接近，到位后 `RemoteActionButton` 交给游戏正常的客户端请求流程；服务端在 `performaction` 事件绑定结果回调。独立原生探针保留为显式诊断入口，自动生存不再触发探针。待实机验证。

进入世界后普通自主模式自动启动。独立原生基准入口 `POST /native-benchmark/start` 仅供开发者在停止自主模式后隔离复现，结果可从 `GET /native-benchmark/status` 读取。
