"""
NPC 触发路由层（task-3 实施 / 本 task 仅空骨架占位）。

干啥用（task-3 填后）：
- 接收 PersonaEvent dict，按 scene_type 路由到对应模板池
- 含场景定义：PR / 普通骑行（4 段位）/ 连骑高频 / 沉寂 / 极端数据 / 空状态 /
  跨时间镜像 / 错峰惊喜（共 7 大类 / 50+ 子场景）
- 决策算法：根据用户 stage（萌新 < 500km / 入门 500-3000 / 进阶 3000-8000 / 老登 >8000）
  + 场景上下文做模板选择

操作注意（ADR-009）：
- 不 import 业务 service / 只接受参数 dict
- 所有外部数据由调用方喂入

输入输出（task-3 填后）：
- 入：PersonaEvent dict
- 出：选中的 PersonaTemplate（或 None）

本文件 task-1 仅占位 / 真实现见 task-3。
"""
