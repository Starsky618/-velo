"""sprint6_activity_city：activities.city 字段（Sprint 6 task-3）。

Sprint 6 把"我的"页升级为骑手身份名片，task-3 加"城市征服墙"地基：
让每条骑行记录起点城市（6 主城 + unknown 或 NULL），city-medals endpoint
按此聚合"用户在哪几个城市骑过"。

类比：给小区物业的"快递柜流水台账"加一栏"快递起始城市"——
不影响其他字段、不阻断已有流程，只是多记一格信息。

字段约束：
- DB varchar(32)：与 users.city 完全一致（同枚举字符串）。
- nullable=True：旧数据 / 起点经纬度缺失 / worker 异常都允许为 NULL。
- CHECK 约束：要么 NULL，要么 7 个枚举值之一（6 城 + unknown）。

NULL vs 'unknown' 语义区分（红线 / 不可混淆）：
- NULL = "从未推断过"（旧数据 / 解析失败 / 无坐标）
- 'unknown' = "推断过但不在 6 城内"（用户骑老家小县城）
- 业务层（city-medals 聚合）用 `city IN (6 城)` 过滤同时排除两者。

partial index 设计：
- 只索引 `status='completed' AND city IS NOT NULL AND duplicate_of IS NULL` 的行。
- city-medals 聚合 + 未来按城市筛 feed 都命中此索引。
- 比建一个无条件 (user_id, city) 全表索引省 30-50% 索引空间
  （pending / failed / city=NULL / duplicate 行不进索引）。
- partial index 是 PostgreSQL 特性，SQLite 不支持 → dialect 守卫跳过。

部署纪律：
- 跑完 upgrade 后建议跑 scripts/backfill_activity_city.py 回填历史 activity。

Revision ID: sprint6_activity_city
Revises: sprint6_user_bio
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "sprint6_activity_city"
down_revision = "sprint6_user_bio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """加 city 列 + CHECK 约束 + partial index 到 activities 表。"""
    op.add_column(
        "activities",
        sa.Column("city", sa.String(32), nullable=True),
    )

    # CHECK 约束（与 users.city 完全一致 / 6 城 + unknown / 防脏数据）
    # 维护城市真实 3 处之一（见模块顶部 docstring）：
    # 字符串必须写死 / Alembic 迁移不能 import 应用代码（迁移要可独立跑）
    op.create_check_constraint(
        "ck_activities_city",
        "activities",
        "city IS NULL OR city IN ('beijing', 'shanghai', 'hangzhou', "
        "'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
    )

    # partial index 加速 city-medals 聚合（CLAUDE.md 陷阱 #15 / SQLite dialect 守卫）
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "idx_activities_user_city_completed",
            "activities",
            ["user_id", "city"],
            postgresql_where=sa.text(
                "status = 'completed' AND city IS NOT NULL AND duplicate_of IS NULL"
            ),
        )


def downgrade() -> None:
    """回滚：删 partial index + CHECK + city 列。"""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index(
            "idx_activities_user_city_completed", table_name="activities"
        )
    op.drop_constraint("ck_activities_city", "activities", type_="check")
    op.drop_column("activities", "city")
