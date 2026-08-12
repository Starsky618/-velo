"""
Alembic 迁移环境配置——连接"代码里的表定义"和"数据库里的真实表"的桥梁。

工作原理：
1. 从 app/config.py 读取数据库地址（不硬编码在 alembic.ini 里，保持单一来源）
2. 导入所有模块的 models.py，让 Alembic 知道"代码里定义了哪些表"
3. 运行 --autogenerate 时，Alembic 对比"代码定义"和"数据库现状"，自动生成差异脚本

注意事项：
- 新增模块时，必须在下方 import 该模块的 models，否则 autogenerate 看不到新表
- 数据库地址统一从 app/config.py 读取，不要在 alembic.ini 里单独维护
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from app.config import settings
from app.database import Base

# ===== 关键步骤：导入所有模块的 models =====
# Alembic 的 autogenerate 通过扫描 Base.metadata 来发现表定义，
# 但 Python 的 import 是惰性的——如果没人 import 这些 models.py，
# 它们定义的表就不会注册到 Base.metadata 上，autogenerate 就看不到。
# 所以这里必须显式 import 每个模块的 models。
# 新增模块时记得在这里加一行。
import app.user.models       # noqa: F401 — users 表
import app.activity.models   # noqa: F401 — activities + trackpoints 表
import app.segment.models    # noqa: F401 — segments + segment_efforts 表
import app.training.models   # noqa: F401 — daily_training_load 表
import app.route_book.models  # noqa: F401 — route_books 表
import app.route_cognition.models  # noqa: F401 — judgment / evidence / research 表
import app.route_cognition.census_models  # noqa: F401 — 区域来源赛段普查表
import app.meetup.models      # noqa: F401 — meetups + participants + media 表
import app.creator_persistence.models  # noqa: F401 — Creator private event truth + projections

# Alembic 配置对象（读取 alembic.ini）
config = context.config

# 用 app/config.py 的数据库地址覆盖 alembic.ini 中的占位值，
# 保证"代码用的数据库"和"迁移用的数据库"永远是同一个
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 配置 Python logging
if (
    config.config_file_name is not None
    and config.attributes.get("configure_logger", True)
):
    fileConfig(config.config_file_name)

# 告诉 Alembic "代码里的表长什么样"
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线模式：不连数据库，只生成 SQL 文本。
    适合 DBA 审核 SQL 后手动执行的场景。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式：连接数据库，直接执行迁移。
    这是最常用的模式——autogenerate 和 upgrade 都走这里。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
