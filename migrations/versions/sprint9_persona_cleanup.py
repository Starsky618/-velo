"""sprint9_persona_cleanup：drop 3 张 persona_* 表（Persona Engine 整模块清 / Sprint 9 收尾）。

Persona Engine 2026-05-21 战略决定整模块清理（C 方案 = 前端 + 后端代码 + DB 表全清）。
本迁移完成 stage 3 = DB 层 drop 3 张 persona_* 表。stage 1 已 pg_dump 备份到
`docs/archive/persona-db-backup/2026-05-21-persona-tables.sql`（193+168+0 = 361 条 INSERT
/ 含 schema CREATE TABLE + 数据 + FK ALTER / archive **自包含** / 直接 psql restore 可恢复）。

不动核心表（users / activities）/ 防火墙原则。
不删历史 migration 文件（persona_engine_init.py + persona_engine_seed.py 保留在 chain）
/ alembic chain 保留完整历史是 best practice。

drop 顺序（按反向 FK 依赖 / 三审验证 PG 行为）：
1. persona_feedback（有 DB-level FK：output_id → persona_outputs.id + user_id → users.id / 先删 child）
2. persona_templates（无 DB-level FK / persona_outputs.template_id 是普通整数列引用 templates.id
   但**没** sa.ForeignKey 约束 / PG 不阻塞 drop）
3. persona_outputs（被 feedback 依赖但已删 / 含 user_id FK to users + activity_id FK to activities
   / 这是 child 指向 parent / 删 child 不需要先解 FK）

downgrade 不可逆：3 张表 + 361 条数据无法从代码层恢复。如未来真要恢复：
1. **archive SQL 自包含 schema + FK + data**，直接 `psql -U velo -d velo < docs/archive/persona-db-backup/2026-05-21-persona-tables.sql` 即可还原表 + 数据
2. 然后 `alembic stamp` 到本 migration 之前的 revision（sprint9_breakthrough_events）保持版本号一致

战略复盘见 docs/changelog.md 2026-05-21 段 + memory feedback_decoration_vs_guidance_velo_persona_lesson.md。

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
    """drop 3 张 persona_* 表（按反向 FK 依赖顺序 / drop_index 冗余但沿用 init 风格）。"""

    # 1. persona_feedback（有 DB-level FK to persona_outputs + users / 先删 child / 0 行数据）
    op.drop_table("persona_feedback")

    # 2. persona_templates（templates.id 被 persona_outputs.template_id 引用但**无 sa.ForeignKey 约束**
    #    / PG 不阻塞 drop / 168 行模板已归档）
    op.drop_index(
        "ix_persona_templates_scene_active",
        table_name="persona_templates",
    )
    op.drop_table("persona_templates")

    # 3. persona_outputs（被 feedback 依赖但已删 / 含 user_id FK to users + activity_id FK to activities
    #    都是 child 指向 parent / 删 child 不需要先解 FK / 193 行 NPC 输出已归档）
    op.drop_index(
        "ix_persona_outputs_user_scene_shown",
        table_name="persona_outputs",
    )
    op.drop_table("persona_outputs")


def downgrade() -> None:
    """不可逆：3 张表 + 361 条数据无法从代码层恢复。

    archive SQL 自包含 schema + FK + data。如未来真要恢复：

        psql -U velo -d velo < docs/archive/persona-db-backup/2026-05-21-persona-tables.sql
        alembic stamp sprint9_breakthrough_events  # 把版本号退到本 migration 之前

    不需要先写 downgrade 重建 schema（archive 已含 CREATE TABLE）。
    """
    raise NotImplementedError(
        "Persona Engine 整模块清理不可逆 / 数据已 pg_dump 归档 "
        "docs/archive/persona-db-backup/2026-05-21-persona-tables.sql / "
        "如需恢复见本函数 docstring：psql restore + alembic stamp 两步"
    )
