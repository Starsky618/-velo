"""
骑行活动模块——"运动记录本"。

如果 User 模块是"住户档案"（管谁住在这里），
那 Activity 模块就是"每次骑行的详细日志"——
记录你每次骑了多远、多快、爬了多少坡、心率多少、功率多少。

每上传一个 GPX 文件，就会新建一条 Activity 记录（状态为 pending），
然后异步解析 GPX → 提取轨迹点 → 计算统计数据 → 状态变为 completed。

模块内部文件分工：
- models.py：定义数据库表结构（Activity 主表 + Trackpoint 轨迹点表）
- gpx_parser.py：GPX 文件解析器（Task 3.2）
- service.py：业务逻辑（Task 3.5-3.7）
- router.py：API 路由（Task 3.5-3.7）
- schemas.py：请求/响应格式（Task 3.5-3.7）

注意事项：
- 本模块依赖 User 模块（每条记录关联一个用户）
- Segment 模块会依赖本模块（读取轨迹做赛段匹配）
- 禁止反向依赖：本模块不得 import Segment 模块的任何代码
"""
