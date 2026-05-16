"""
NPC 文案系统子模块（Persona Engine / ADR-009 第 2 个 agent 子工程）。

干啥用：
- 给业务模块（worker / endpoint）调 generate_persona_output(event) 返 NPC 文案
- "老登"人格层：用户上传 PR / 普通骑行 / 连骑 / 沉寂 / 极端数据 / 空状态等场景
  时，NPC 用半句话、圈内黑话、反向赞美、deadpan 风格说一句话
- 输入参数 dict + DB session / 不反向 import 业务模块 service

操作注意（ADR-009 + 宪法 § 7.2 硬约束 / 违反 = REJECT）：
- 本模块**不反向 import** 业务模块（user / activity / segment / notification 的 service 都禁）
- 只读 Activity / User ORM model + 写 persona_outputs / persona_feedback model
- agent 是叶子节点——业务模块依赖它，不反过来
- 任何子模块抛 unhandled exception → service 顶层 catch / 返 None / 不传染调用方事务
- 命名前缀守则：persona_* 表 / persona_engine_*.py 迁移 / test_persona_*.py 测试 /
  scripts/persona_*.py 脚本（让 find -name "*persona*" 一条命令列全资产）

数据流：
- 入：PersonaEvent dict（含 user_id / scene_type / activity context）+ DB session
- 出：Optional[str]（46 条固定模板之一渲染后的文案 / 或 None 表示该场景无文案）

模块结构（task-1 地基 / task-2~5 逐步填）：
- trigger_router.py：路由层（场景路由 / 选模板）— task-3 填
- template_lib.py：模板池（46 条精金文案 + 渲染）— task-2 填
- filters.py：后置过滤（反 pattern 检测 / 兜底降级）— task-3 填
- cache.py：去重 + 缓存（同场景同用户 N 小时不重复）— task-3 填
- service.py：顶层入口（编排 router → template → filter → cache）— task-3 主入口
- models.py：3 个 ORM（PersonaOutput / PersonaTemplate / PersonaFeedback）— task-1 已建

参考：docs/agent-rules/persona-constitution.md（Persona 宪法 v0.1 / 文案灵魂源）
"""
