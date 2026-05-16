"""
NPC 模板池 + 渲染（task-2 实施 / 本 task 仅空骨架占位）。

干啥用（task-2 填后）：
- 加载 persona_templates 表 46+ 条精金文案（按 scene_type / segment 分类）
- 模板渲染：把 {distance} / {pr_delta} / {city} 等占位符填进文案
- 副线 cycle 扩 112 条新文案（Tim 拍 5 条金标尺 → 整组入库 → 下一场景）

操作注意（ADR-009 + 宪法 § 2.5 双标尺）：
- 不 import 业务 service / 只读 persona_templates 表
- 文案 ground truth = docs/agent-rules/persona-constitution.md / 不允许偏离

输入输出（task-2 填后）：
- 入：scene_type + segment + render_context dict
- 出：渲染后的 str（或 None）

本文件 task-1 仅占位 / 真实现见 task-2。
"""
