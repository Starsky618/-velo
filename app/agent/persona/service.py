"""
NPC 文案系统顶层入口（task-3 实施 / 本 task 仅空骨架占位）。

干啥用（task-3 填后）：
- 业务模块（worker / endpoint）唯一调用入口：generate_persona_output(event, db)
- 编排：trigger_router → template_lib → filters → cache → 写 persona_outputs → 返 str
- 顶层 catch any Exception → 返 None / 不传染调用方事务（宪法 § 7.2 失败隔离）

操作注意（ADR-009 + 宪法 § 7.2 + CLAUDE.md 陷阱 #13）：
- 内层失败用 db.begin_nested() SAVEPOINT 隔离
- 不抛错给调用方 / 失败静默返 None
- worker hook 调用方需自己再外层 SAVEPOINT（双层兜底）

输入输出（task-3 填后）：
- 入：PersonaEvent dict + Session
- 出：Optional[str]（NPC 文案 / 或 None）

本文件 task-1 仅占位 / 真实现见 task-3。
"""
