"""
NPC 去重 + 缓存（task-3 实施 / 本 task 仅空骨架占位）。

干啥用（task-3 填后）：
- 同用户 / 同场景 N 小时内不重复同一文案（用户体验防呆）
- 查 persona_outputs 表近期记录 / 排除已用过的 template_id
- 命中缓存返历史 / 未命中走 trigger_router 重新生成

操作注意：
- 只读写 persona_outputs / 不污染其他表
- 缓存 key 设计：(user_id, scene_type, window_hours)

输入输出（task-3 填后）：
- 入：user_id + scene_type + window_hours
- 出：近期 used template_id 列表（去重排除集）

本文件 task-1 仅占位 / 真实现见 task-3。
"""
