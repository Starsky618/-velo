"""
AI 内容生成模块（v5 task-1.B.1 / 留接口架构 / 未来 v7+ 扩 RAG）。

干啥用：
- 调外部 LLM API（DeepSeek，OpenAI 兼容 SDK）给赛段写"活人感介绍"
- 写 segment_ai_drafts 表（v5 task-0.6 已建 / pending → human_edited → approved/rejected 状态机）
- admin H5 触发后通过 RQ async 跑（admin endpoint 不阻塞 / 单次 LLM 调用 3-8s）

操作注意（ADR-009 边界硬约束）：
- 本模块**不反向 import** 业务模块（segment / activity / user 的 service 都禁）
- 只读 Segment ORM model + 写 SegmentAiDraft model + 通过参数 dict 输入
- agent 是叶子节点 —— 业务模块依赖它，不反过来

数据流：
- 入：segment_id (admin enqueue) → 查 Segment props → 喂 prompt 模板
- 出：DeepSeek 返 50-100 字草稿 → UPSERT segment_ai_drafts (segment_id UNIQUE) → 状态 'pending'
- 已存在 + status='pending' 才覆盖（不覆盖人工编辑）

未来扩展（v7+）：
- 加 RAG 向量检索本地骑友 UGC 给 prompt 注入语境
- 此模块为入口，新增 retrieval.py / vectordb.py 等不影响现有 segment_writer.py 接口

子工程地图（ADR-009 / agent 模块下并列子目录 / 都是叶子节点）：
- segment AI 草稿：本目录 segment_writer.py + tasks.py（赛段 AI 介绍）
- Persona Engine：app/agent/persona/（NPC 文案系统 / Persona Engine Sprint task-1 起）
  - 文案灵魂源：docs/agent-rules/persona-constitution.md
  - 同 ADR-009 边界：persona 子目录任何文件**不反向 import** 业务 service
  - 失败隔离：persona service 顶层 catch / 返 None / 用 SAVEPOINT 不传染调用方事务
"""
