"""
赛段模块——"田径赛道 + 成绩册"。

如果 Activity 模块是"你今天跑了多远"（个人运动日志），
那 Segment 模块是"你在这条赛道上排第几"（竞技排行榜）。

赛段 = 一段固定路线（如"太原龙城大道上坡 3.2km"），由管理员设置。
成绩 = 用户骑过这段路的用时记录，由 Worker 自动匹配生成。

两张核心表：
- segments：赛道本身（起终点、参考路线、匹配容差）
- segment_efforts：每个用户在每条赛道上的成绩（用时、速度、功率）

模块内部文件分工：
- models.py：数据库表结构（Segment + SegmentEffort）
- matcher.py：GPS 精确匹配算法（纯函数，Task 4.3）
- service.py：业务逻辑（创建赛段、自动匹配、排行榜查询）
- router.py：API 路由（/api/segments/...）
- schemas.py：请求/响应格式

注意事项：
- 本模块依赖 User 模块（创建者）和 Activity 模块（成绩关联）
- 禁止被 User 或 Activity 模块反向依赖
- Worker（Task 3.6 第 11 步）会调用本模块的匹配函数
"""
