"""sprint9_persona_cleanup：drop 3 张 persona_* 表（Persona Engine 整模块清 / Sprint 9 收尾）。

Persona Engine 2026-05-21 战略决定整模块清理（C 方案 = 前端 + 后端代码 + DB 表全清）。
本迁移完成 stage 3 = DB 层 drop 3 张 persona_* 表。stage 1 已 pg_dump 备份到
`docs/archive/persona-db-backup/2026-05-21-persona-tables.sql`（193+168+0 行 INSERT 含 FK）。

不动核心表（users / activities）/ 防火墙原则。
不删历史 migration 文件（persona_engine_init.py + persona_engine_seed.py 保留在 chain）
/ alembic chain 保留完整历史是 best practice。

drop 顺序（按反向 FK 依赖）：
1. persona_feedback（依赖 persona_outputs + users / 先删）
2. persona_templates（无 FK 依赖）
3. persona_outputs（被 persona_feedback 依赖但已删 / 含 user_id FK to users / activity_id FK to activities）

downgrade 不可逆：3 张表 + 193+168+0 行数据无法从代码层恢复。如未来真要恢复：
1. 先把本 migration 改成 downgrade 路径 / 重建 schema（参考 persona_engine_init.py upgrade()）
2. 从 archive psql restore 数据：psql -U velo -d velo < docs/archive/persona-db-backup/2026-05-21-persona-tables.sql

战略复盘见 docs/changelog.md 2026-05-20→21 段 + memory feedback_decoration_vs_guidance_velo_persona_lesson.md。

Revision ID: sprint9_persona_cleanup
Revises: sprint9_breakthrough_events
Create Date: 2026-05-21
"""

from alembic import op


revision = "sprint9_persona_cleanup"
down_revision = "sprint9_breakthrough_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """drop 3 张 persona_* 表（按反向 FK 依赖顺序）。"""

    # 1. persona_feedback（依赖 persona_outputs + users / 先删 / 0 行数据）
    op.drop_table("persona_feedback")

    # 2. persona_templates（无 FK 依赖 / 168 行模板已归档）
    op.drop_index(
        "ix_persona_templates_scene_active",
        table_name="persona_templates",
    )
    op.drop_table("persona_templates")

    # 3. persona_outputs（被 feedback 依赖但已删 / 含 user_id FK + activity_id FK / 193 行 NPC 输出已归档）
    op.drop_index(
        "ix_persona_outputs_user_scene_shown",
        table_name="persona_outputs",
    )
    op.drop_table("persona_outputs")


def downgrade() -> None:
    """不可逆：3 张表 + 361 行数据无法从代码层恢复。

    如未来真要恢复：
    1. 改本 migration 写 downgrade 重建 schema（参考 persona_engine_init.py upgrade()）
    2. 从 archive psql restore 数据：
       psql -U velo -d velo < docs/archive/persona-db-backup/2026-05-21-persona-tables.sql
    """
    raise NotImplementedError(
        "Persona Engine 整模块清理不可逆 / 数据已 pg_dump 归档 "
        "docs/archive/persona-db-backup/2026-05-21-persona-tables.sql / "
        "如需恢复请手工重建 schema + psql restore（见本文件 docstring）"
    )
