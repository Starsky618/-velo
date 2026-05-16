"""sprint6_user_bio：User.bio 个性签名字段（Sprint 6 task-1）。

Sprint 6 把"我的"页升级为骑手身份名片，task-1 是地基：
加 bio 字段——一行短签名（≤ 30 字符）让别人秒懂用户是哪种骑手。

类比：给小区物业的住户档案多加一栏"个性介绍"，
档案柜里所有住户都加这一栏（DB schema），但每个住户填不填随意（nullable）。

字段约束：
- DB varchar(30)：与 Pydantic schema max_length=30 完全对齐（PostgreSQL varchar
  按 Unicode codepoint 计长度，不是字节）；防止脚本绕过 API 直写超长 bio。
- nullable=True：未填写状态等价 NULL
- 不加 CHECK 约束：空串/纯空格/换行的清洗在应用层（schema validator + service strip 归一化）

Revision ID: sprint6_user_bio
Revises: sprint5_activity_privacy
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "sprint6_user_bio"
down_revision = "sprint5_activity_privacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """加 bio 列到 users 表。"""
    op.add_column("users", sa.Column("bio", sa.String(30), nullable=True))


def downgrade() -> None:
    """回滚：删除 bio 列。"""
    op.drop_column("users", "bio")
