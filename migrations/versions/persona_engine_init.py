"""persona_engine_init：NPC 文案系统 3 张 persona_* 表（Persona Engine Sprint task-1）。

Persona Engine Sprint v0.1 地基迁移：建好"老登"NPC 文案系统的持久层。
不动核心表（users / activities / segments / notifications）/ 防火墙原则。

类比：给小区物业新加 3 本台账——
- persona_outputs = 老登发言流水（哪天对哪个住户说了啥）
- persona_templates = 老登的金句库（备选 46+ 条）
- persona_feedback = 住户对老登态度记录（v1.0+ 才真用）

字段 / 索引设计依据：
- text_snapshot：文案快照（v0.4 修 Claude A+B 共识 C1 / 避免 endpoint JOIN templates）
- (user_id, scene_type, shown_at) 索引：endpoint 主查询 "该用户某场景最近文案"
- (scene_type, active) 索引：选模板时按场景 + 启用过滤候选池
- 不加 UNIQUE：去重逻辑在 service 层（cache.py 时间窗内防重渲染）
- 不加 CHECK enum：reaction / scene_type 应用层枚举 / 防未来扩枚举锁死表
- tz-aware DateTime：CLAUDE.md 陷阱 #2 / 防 naive vs aware 比较 TypeError

防火墙红线（宪法 § 7 / handoff § 1）：
- 表名前缀 persona_*（一条命令列全资产）
- 迁移文件名 persona_engine_*.py
- 不修改既有任何核心表字段

Revision ID: persona_engine_init
Revises: sprint6_activity_city
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "persona_engine_init"
down_revision = "sprint6_activity_city"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建 3 张 persona_* 表 + 2 个查询索引。"""

    # ─── persona_outputs：NPC 文案发送台账 ───
    op.create_table(
        "persona_outputs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("scene_type", sa.String(32), nullable=False),
        sa.Column("template_id", sa.Integer, nullable=False),
        # 文案快照（v0.4 修 C1 / 避免 endpoint JOIN templates）
        sa.Column("text_snapshot", sa.Text, nullable=False),
        sa.Column(
            "shown_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        # ondelete="SET NULL"：activity 被删（用户删 / Strava webhook 删）时
        # 历史台账保留 + activity_id 置 NULL（防 PG NO ACTION 让删活动 500 / Codex C1）
        sa.Column(
            "activity_id",
            sa.Integer,
            sa.ForeignKey("activities.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_persona_outputs_user_scene_shown",
        "persona_outputs",
        ["user_id", "scene_type", "shown_at"],
    )

    # ─── persona_templates：NPC 模板池 ───
    op.create_table(
        "persona_templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scene_type", sa.String(32), nullable=False),
        sa.Column("segment", sa.String(32), nullable=True),
        sa.Column("template_text", sa.Text, nullable=False),
        sa.Column("weight", sa.Integer, server_default=sa.text("1")),
        sa.Column(
            "active",
            sa.Boolean,
            server_default=sa.text("true"),
        ),
    )
    op.create_index(
        "ix_persona_templates_scene_active",
        "persona_templates",
        ["scene_type", "active"],
    )

    # ─── persona_feedback：用户反馈占位（v1.0+ 才真用）───
    op.create_table(
        "persona_feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "output_id",
            sa.Integer,
            sa.ForeignKey("persona_outputs.id"),
            nullable=False,
        ),
        sa.Column("reaction", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """回滚：3 表全删（含索引自动随表删）。"""
    op.drop_table("persona_feedback")
    op.drop_index(
        "ix_persona_templates_scene_active",
        table_name="persona_templates",
    )
    op.drop_table("persona_templates")
    op.drop_index(
        "ix_persona_outputs_user_scene_shown",
        table_name="persona_outputs",
    )
    op.drop_table("persona_outputs")
