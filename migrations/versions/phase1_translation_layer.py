"""phase1 translation layer — 翻译层数据库变更

这个迁移为翻译层（第 1 期）做表结构准备：
1. trackpoints 表新增 speed 和 distance 列（逐点速度和累计距离）
2. activities 表新增 normalized_power 和 data_source 列（标准化功率和数据来源标记）

所有新列都是 nullable：老数据不回填，service 层兼容 NULL。
speed 和 distance 不加索引：它们只在 API 输出时使用，不参与查询条件。

Revision ID: phase1_translation
Revises: phase0_fixes
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

# 版本链：本迁移接在 phase0_fixes 之后
revision = 'phase1_translation'
down_revision = 'phase0_fixes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== trackpoints 表：新增 speed 和 distance 列 =====
    # speed：逐点瞬时速度（m/s），GPX 由解析器计算，FIT/Strava 直接提供
    # 老数据为 NULL，新上传的数据会填充此列
    op.add_column('trackpoints', sa.Column('speed', sa.Float, nullable=True))

    # distance：从起点到该点的累计距离（米），用于前端曲线图的 X 轴
    # 老数据为 NULL，新上传的数据会填充此列
    op.add_column('trackpoints', sa.Column('distance', sa.Float, nullable=True))

    # ===== activities 表：新增 normalized_power 和 data_source 列 =====
    # normalized_power：标准化功率（NP），只有 FIT 文件自带，GPX 和 Strava 为 NULL
    # 这是训练分析的高级指标，反映骑行强度的"真实感受"
    op.add_column('activities', sa.Column('normalized_power', sa.Float, nullable=True))

    # data_source：标记这条记录来自哪个数据来源（gpx / fit / strava）
    # 老数据为 NULL（都是 GPX 上传的），新上传时由 Worker 根据文件类型填写
    op.add_column('activities', sa.Column('data_source', sa.String(20), nullable=True))


def downgrade() -> None:
    # 回滚顺序：按添加的逆序删除
    op.drop_column('activities', 'data_source')
    op.drop_column('activities', 'normalized_power')
    op.drop_column('trackpoints', 'distance')
    op.drop_column('trackpoints', 'speed')
