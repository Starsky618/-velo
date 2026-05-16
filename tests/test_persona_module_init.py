"""Persona Engine task-1：模块脚手架 + 迁移地基冒烟测试。

测试 4 项目标（plan task-1 § 测试要求）：
1. 5 个空骨架 + models 模块全可 import（防未来重命名 / 误删文件）
2. __init__.py docstring 含 "ADR-009" + "宪法" 字样（防边界声明被无意删除 / 违反 = REJECT）
3. 迁移文件 metadata 对（revision / down_revision 链不断）
4. 3 个 ORM 模型字段 / 索引齐 + SQLite 真建表 / 真 drop（绕开 PostGIS 全链路）

为什么不真跑 `alembic upgrade head`：
- 前置迁移有 PostGIS Geometry 字段 / SQLite alembic 全链路会跪
- 真链路验证留 task-6 真用回归 + 部署后 alembic upgrade head 手动 verify
- 本测试用 Base.metadata.create_all() 隔离测 persona 3 张表的 schema 正确性
"""

import importlib
import pathlib

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.database import Base


# 项目根目录绝对路径（防 CI 从非根目录跑 pytest 时相对路径断 / Codex+Claude 三审共识 I2）
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ─── 测试 1：5 个空骨架 + models 全可 import ───


def test_persona_modules_all_importable():
    """5 个空骨架 + models 全 import 成功（防未来重命名 / 误删文件）。"""
    from app.agent.persona import (
        trigger_router,
        template_lib,
        filters,
        cache,
        service,
        models,
    )
    # 真的拿到 module 对象 / 不只是 import 不报错
    assert all(
        m is not None
        for m in (trigger_router, template_lib, filters, cache, service, models)
    )


# ─── 测试 2：__init__.py docstring 含边界声明字样 ───


def test_persona_init_docstring_has_boundary_markers():
    """__init__.py docstring 必须含 "ADR-009" + "宪法" 字样（防边界声明被删 / 违反 = REJECT）。"""
    import app.agent.persona as persona_pkg
    doc = persona_pkg.__doc__ or ""
    assert "ADR-009" in doc, "__init__.py 必须声明 ADR-009 边界（违反 = REJECT）"
    assert "宪法" in doc, "__init__.py 必须 reference Persona 宪法（文案灵魂源）"


# ─── 测试 3：迁移文件 metadata 链对 ───


def test_persona_migration_revision_chain():
    """迁移文件 revision / down_revision 元数据对（防链断 / Sprint 6 真 head = sprint6_activity_city）。"""
    # 用 importlib 加载迁移模块（路径有"."不能用 from..import）
    # 绝对路径 / 防 CI 从非项目根目录跑时 spec_from_file_location 返 None → AttributeError
    mig_path = _PROJECT_ROOT / "migrations" / "versions" / "persona_engine_init.py"
    spec = importlib.util.spec_from_file_location(
        "persona_engine_init_mig",
        str(mig_path),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "persona_engine_init"
    assert module.down_revision == "sprint6_activity_city"
    # 防未来手抖把 upgrade/downgrade 删了
    assert callable(module.upgrade)
    assert callable(module.downgrade)


# ─── 测试 4：ORM 模型字段 / 索引齐 + SQLite 真建表 / 真 drop ───


@pytest.fixture()
def isolated_persona_engine():
    """独立 in-memory SQLite engine / 只装 persona 3 张表 / 不污染其他测试。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()


def test_persona_orm_models_schema(isolated_persona_engine):
    """3 个 ORM 模型字段类型 / 索引名 / 表名全对 + SQLite 真建表 / 真 drop 干净。"""
    from app.agent.persona.models import (
        PersonaOutput,
        PersonaTemplate,
        PersonaFeedback,
    )

    # 字段层断言（ORM 声明 / 防未来手抖改字段类型）
    assert PersonaOutput.__tablename__ == "persona_outputs"
    assert PersonaTemplate.__tablename__ == "persona_templates"
    assert PersonaFeedback.__tablename__ == "persona_feedback"

    # text_snapshot 必存在（v0.4 修 C1 / 防未来回退到 JOIN templates）
    assert "text_snapshot" in PersonaOutput.__table__.columns

    # tz-aware DateTime（CLAUDE.md 陷阱 #2 / 防 naive 比较踩坑）
    shown_at = PersonaOutput.__table__.columns["shown_at"]
    assert shown_at.type.timezone is True

    # PersonaFeedback.created_at 同样必须 tz-aware（Claude A I3 抓）
    feedback_created_at = PersonaFeedback.__table__.columns["created_at"]
    assert feedback_created_at.type.timezone is True

    # PersonaOutput.activity_id FK 必须有 ondelete="SET NULL"（Codex C1 抓 / 防生产删 activity 500）
    activity_fk = next(iter(PersonaOutput.__table__.columns["activity_id"].foreign_keys))
    assert activity_fk.ondelete == "SET NULL"

    # 索引名（PR review 红线 / 防未来重命名误伤 endpoint 查询计划）
    output_indexes = {idx.name for idx in PersonaOutput.__table__.indexes}
    assert "ix_persona_outputs_user_scene_shown" in output_indexes

    template_indexes = {idx.name for idx in PersonaTemplate.__table__.indexes}
    assert "ix_persona_templates_scene_active" in template_indexes

    # 真建表测试：SQLite 跑 create_all → 3 表 + 索引在 → drop_all 干净
    # 只建 persona 3 表 / 不建 users + activities（避免 activities 的 JSONB 字段
    # 在 SQLite 上 CompileError / SQLite FK 默认 off 不强制 FK 目标存在）
    persona_tables = [
        Base.metadata.tables[t]
        for t in ("persona_outputs", "persona_templates", "persona_feedback")
    ]
    Base.metadata.create_all(
        bind=isolated_persona_engine, tables=persona_tables,
    )

    inspector = inspect(isolated_persona_engine)
    db_tables = set(inspector.get_table_names())
    assert "persona_outputs" in db_tables
    assert "persona_templates" in db_tables
    assert "persona_feedback" in db_tables

    # 索引也真建出来了（不只是 ORM 声明）
    db_indexes_on_outputs = {
        idx["name"]
        for idx in inspector.get_indexes("persona_outputs")
    }
    assert "ix_persona_outputs_user_scene_shown" in db_indexes_on_outputs

    db_indexes_on_templates = {
        idx["name"]
        for idx in inspector.get_indexes("persona_templates")
    }
    assert "ix_persona_templates_scene_active" in db_indexes_on_templates

    # downgrade 干净：drop_all → 3 表全没（顺序反向 / FK 依赖 persona_outputs 的 feedback 先删）
    Base.metadata.drop_all(
        bind=isolated_persona_engine,
        tables=[
            Base.metadata.tables["persona_feedback"],
            Base.metadata.tables["persona_templates"],
            Base.metadata.tables["persona_outputs"],
        ],
    )
    inspector = inspect(isolated_persona_engine)
    db_tables_after = set(inspector.get_table_names())
    assert "persona_outputs" not in db_tables_after
    assert "persona_templates" not in db_tables_after
    assert "persona_feedback" not in db_tables_after
