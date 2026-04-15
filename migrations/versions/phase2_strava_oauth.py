"""phase2 strava oauth — Strava 集成数据库变更

这个迁移为第 2 期 Strava 集成做表结构准备：
1. users 表新增 4 个 Strava OAuth 字段（athlete_id、令牌、过期时间）
2. activities 表新增 strava_activity_id 列（Strava 活动去重）
3. activities 表新增 status CHECK 约束，把 'importing' 纳入合法状态

好比给系统办了一张"Strava 联名会员卡"：
- users 表记住每个用户的会员卡信息（卡号、密码、有效期）
- activities 表能标记"这条记录是从 Strava 同步来的"
- status 多了一个 'importing' 状态，表示"正在从 Strava 搬运数据"

所有新列都是 nullable：老用户不受影响，绑定 Strava 后才会填充。

Revision ID: phase2_strava_oauth
Revises: phase1_translation
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

# 版本链：本迁移接在 phase1_translation 之后
revision = 'phase2_strava_oauth'
down_revision = 'phase1_translation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== users 表：新增 Strava OAuth 绑定字段 =====

    # strava_athlete_id：用户在 Strava 平台的唯一 ID
    # 用 BigInteger 因为 Strava 的用户 ID 是大整数（可能超过 int32 的 21 亿上限）
    # UNIQUE 约束：一个 Strava 账号只能绑一个系统用户，防止"一号多绑"
    op.add_column('users', sa.Column(
        'strava_athlete_id', sa.BigInteger, nullable=True, unique=True,
    ))

    # strava_access_token：访问 Strava API 的"临时通行证"
    # 有效期通常 6 小时，过期后用 refresh_token 换新的
    op.add_column('users', sa.Column(
        'strava_access_token', sa.String(255), nullable=True,
    ))

    # strava_refresh_token："换通行证的凭据"
    # 只要用户不解绑，这个 token 长期有效，用来换新的 access_token
    op.add_column('users', sa.Column(
        'strava_refresh_token', sa.String(255), nullable=True,
    ))

    # strava_token_expires_at：通行证的过期时间（UTC）
    # 每次请求 Strava API 前先检查这个时间，快过期就提前刷新
    # 用 DateTime(timezone=True) 映射为 TIMESTAMP WITH TIME ZONE，
    # 确保读出的 datetime 带时区信息，避免 Python 端 naive vs aware 比较报错
    op.add_column('users', sa.Column(
        'strava_token_expires_at', sa.DateTime(timezone=True), nullable=True,
    ))

    # ===== activities 表：新增 Strava 活动去重字段 =====

    # strava_activity_id：这条骑行记录在 Strava 上的原始 ID
    # UNIQUE 约束防止同一条 Strava 活动被重复导入
    # 非 Strava 来源的活动（GPX/FIT 上传）此字段为 NULL
    op.add_column('activities', sa.Column(
        'strava_activity_id', sa.BigInteger, nullable=True, unique=True,
    ))

    # ===== activities 表：更新 status CHECK 约束 =====
    # 新增 'importing' 状态：表示正在从 Strava 拉取数据
    # 先删除旧约束（如果存在），再创建新的
    # 注意：PostgreSQL 中 try/except 不能绕过事务失败状态，
    # 必须用 DO $$ 块 + EXCEPTION 处理，这是数据库层面的异常隔离
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE activities DROP CONSTRAINT ck_activities_status;
        EXCEPTION
            WHEN undefined_object THEN NULL;
        END $$;
    """)

    op.create_check_constraint(
        'ck_activities_status',
        'activities',
        "status IN ('pending', 'processing', 'completed', 'failed', 'importing')",
    )


def downgrade() -> None:
    # ===== 回滚 status CHECK 约束 =====
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE activities DROP CONSTRAINT ck_activities_status;
        EXCEPTION
            WHEN undefined_object THEN NULL;
        END $$;
    """)
    op.create_check_constraint(
        'ck_activities_status',
        'activities',
        "status IN ('pending', 'processing', 'completed', 'failed')",
    )

    # ===== 回滚顺序：按添加的逆序删除 =====
    op.drop_column('activities', 'strava_activity_id')
    op.drop_column('users', 'strava_token_expires_at')
    op.drop_column('users', 'strava_refresh_token')
    op.drop_column('users', 'strava_access_token')
    op.drop_column('users', 'strava_athlete_id')
