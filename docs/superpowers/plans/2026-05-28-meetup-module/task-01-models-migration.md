# Task 1: Models And Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the four new tables and make Alembic aware of the two new modules.

**Architecture:** This task pours the concrete slab. No API or product action works until `route_books`, `meetups`, `meetup_participants`, and `meetup_media` exist with the exact constraints from spec §4.

**Tech Stack:** SQLAlchemy ORM, Alembic, GeoAlchemy2, PostgreSQL partial indexes, pytest static checks.

---

## User Story

陈哥周五晚上想发起周六约骑。Before this task, the database has nowhere to store his route drawing, meetup card, joined riders, or media. After this task, later tasks can safely build the user journey without squeezing meetup fields into `users`, `activities`, or `segments`.

## Files

- Create: `app/route_book/__init__.py`
- Create: `app/route_book/models.py`
- Create: `app/meetup/__init__.py`
- Create: `app/meetup/models.py`
- Create: `migrations/versions/20260528_meetup_route_book.py`
- Create: `tests/test_meetup_models.py`
- Modify: `migrations/env.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_meetup_models.py`

## Evidence Anchors

- [✓ grep] table fields and constraints: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:82-180`.
- [✓ grep] partial unique precedent: `app/notification/models.py:130-134`.
- [✓ grep] Alembic imports all model modules explicitly: `migrations/env.py:22-31`.
- [✓ grep] SQLite tests use simplified tables for PG-only columns: `tests/conftest.py:86-90`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写模型和迁移；复审时确认测试者≠实现者。

## Steps

- [ ] **Step 1: Read the exact contracts**

Run:

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '80,180p'
nl -ba migrations/env.py | sed -n '22,32p'
nl -ba tests/conftest.py | sed -n '80,291p'
```

Expected: you see 4 table contracts, existing model-import pattern, and SQLite simplified-table pattern.

- [ ] **Step 2: Write the red static tests**

Create `tests/test_meetup_models.py` with this complete code:

```python
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
    assert "uq_meetups_creator_draft" in models
    assert "postgresql_where=text(\"status = 'DRAFT'\")" in models


def test_route_book_orphan_semantics_are_preserved():
    models = _read("app/route_book/models.py")

    assert "ck_route_books_file_type_source" in models
    assert "source_activity_id" in models
    assert "ondelete=\"SET NULL\"" in models
    assert "source = 'activity_derived'" in models
    assert "source_activity_id IS NOT NULL" not in models


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
```

- [ ] **Step 3: Run red tests**

Run:

```bash
python3 -m pytest tests/test_meetup_models.py -q
```

Expected: FAIL because the new files and imports do not exist yet.

- [ ] **Step 4: Create module init files**

Create `app/route_book/__init__.py`:

```python
"""路书模块——用户自己保存的路线图纸。"""
```

Create `app/meetup/__init__.py`:

```python
"""约骑模块——把一条路线变成一次有时间、有名额、有参与者的集体骑行。"""
```

- [ ] **Step 5: Add `app/route_book/models.py`**

Use this complete file:

```python
"""
路书数据模型——用户自己的"路线图纸库"。

这个文件只定义 route_books 表：它保存用户上传或从活动衍生出来的路线线条。
操作注意事项：source_activity_id 允许后续变成 NULL，这是源活动被删后的合法孤儿态。
输入输出：service 写入 name / distance / reference_line / source，meetup 读取这些字段做快照。
"""

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.sql import func

from app.database import Base


class RouteBook(Base):
    """路书表——用户保存的一张路线图纸。"""

    __tablename__ = "route_books"

    id = Column(Integer, primary_key=True, autoincrement=True)
    creator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(128), nullable=False)
    distance = Column(Float, nullable=False)
    climb = Column(Float, nullable=True)
    reference_line = Column(Geometry("LINESTRING", srid=4326), nullable=False)
    file_id = Column(String(512), nullable=True)
    file_type = Column(String(8), nullable=True)
    source = Column(String(32), nullable=False)
    source_activity_id = Column(Integer, ForeignKey("activities.id", ondelete="SET NULL"), nullable=True)
    city = Column(String(32), nullable=False, server_default="unknown")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_route_books_geom", "reference_line", postgresql_using="gist"),
        Index("idx_route_books_creator_created", "creator_id", text("created_at DESC")),
        CheckConstraint(
            "source IN ('file_upload', 'activity_derived')",
            name="ck_route_books_source",
        ),
        CheckConstraint(
            "city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
            name="ck_route_books_city",
        ),
        CheckConstraint(
            "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
            "AND source_activity_id IS NULL) OR "
            "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL)",
            name="ck_route_books_file_type_source",
        ),
    )
```

- [ ] **Step 6: Add `app/meetup/models.py`**

Use this complete file:

```python
"""
约骑数据模型——一张路线图纸上的"集合通知单 + 报名名单 + 相册"。

这个文件定义 meetups、meetup_participants、meetup_media 三张表。
操作注意事项：DRAFT 只允许每个 creator 保留一份；OPEN 之后快照字段不再跟 route_book 或 segment 改名漂移。
输入输出：service 写状态机，router 读这些字段返回前端卡片。
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import false, func

from app.database import Base


class Meetup(Base):
    """约骑主表——一次即将发生或已经结束的集体骑行。"""

    __tablename__ = "meetups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    creator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, server_default="DRAFT")
    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="SET NULL"), nullable=True)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"), nullable=True)
    snapshot_route_name = Column(String(128), nullable=False)
    snapshot_distance = Column(Float, nullable=False)
    snapshot_climb = Column(Float, nullable=True)
    snapshot_city = Column(String(32), nullable=False, server_default="unknown")
    start_time = Column(DateTime(timezone=True), nullable=False)
    estimated_end_time = Column(DateTime(timezone=True), nullable=False)
    meeting_point = Column(String(128), nullable=False)
    pace_level = Column(String(16), nullable=False)
    max_participants = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_meetups_status_start", "status", "start_time"),
        Index("idx_meetups_creator_status", "creator_id", "status"),
        Index(
            "uq_meetups_creator_draft",
            "creator_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'CANCELLED', 'COMPLETED')",
            name="ck_meetups_status",
        ),
        CheckConstraint(
            "pace_level IN ('relaxed', 'cruise', 'training', 'race')",
            name="ck_meetups_pace_level",
        ),
        CheckConstraint(
            "max_participants >= 2 AND max_participants <= 20",
            name="ck_meetups_max",
        ),
        CheckConstraint(
            "snapshot_city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
            name="ck_meetups_city",
        ),
    )


class MeetupParticipant(Base):
    """约骑报名表——谁已经占了这次约骑的一个名额。"""

    __tablename__ = "meetup_participants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meetup_id = Column(Integer, ForeignKey("meetups.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_creator = Column(Boolean, nullable=False, server_default=false())
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("meetup_id", "user_id", name="uq_meetup_participant_user"),
        Index("idx_meetup_participants_user_joined", "user_id", "joined_at"),
    )


class MeetupMedia(Base):
    """约骑媒体表——创建者给约骑卡片上传的图片或视频。"""

    __tablename__ = "meetup_media"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meetup_id = Column(Integer, ForeignKey("meetups.id", ondelete="CASCADE"), nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(16), nullable=False)
    file_id = Column(String(512), nullable=False)
    caption = Column(String(128), nullable=True)
    seq = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_meetup_media_meetup_seq", "meetup_id", "seq"),
        CheckConstraint("type IN ('image', 'video')", name="ck_meetup_media_type"),
    )
```

- [ ] **Step 7: Add Alembic migration**

Create `migrations/versions/20260528_meetup_route_book.py`. Use `python3 -m alembic heads` first; set `down_revision` to the current head shown in this repo, which is expected to be `sprint10_daily_training_load` unless another migration has landed.

Implementation block:

```python
"""Create route_book and meetup tables.

Revision ID: 20260528_meetup_route_book
Revises: sprint10_daily_training_load
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


revision = "20260528_meetup_route_book"
down_revision = "sprint10_daily_training_load"
branch_labels = None
depends_on = None


CITY_CHECK = "IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')"


def upgrade() -> None:
    op.create_table(
        "route_books",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("climb", sa.Float(), nullable=True),
        sa.Column("reference_line", Geometry("LINESTRING", srid=4326), nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=True),
        sa.Column("file_type", sa.String(length=8), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_activity_id", sa.Integer(), nullable=True),
        sa.Column("city", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], name="fk_route_books_creator_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_activity_id"], ["activities.id"], name="fk_route_books_source_activity_id", ondelete="SET NULL"
        ),
        sa.CheckConstraint("source IN ('file_upload', 'activity_derived')", name="ck_route_books_source"),
        sa.CheckConstraint(f"city {CITY_CHECK}", name="ck_route_books_city"),
        sa.CheckConstraint(
            "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
            "AND source_activity_id IS NULL) OR "
            "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL)",
            name="ck_route_books_file_type_source",
        ),
    )
    op.create_index("idx_route_books_geom", "route_books", ["reference_line"], postgresql_using="gist")
    op.create_index("idx_route_books_creator_created", "route_books", ["creator_id", sa.text("created_at DESC")])

    op.create_table(
        "meetups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_route_name", sa.String(length=128), nullable=False),
        sa.Column("snapshot_distance", sa.Float(), nullable=False),
        sa.Column("snapshot_climb", sa.Float(), nullable=True),
        sa.Column("snapshot_city", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estimated_end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meeting_point", sa.String(length=128), nullable=False),
        sa.Column("pace_level", sa.String(length=16), nullable=False),
        sa.Column("max_participants", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], name="fk_meetups_creator_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], name="fk_meetups_segment_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_meetups_route_book_id", ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('DRAFT', 'OPEN', 'CANCELLED', 'COMPLETED')", name="ck_meetups_status"),
        sa.CheckConstraint("pace_level IN ('relaxed', 'cruise', 'training', 'race')", name="ck_meetups_pace_level"),
        sa.CheckConstraint("max_participants >= 2 AND max_participants <= 20", name="ck_meetups_max"),
        sa.CheckConstraint(f"snapshot_city {CITY_CHECK}", name="ck_meetups_city"),
    )
    op.create_index("idx_meetups_status_start", "meetups", ["status", "start_time"])
    op.create_index("idx_meetups_creator_status", "meetups", ["creator_id", "status"])
    op.create_index(
        "uq_meetups_creator_draft",
        "meetups",
        ["creator_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
    )

    op.create_table(
        "meetup_participants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meetup_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_creator", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["meetup_id"], ["meetups.id"], name="fk_meetup_participants_meetup_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_meetup_participants_user_id", ondelete="CASCADE"),
        sa.UniqueConstraint("meetup_id", "user_id", name="uq_meetup_participant_user"),
    )
    op.create_index("idx_meetup_participants_user_joined", "meetup_participants", ["user_id", "joined_at"])

    op.create_table(
        "meetup_media",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meetup_id", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("caption", sa.String(length=128), nullable=True),
        sa.Column("seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["meetup_id"], ["meetups.id"], name="fk_meetup_media_meetup_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], name="fk_meetup_media_uploader_id", ondelete="SET NULL"),
        sa.CheckConstraint("type IN ('image', 'video')", name="ck_meetup_media_type"),
    )
    op.create_index("idx_meetup_media_meetup_seq", "meetup_media", ["meetup_id", "seq"])


def downgrade() -> None:
    op.drop_index("idx_meetup_media_meetup_seq", table_name="meetup_media")
    op.drop_table("meetup_media")
    op.drop_index("idx_meetup_participants_user_joined", table_name="meetup_participants")
    op.drop_table("meetup_participants")
    op.drop_index("uq_meetups_creator_draft", table_name="meetups")
    op.drop_index("idx_meetups_creator_status", table_name="meetups")
    op.drop_index("idx_meetups_status_start", table_name="meetups")
    op.drop_table("meetups")
    op.drop_index("idx_route_books_creator_created", table_name="route_books")
    op.drop_index("idx_route_books_geom", table_name="route_books")
    op.drop_table("route_books")
```

- [ ] **Step 8: Wire Alembic model imports**

In `migrations/env.py`, add below `import app.training.models`:

```python
import app.route_book.models  # noqa: F401 — route_books 表
import app.meetup.models      # noqa: F401 — meetups + participants + media 表
```

- [ ] **Step 9: Extend SQLite test tables**

In `tests/conftest.py`, add simplified tables after `_segment_ai_drafts_table` and before `_notifications_table`:

```python
_route_books_table = Table(
    "route_books",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("creator_id", Integer),
    Column("name", String(128), nullable=False),
    Column("distance", Float, nullable=False),
    Column("climb", Float),
    Column("reference_line", Text),
    Column("file_id", String(512)),
    Column("file_type", String(8)),
    Column("source", String(32), nullable=False),
    Column("source_activity_id", Integer),
    Column("city", String(32), nullable=False, default="unknown"),
    Column("created_at", DateTime(timezone=True)),
)

_meetups_table = Table(
    "meetups",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("creator_id", Integer),
    Column("status", String(16), nullable=False, default="DRAFT"),
    Column("segment_id", Integer),
    Column("route_book_id", Integer),
    Column("snapshot_route_name", String(128), nullable=False),
    Column("snapshot_distance", Float, nullable=False),
    Column("snapshot_climb", Float),
    Column("snapshot_city", String(32), nullable=False, default="unknown"),
    Column("start_time", DateTime(timezone=True), nullable=False),
    Column("estimated_end_time", DateTime(timezone=True), nullable=False),
    Column("meeting_point", String(128), nullable=False),
    Column("pace_level", String(16), nullable=False),
    Column("max_participants", Integer, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("cancelled_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
)

_meetup_participants_table = Table(
    "meetup_participants",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("meetup_id", Integer, nullable=False),
    Column("user_id", Integer, nullable=False),
    Column("is_creator", Boolean, nullable=False, default=False),
    Column("joined_at", DateTime(timezone=True)),
    UniqueConstraint("meetup_id", "user_id", name="uq_meetup_participant_user"),
)

_meetup_media_table = Table(
    "meetup_media",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("meetup_id", Integer, nullable=False),
    Column("uploader_id", Integer),
    Column("type", String(16), nullable=False),
    Column("file_id", String(512), nullable=False),
    Column("caption", String(128)),
    Column("seq", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True)),
)
```

- [ ] **Step 10: Run green tests and migration checks**

Run:

```bash
python3 -m pytest tests/test_meetup_models.py -q
python3 -m alembic heads
python3 -m alembic upgrade head
python3 -m alembic downgrade sprint10_daily_training_load
python3 -m alembic upgrade head
```

Expected: tests pass, Alembic upgrade/downgrade returns without table-order or check-constraint errors.

- [ ] **Step 11: Self-review**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
root = Path("docs/superpowers/plans/2026-05-28-meetup-module")
terms = ["TB" + "D", "TO" + "DO", "fill " + "in", "place" + "holder", "类似 " + "Task"]
for path in root.rglob("*.md"):
    text = path.read_text(encoding="utf-8")
    for term in terms:
        assert term not in text, f"{term} appears in {path}"
print("scan clean")
PY
```

Self-check:

- [ ] Spec coverage: every field in spec §4.1-§4.4 appears in model and migration code.
- [ ] Type consistency: `file_id`, `route_book_id`, `source_activity_id`, and `snapshot_*` spellings match across ORM, migration, and tests.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: no existing module imports `app.meetup` or `app.route_book` in this task.

- [ ] **Step 12: Commit**

```bash
git add app/route_book/__init__.py app/route_book/models.py app/meetup/__init__.py app/meetup/models.py migrations/env.py migrations/versions/20260528_meetup_route_book.py tests/conftest.py tests/test_meetup_models.py
git commit -F - <<'MSG'
feat(meetup): task 1 add route and meetup tables

Create route_books, meetups, meetup_participants, and meetup_media with Alembic visibility and static contract tests.
Keep core tables unchanged and preserve route_book activity-derived orphan semantics.
MSG
```
