# 0.25 稳定化进度

按 Astra 的《DST-AI-AGENT 0.25 Stabilization Rescue》在 `stabilization/0.25` 分支处理。以下均以实机结果作为最终验收。

| 项目 | 当前状态 |
| --- | --- |
| explore coast / early-arrived | 已删除；移动终态停止自身 Locomotor 目标并结束客户端预览。待实机观察。 |
| 8～12 单位原生 `PushAction` | 已接入独立探针，可自动累计 10 次；尚无实机结果。 |
| HARVEST_TARGET / PICKUP_TARGET / FELL_TREE 连贯性 | 增加执行时间日志；现有执行路径仍需原生探针结果指导，尚未通过。 |
| COLLECT_NEARBY | 待原生 primitive 稳定后替换现有静态 GUID 区域收集。 |
| 路边资源 Lua 微策略 | 待原生 primitive 稳定后实现；现有 Python STOP 路径仍在。 |
| SafetyMode | 已加入 NORMAL、EVADE、RECOVER 与约 2 秒稳定退出条件；待实机测威胁 episode。 |
| 前两天沼泽 | 规划器、命令接收端和断桥本地逃跑拒绝已知沼泽路线；误入时 Lua 返回最近非沼泽位置。实际 pathfinder 轨迹仍需实机核对。 |
| A～E micro-benchmark | A 的自动探针已备；A～E 均待实机。 |

原生采摘基准：先由桥接端停止自主模式，待角色空闲；调用 `POST /native-benchmark/start`。威尔逊白天、安全、生命和饥饿均不低于 75 且背包有空间时，探针寻找 8～12 单位外可采的草。找到就连续提交原生动作，总共记录 10 次；找不到时状态为 `waiting_for_grass_8_to_12`，可人工移动至下一片草旁。读取 `GET /native-benchmark/status` 查看每次终态。服务端日志有 `[Wilson native]` 和 `[Wilson timeline]`。本轮要求核对自动接近、动作衔接和每次失败原因，不以 Python 单元测试代替实机结果。
