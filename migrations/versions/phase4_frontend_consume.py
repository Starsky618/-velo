"""第 4 期迁移：前端反馈环闭合所需的 5 项 DB 改动。

修改点：
1. notifications 表加 is_read 字段 + 部分索引
2. activities 表加 activity_type 字段（多运动种子）
3. users 表加 mute_notifications 字段（免打扰种子）
4. strava_imports.updated_at 改成 TIMESTAMP WITH TIME ZONE
5. notifications 外键（segment_id/activity_id）改为 ON DELETE SET NULL

为什么 5 项合一个文件：
    这些改动互不干扰、属于同一业务主题，一次迁移可以原子性完成。
    若分成 5 个迁移文件会增加版本管理成本且没有隔离收益。

Revision ID: phase4_frontend_consume
Revises: phase3_notifications
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "phase4_frontend_consume"
down_revision = "phase3_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ========================================================
    # 改动 1：notifications 加 is_read 字段
    # ========================================================
    # 为什么 NOT NULL + 默认 FALSE：
    #   老通知（第 3 期产生的）要视为未读，让用户进通知页后一次性 mark-all-read
    op.add_column(
        "notifications",
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )

    # 部分索引：只索引未读 + 未过期的通知
    # 这是 unread_count 高频查询的支撑（task-7.8 用）
    # 部分索引的空间占用比全表索引小 10 倍以上（假设只有 5% 未读）
    op.create_index(
        "idx_notifications_user_unread",
        "notifications",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("is_read = FALSE"),
    )

    # ========================================================
    # 改动 2：activities 加 activity_type 字段（种子 1）
    # ========================================================
    # PostgreSQL 11+ 加列带 server_default 不会重写全表，
    # 老数据（33 条）自动获得默认值 'cycling'
    op.add_column(
        "activities",
        sa.Column(
            "activity_type",
            sa.String(20),
            nullable=False,
            server_default="cycling",
            comment="活动类型：cycling / running（预留）/ hiking（预留）",
        ),
    )

    # ========================================================
    # 改动 3：users 加 mute_notifications 字段（种子）
    # ========================================================
    # nullable：NULL 表示"未设置"，区别于 False（"已设置为不静音"）
    # 本期前端不读写这字段，仅作为未来跨设备同步留位
    op.add_column(
        "users",
        sa.Column(
            "mute_notifications",
            sa.Boolean(),
            nullable=True,
            comment="免打扰开关预留字段。本期仅字段存在，实际开关存前端本地",
        ),
    )

    # ========================================================
    # 改动 4：strava_imports.updated_at 改成 timezone-aware
    # ========================================================
    # 为什么必改：task-7.5 stalled 判定用 datetime.now(UTC) - imp.updated_at
    # 当前 updated_at 是 naive datetime，与 aware datetime 相减会抛 TypeError
    # 迁移策略：用 AT TIME ZONE 'UTC' 把现有值解释为 UTC
    op.alter_column(
        "strava_imports",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
    )

    # ========================================================
    # 改动 5：notifications 外键改成 ON DELETE SET NULL
    # ========================================================
    # 当前：segment_id NOT NULL + CASCADE，activity_id NULLABLE + CASCADE
    # 期望：两个都 NULLABLE + SET NULL
    # 业务动机：赛段或活动被删时，通知记录保留（可显示"该记录已失效"），不连带删除
    #
    # PostgreSQL 外键自动命名规则：<table>_<column>_fkey
    # 现有约束名：notifications_segment_id_fkey / notifications_activity_id_fkey

    # Step 5.1：先 drop 现有外键
    op.drop_constraint("notifications_segment_id_fkey", "notifications", type_="foreignkey")
    op.drop_constraint("notifications_activity_id_fkey", "notifications", type_="foreignkey")

    # Step 5.2：segment_id 改成 nullable（activity_id 本来就是 nullable，不动）
    op.alter_column("notifications", "segment_id", nullable=True)

    # Step 5.3：重建外键 with ON DELETE SET NULL
    op.create_foreign_key(
        "notifications_segment_id_fkey",
        "notifications", "segments",
        ["segment_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "notifications_activity_id_fkey",
        "notifications", "activities",
        ["activity_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # ---- 改动 5 回滚 ----
    op.drop_constraint("notifications_segment_id_fkey", "notifications", type_="foreignkey")
    op.drop_constraint("notifications_activity_id_fkey", "notifications", type_="foreignkey")
    op.alter_column("notifications", "segment_id", nullable=False)
    op.create_foreign_key(
        "notifications_segment_id_fkey",
        "notifications", "segments",
        ["segment_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "notifications_activity_id_fkey",
        "notifications", "activities",
        ["activity_id"], ["id"],
        ondelete="CASCADE",
    )

    # ---- 改动 4 回滚 ----
    op.alter_column(
        "strava_imports",
        "updated_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
    )

    # ---- 改动 3 回滚 ----
    op.drop_column("users", "mute_notifications")

    # ---- 改动 2 回滚 ----
    op.drop_column("activities", "activity_type")

    # ---- 改动 1 回滚 ----
    op.drop_index("idx_notifications_user_unread", table_name="notifications")
    op.drop_column("notifications", "is_read")
