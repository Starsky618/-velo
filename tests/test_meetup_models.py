"""约骑模块 Task 1：模型和迁移静态合同测试。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_new_model_files_define_four_tables():
    route_models = _read("app/route_book/models.py")
    meetup_models = _read("app/meetup/models.py")

    assert '__tablename__ = "route_books"' in route_models
    assert '__tablename__ = "meetups"' in meetup_models
    assert '__tablename__ = "meetup_participants"' in meetup_models
    assert '__tablename__ = "meetup_media"' in meetup_models


def test_meetup_constraints_match_spec():
    models = _read("app/meetup/models.py")

    assert "ck_meetups_status" in models
    assert "DRAFT" in models and "OPEN" in models and "CANCELLED" in models and "COMPLETED" in models
    assert "ck_meetups_pace_level" in models
    assert "relaxed" in models and "cruise" in models and "training" in models and "race" in models
    assert "ck_meetups_max" in models
    assert "ck_meetups_city" in models
    assert "ck_meetups_time_order" in models
    assert "estimated_end_time > start_time" in models
    assert "uq_meetups_creator_draft" in models
    assert "postgresql_where=text(\"status = 'DRAFT'\")" in models


def test_route_book_orphan_semantics_are_preserved():
    models = _read("app/route_book/models.py")

    assert "ck_route_books_file_type_source" in models
    assert "source_activity_id" in models
    assert "ondelete=\"SET NULL\"" in models
    assert "source = 'activity_derived'" in models
    assert "tencent_direction" in models
    assert "source_activity_id IS NOT NULL" not in models


def test_tencent_direction_migration_extends_route_book_source():
    migrations = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "migrations/versions").glob("*.py"))

    assert "tencent_direction" in migrations
    assert "ck_route_books_source" in migrations
    assert "ck_route_books_file_type_source" in migrations


def test_tencent_direction_migration_revision_fits_alembic_version_column():
    migration = _read("migrations/versions/20260602_route_book_tencent_direction.py")
    revision_line = next(line for line in migration.splitlines() if line.startswith("revision = "))
    revision = revision_line.split('"')[1]

    assert len(revision) <= 32


def test_tencent_direction_migration_downgrade_aborts_with_existing_rows():
    migration = _read("migrations/versions/20260602_route_book_tencent_direction.py")

    assert "SELECT 1 FROM route_books WHERE source = 'tencent_direction' LIMIT 1" in migration
    assert "RuntimeError" in migration
    assert "不能回滚" in migration


def test_alembic_imports_new_models():
    env = _read("migrations/env.py")

    assert "import app.route_book.models" in env
    assert "import app.meetup.models" in env


def test_migration_downgrade_drops_children_before_parents():
    migration = _read("migrations/versions/20260528_meetup_route_book.py")

    order = [
        'op.drop_table("meetup_media")',
        'op.drop_table("meetup_participants")',
        'op.drop_table("meetups")',
        'op.drop_table("route_books")',
    ]
    positions = [migration.index(item) for item in order]
    assert positions == sorted(positions)
