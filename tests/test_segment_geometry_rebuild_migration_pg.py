"""标准几何迁移的真 PostgreSQL 前进、回退与历史 hash 拒绝回退测试。"""

from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings


def test_segment_geometry_migration_roundtrip_and_incompatible_history_guard():
    base_url_text = os.getenv("VELO_TEST_DATABASE_URL")
    if not base_url_text:
        pytest.skip("设置 VELO_TEST_DATABASE_URL 后才运行赛段几何迁移真 PG 测试")

    base_url = make_url(base_url_text)
    database_name = f"velo_seg_geom_migration_{uuid.uuid4().hex}"
    temp_url = base_url.set(database=database_name)
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    original_database_url = settings.DATABASE_URL
    temp_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        temp_engine = create_engine(temp_url, pool_pre_ping=True)
        with temp_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

        settings.DATABASE_URL = temp_url.render_as_string(hide_password=False)
        # Alembic 的 fileConfig 会重置当前进程的全局 logging；本测试在 pytest
        # 进程内运行，若不关闭会移除 caplog handler，污染后续日志断言。
        alembic_config = Config(
            "alembic.ini",
            attributes={"configure_logger": False},
        )
        command.upgrade(alembic_config, "head")
        with temp_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                "20260809_seg_geom_rebuild"
            )

        command.downgrade(alembic_config, "20260806_creator_ctx_v1")
        command.upgrade(alembic_config, "head")

        # 只在一次性测试库绕过 FK，构造“current cognition 已换新 hash，历史成员仍
        # 保留旧 hash”的合法升级后语义；downgrade 必须在任何 DDL 前明确拒绝。
        with temp_engine.begin() as connection:
            connection.execute(text("SET session_replication_role = replica"))
            connection.execute(
                text(
                    """
                    INSERT INTO route_cognition_segments (
                        segment_id,
                        review_basis,
                        eligibility_status,
                        geometry_hash,
                        normalization_version,
                        accepted_judgment_run_id,
                        reviewed_at
                    ) VALUES (
                        999,
                        'legacy_reviewed',
                        'active',
                        'new-hash',
                        'test-v1',
                        999,
                        now()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO collection_segments (
                        collection_id,
                        segment_id,
                        segment_geometry_hash,
                        role,
                        membership_status,
                        source_kind,
                        accepted_judgment_run_id,
                        accepted_judgment_run_type
                    ) VALUES (
                        999,
                        999,
                        'old-hash',
                        'core',
                        'deprecated',
                        'manual_curated',
                        999,
                        'human_review'
                    )
                    """
                )
            )

        with pytest.raises(RuntimeError, match="historical membership hashes"):
            command.downgrade(alembic_config, "20260806_creator_ctx_v1")

        with temp_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                "20260809_seg_geom_rebuild"
            )
    finally:
        settings.DATABASE_URL = original_database_url
        if temp_engine is not None:
            temp_engine.dispose()
        try:
            with admin_engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        finally:
            admin_engine.dispose()
