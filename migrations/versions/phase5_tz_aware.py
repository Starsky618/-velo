"""第 5 期 Sprint 0 task 0.1：12 列 DateTime → timezone=True。

为什么 12 列合一份迁移：
    所有列都属同一性质改动（naive → tz-aware UTC），合并迁移降低版本管理成本。
    不影响业务逻辑（值域不变，只加时区元数据）。

陷阱 #7（Alembic alter_column 类型转换）：
    naive 改 tz-aware 必须 postgresql_using="<col> AT TIME ZONE 'UTC'"
    否则 PG 会报 "column cannot be cast automatically"。
    含义：把现有 naive 值视为 UTC，加上 +00 时区标记。

为什么必须先做（Sprint 0 根任务）：
    Sprint 1+ 业务代码（§3.3 power_curve / §3.4 progress detector / §3.6 看他人主页）
    假设 DB DateTime 列已 tz-aware，未迁前直接跑会触发陷阱 #2 naive vs aware TypeError。

⚠️ **单向迁移**（task-0.1 双审 Important 4 修复）：
    downgrade 把 DB 列改回 naive，但 v5 期 Python 代码已统一 datetime.now(timezone.utc)。
    回滚后代码 tz-aware 跟 DB naive 比较仍触发陷阱 #2 TypeError。
    若需回滚到 v4 状态，必须**配合代码版本回滚**（git checkout 到 phase4 之前的 commit）。
    单跑 `alembic downgrade phase4_frontend_consume` 不足以恢复服务。

Revision ID: phase5_tz_aware
Revises: phase4_frontend_consume
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa


revision = "phase5_tz_aware"
down_revision = "phase4_frontend_consume"
branch_labels = None
depends_on = None


# 待迁列清单（7 表 12 列）
# 注：strava_imports.updated_at 已在 phase4_frontend_consume 改过，跳过
#     strava_imports.cursor_before / users.strava_token_expires_at 创建时即 tz-aware，跳过
COLUMNS_TO_TZ_AWARE = [
    ("activities", "started_at"),
    ("activities", "finished_at"),
    ("activities", "created_at"),
    ("activities", "updated_at"),
    ("trackpoints", "timestamp"),
    ("segments", "created_at"),
    ("segment_efforts", "created_at"),
    ("notifications", "expires_at"),
    ("notifications", "created_at"),
    ("users", "created_at"),
    ("users", "updated_at"),
    ("strava_imports", "created_at"),
]


def upgrade() -> None:
    """naive → tz-aware：把现有值当 UTC 处理，加 +00 时区标记。"""
    for table, col in COLUMNS_TO_TZ_AWARE:
        op.alter_column(
            table,
            col,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{col} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """tz-aware → naive：丢弃时区元数据，保留值（按 UTC 解读）。"""
    for table, col in COLUMNS_TO_TZ_AWARE:
        op.alter_column(
            table,
            col,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{col} AT TIME ZONE 'UTC'",
        )
