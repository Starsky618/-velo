"""phase2 strava imports — Strava 历史导入进度表 + file_url nullable

这个迁移做两件事：
1. 创建 strava_imports 表：记录每个用户的 Strava 历史导入进度（"搬家工单"）
2. 修改 activities.file_url 为 nullable：Strava 导入的活动没有本地文件

好比搬家公司的系统升级：
- 新增了一张"搬家工单"表，记录每次搬家进度
- 原来的"快递收件地址"字段变成可选的——因为 Strava 的数据不需要本地存文件

Revision ID: phase2_strava_imports
Revises: phase2_strava_oauth
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

# 版本链：本迁移接在 phase2_strava_oauth 之后
revision = 'phase2_strava_imports'
down_revision = 'phase2_strava_oauth'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== 1. 创建 strava_imports 表 =====
    # 这张表追踪 Strava 历史数据的搬运进度：搬了多少、跳过多少、下次从哪接着搬
    op.create_table(
        'strava_imports',
        # 主键
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        # 所属用户（外键关联 users 表）
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        # Strava 运动员 ID（冗余存储，避免每次查询都 JOIN users）
        sa.Column('strava_athlete_id', sa.BigInteger, nullable=False),
        # 总活动数（扫描完列表后更新）
        sa.Column('total_activities', sa.Integer, nullable=True),
        # 进度计数：第一层完成、第二层完成、第二层跳过
        sa.Column('tier1_completed', sa.Integer, server_default='0'),
        sa.Column('tier2_completed', sa.Integer, server_default='0'),
        sa.Column('tier2_skipped', sa.Integer, server_default='0'),
        # 断点续传游标：下次拉列表用 before=此值
        # DateTime(timezone=True) → TIMESTAMP WITH TIME ZONE，防 naive/aware 陷阱
        sa.Column('cursor_before', sa.DateTime(timezone=True), nullable=True),
        # 状态：active / paused / completed
        sa.Column('status', sa.String(20), server_default='active'),
        # 时间戳
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ===== 2. activities.file_url 改为 nullable =====
    # Strava 导入的活动没有本地文件，file_url 为 NULL
    # 原来是 NOT NULL，现在改为允许 NULL
    op.alter_column('activities', 'file_url', nullable=True)


def downgrade() -> None:
    # ===== 回滚顺序：先改列、再删表（与 upgrade 相反）=====

    # 恢复 file_url 为 NOT NULL
    # 注意：如果已有 NULL 值的行，需要先清理，否则此操作会失败
    op.alter_column('activities', 'file_url', nullable=False)

    # 删除 strava_imports 表
    op.drop_table('strava_imports')
