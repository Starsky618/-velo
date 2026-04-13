"""phase0 foundation fixes

这个迁移做两件事：
1. activities 表新增 file_hash 列，用于重复上传检测
2. segment_efforts 表新增 PR 检测索引，加速"用户在某赛段的最佳成绩"查询

Revision ID: phase0_fixes
Revises: 0d0e5adcd706
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa

# 版本链：本迁移接在 initial_schema 之后
revision = 'phase0_fixes'
down_revision = '0d0e5adcd706'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== activities 表：新增 file_hash 列 =====
    # 存储 GPX 文件内容的 SHA-256 哈希值（64 位十六进制字符串）
    # nullable=True：老记录没有哈希值，不影响 UNIQUE 约束（SQL 标准：NULL != NULL）
    op.add_column('activities', sa.Column('file_hash', sa.String(64), nullable=True))

    # 数据库层最后防线：同一用户 + 同一文件哈希 = 重复上传，直接拦截
    # 约束只对非 NULL 值生效，因此历史记录不受影响
    op.create_unique_constraint('uq_user_file_hash', 'activities', ['user_id', 'file_hash'])

    # ===== segment_efforts 表：新增 PR 检测索引 =====
    # 三列联合索引：segment_id + user_id + elapsed_time
    # 支持 index-only scan，查"用户在某赛段的最短用时"时无需回表
    # 好比在档案馆建立"赛段→用户→用时"三级目录，找最快成绩直接定位，不用翻全部档案
    op.create_index(
        'idx_efforts_segment_user_time',
        'segment_efforts',
        ['segment_id', 'user_id', 'elapsed_time'],
    )


def downgrade() -> None:
    # 回滚顺序：先删索引，再删约束，最后删列
    op.drop_index('idx_efforts_segment_user_time', table_name='segment_efforts')
    op.drop_constraint('uq_user_file_hash', 'activities', type_='unique')
    op.drop_column('activities', 'file_hash')
