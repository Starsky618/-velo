"""第 5 期主迁移：B/C/A/D 主轴的所有 schema 改动。

修改点（9 项）：
1. segments 加 difficulty / max_gradient / city（防火墙破例 3 处）
2. users 加 city（防火墙破例 1 处）
3. notifications.event_type 长度 VARCHAR(20) → VARCHAR(32)
   （Codex 异源审抓出：'progress_monthly_summary' 24 字符超 20 上限，写入会报错）
4. notifications.event_type CHECK 扩展（drop 旧 add 新，从 3 值扩到 6 值）
5. notifications.payload JSONB NULL 字段（spec §2 修订补遗 5.5——progress 类塞 current/prev/delta）
6. notifications 部分唯一索引 uniq_progress_notification_per_activity
   （spec 5.6 / codex E1 C13——progress 类幂等闸门：仅对 progress_% 类生效）
7. 新建 segment_ai_drafts 表（5.B.2 + 5.D.2）
8. 新建 segment_curation_pool 表（5.D.1）
9. 新建索引 idx_segments_city_difficulty / idx_ai_drafts_status / idx_curation_pool_selected

为什么 9 项合一份迁移：
    所有改动属同一期（v5）业务主题，原子性落地。
    分多份会增加版本管理成本且无隔离收益。
    单 revision = 单事务，崩溃时 PG 自动整体回滚，不会留中间态。

注意事项：
- segments.difficulty / segments.city 用 NOT NULL + server_default，避免老数据破 NOT NULL；
  task 0.7 老数据回填脚本会把 default 替换成基于轨迹算出的精确值
- ck_notif_event_type 是 v0/phase3_notifications 显式命名，**不是 PG 默认命名**，
  drop_constraint 时直接用此名（已 grep 验证）
- notifications.payload 字段属本 task 0.6（spec §2 修订补遗）；
  task-2.A.1 实施卡说"task 0.6 已迁，本 task 加 ORM 声明"，时序正确

部署 runbook 提醒：
- alembic 默认单事务跑 DDL（ACCESS EXCLUSIVE 表锁），并发 INSERT notifications/segments
  会被锁住等待，理论上不出现"无 CHECK 中间态"。但事务持续期间生产 worker 写表会卡，
  生产部署前最好暂停 worker 几秒，确保部署窗口干净。
- segments / users 加 server_default 后该 default 永驻（设计意图）：
  未来新插入若不显式提供 difficulty / city，DB 会自动填 'medium' / 'unknown' 兜底；
  业务代码（task 1.A.1 起）应主动显式赋值算法值，不依赖 default 兜底。

Revision ID: phase5_v5_db_changes
Revises: phase5_tz_aware
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  # JSONB 字段 + 部分唯一索引必需


revision = "phase5_v5_db_changes"
down_revision = "phase5_tz_aware"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === 1. segments 加 3 字段（防火墙破例 3 处）===
    op.add_column(
        "segments",
        sa.Column(
            "difficulty",
            sa.String(length=16),
            nullable=False,
            server_default="medium",
        ),
    )
    op.add_column(
        "segments",
        sa.Column("max_gradient", sa.Float(), nullable=True),
    )
    op.add_column(
        "segments",
        sa.Column(
            "city",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_check_constraint(
        "ck_segments_difficulty",
        "segments",
        "difficulty IN ('easy', 'medium', 'hard', 'extreme')",
    )
    op.create_check_constraint(
        "ck_segments_city",
        "segments",
        "city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', "
        "'chengdu', 'taiyuan', 'unknown')",
    )
    op.create_index(
        "idx_segments_city_difficulty",
        "segments",
        ["city", "difficulty"],
    )

    # === 2. users 加 city 字段（防火墙破例 1 处）===
    # users.city 允许 NULL（用户未填写时为空），CHECK 用 IS NULL OR IN (...) 包容
    op.add_column(
        "users",
        sa.Column("city", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_city",
        "users",
        "city IS NULL OR city IN ('beijing', 'shanghai', 'hangzhou', "
        "'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
    )

    # === 3. 新建 segment_ai_drafts 表（5.B.2）===
    op.create_table(
        "segment_ai_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "segment_id",
            sa.Integer(),
            sa.ForeignKey("segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ai_draft_text", sa.Text(), nullable=False),
        sa.Column("human_edited_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "editor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("segment_id", name="uq_segment_ai_drafts_segment_id"),
    )
    op.create_check_constraint(
        "ck_segment_ai_drafts_status",
        "segment_ai_drafts",
        "status IN ('pending', 'human_edited', 'approved', 'rejected')",
    )
    op.create_index("idx_ai_drafts_status", "segment_ai_drafts", ["status"])

    # === 4. 新建 segment_curation_pool 表（5.D.1）===
    op.create_table(
        "segment_curation_pool",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "segment_id",
            sa.Integer(),
            sa.ForeignKey("segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pool_score", sa.Float(), nullable=False),
        sa.Column("pool_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "selected_for_v5",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "selected_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("segment_id", name="uq_curation_pool_segment_id"),
    )
    op.create_index(
        "idx_curation_pool_selected",
        "segment_curation_pool",
        ["selected_for_v5"],
    )

    # === 5. notifications.event_type 长度 VARCHAR(20) → VARCHAR(32) ===
    # Codex 异源审抓出：'progress_monthly_summary' 24 字符超 String(20) 上限
    # 32 留 8 字符余量给未来 progress_xxx 类型扩展
    op.alter_column(
        "notifications",
        "event_type",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )

    # === 6. notifications.event_type CHECK 扩展（5.C.3）===
    # 实际约束名 'ck_notif_event_type' 是 phase3_notifications 显式命名（非 PG 默认）
    # 老数据 event_type 取值为 ('pr','kom','kom_lost')，全部在新值集内，扩展不破坏现有数据
    op.drop_constraint("ck_notif_event_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notif_event_type",
        "notifications",
        "event_type IN ('pr', 'kom', 'kom_lost', "
        "'progress_5min_power', 'progress_segment_pb', 'progress_monthly_summary')",
    )

    # === 7. notifications.payload JSONB NULL（spec §2 修订补遗 5.5）===
    # progress 类（5min 功率涨/赛段异步 PB/月度对比）需 (current/prev/delta) 数据
    # 现有 PR/KOM 类 payload 留 NULL（沿用现有字段语义）
    op.add_column(
        "notifications",
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # === 8. notifications 部分唯一索引（spec 5.6 / codex E1 C13）===
    # progress_% 类 (activity_id, event_type) UNIQUE：worker 重试 / 并发不会重复推
    # PR/KOM 类不受影响（用 effort_id + event_type UNIQUE 做幂等）
    op.create_index(
        "uniq_progress_notification_per_activity",
        "notifications",
        ["activity_id", "event_type"],
        unique=True,
        postgresql_where=sa.text("event_type LIKE 'progress_%'"),
    )

    # 老数据回填不在迁移脚本里 —— 见 task 0.7 + scripts/backfill_phase5.py


def downgrade() -> None:
    # 严格逆序拆除：依赖在前的最后建，最先拆
    # ⚠ downgrade 前注意：若已有 progress_5min_power / progress_segment_pb /
    # progress_monthly_summary 类型的 notifications 写入，旧 CHECK 重建会报错；
    # event_type VARCHAR(32) → VARCHAR(20) 时若有 'progress_monthly_summary'（24字符）
    # 数据也会 truncation 报错。
    # 回滚前必须先：
    #   DELETE FROM notifications WHERE event_type IN
    #     ('progress_5min_power', 'progress_segment_pb', 'progress_monthly_summary');

    # === 8. 删部分唯一索引 ===
    op.drop_index(
        "uniq_progress_notification_per_activity",
        table_name="notifications",
    )

    # === 7. 删 notifications.payload ===
    op.drop_column("notifications", "payload")

    # === 6. 还原 notifications CHECK ===
    op.drop_constraint("ck_notif_event_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notif_event_type",
        "notifications",
        "event_type IN ('pr', 'kom', 'kom_lost')",
    )

    # === 5. 还原 event_type 长度 VARCHAR(32) → VARCHAR(20) ===
    op.alter_column(
        "notifications",
        "event_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )

    # === 4. 删 segment_curation_pool ===
    op.drop_index("idx_curation_pool_selected", table_name="segment_curation_pool")
    op.drop_table("segment_curation_pool")

    # === 3. 删 segment_ai_drafts ===
    op.drop_index("idx_ai_drafts_status", table_name="segment_ai_drafts")
    op.drop_constraint(
        "ck_segment_ai_drafts_status", "segment_ai_drafts", type_="check"
    )
    op.drop_table("segment_ai_drafts")

    # === 2. 删 users.city ===
    op.drop_constraint("ck_users_city", "users", type_="check")
    op.drop_column("users", "city")

    # === 1. 删 segments.city / max_gradient / difficulty ===
    op.drop_index("idx_segments_city_difficulty", table_name="segments")
    op.drop_constraint("ck_segments_city", "segments", type_="check")
    op.drop_constraint("ck_segments_difficulty", "segments", type_="check")
    op.drop_column("segments", "city")
    op.drop_column("segments", "max_gradient")
    op.drop_column("segments", "difficulty")
