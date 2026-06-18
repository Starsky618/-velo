"""路线认知 Batch 5 测试——给正式 segment 进入认知系统装上可信门禁。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import JSONB


def _check_sql(table, name: str) -> str:
    checks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    ]
    assert checks
    return str(checks[0].sqltext)


def _composite_fk(table, name: str) -> ForeignKeyConstraint:
    fks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    ]
    assert fks
    return fks[0]


def _unique_constraint_columns(table, name: str) -> set[str]:
    uniques = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name == name
    ]
    assert uniques
    return {column.name for column in uniques[0].columns}


def _constraint_block(path: str, constraint_name: str) -> str:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if constraint_name in line:
            start = index
            while (
                start > 0
                and "ForeignKeyConstraint(" not in lines[start]
                and "op.create_foreign_key(" not in lines[start]
            ):
                start -= 1

            end = index
            while end < len(lines):
                if end > index and lines[end].strip() in {")", "),"}:
                    return "\n".join(lines[start : end + 1])
                end += 1
            return "\n".join(lines[start:])
    raise AssertionError(f"{constraint_name} not found in {path}")


def test_batch5_models_declare_segment_source_and_whitelist_tables():
    from app.route_cognition.models import RouteCognitionSegment, SegmentGeometrySource

    assert SegmentGeometrySource.__tablename__ == "segment_geometry_sources"
    assert RouteCognitionSegment.__tablename__ == "route_cognition_segments"

    assert {
        "segment_id",
        "source_type",
        "source_activity_id",
        "source_file_id",
        "geometry_hash",
        "normalization_version",
        "quality_status",
    } <= set(SegmentGeometrySource.__table__.c.keys())
    assert {
        "segment_id",
        "primary_geometry_source_id",
        "review_basis",
        "eligibility_status",
        "accepted_judgment_run_id",
        "reviewed_at",
    } <= set(RouteCognitionSegment.__table__.c.keys())
    assert isinstance(SegmentGeometrySource.__table__.c.quality_metrics_json.type, JSONB)


def test_batch5_models_declare_required_checks_and_composite_fk():
    from app.route_cognition.models import RouteCognitionSegment, SegmentGeometrySource

    source_type_sql = _check_sql(SegmentGeometrySource.__table__, "ck_segment_geometry_sources_source_type")
    assert "activity_clip" in source_type_sql
    assert "admin_import" in source_type_sql
    assert "legacy_existing" not in source_type_sql

    quality_sql = _check_sql(SegmentGeometrySource.__table__, "ck_segment_geometry_sources_quality_status")
    assert "verified" in quality_sql
    assert "needs_review" in quality_sql
    assert "rejected" in quality_sql
    assert "deprecated" in quality_sql
    assert " raw" not in quality_sql
    assert "simplified" not in quality_sql

    coord_sql = _check_sql(SegmentGeometrySource.__table__, "ck_segment_geometry_sources_coordinate_system")
    assert "wgs84" in coord_sql
    assert "gcj02" in coord_sql

    index_sql = _check_sql(SegmentGeometrySource.__table__, "ck_segment_geometry_sources_index_order")
    assert "source_start_index" in index_sql
    assert "source_end_index" in index_sql
    assert "< source_end_index" in index_sql
    assert "<=" not in index_sql

    material_sql = _check_sql(SegmentGeometrySource.__table__, "ck_segment_geometry_sources_material_pointer")
    assert "source_content_hash IS NOT NULL" in material_sql
    assert "source_file_id IS NOT NULL" in material_sql
    assert "source_url IS NOT NULL" in material_sql

    review_basis_sql = _check_sql(RouteCognitionSegment.__table__, "ck_route_cognition_segments_review_basis")
    assert "provenance_verified" in review_basis_sql
    assert "legacy_reviewed" in review_basis_sql

    eligibility_sql = _check_sql(
        RouteCognitionSegment.__table__,
        "ck_route_cognition_segments_eligibility_status",
    )
    assert "active" in eligibility_sql
    assert "suspended" in eligibility_sql
    assert "deprecated" in eligibility_sql
    assert "eligible" not in eligibility_sql
    assert "needs_review" not in eligibility_sql
    assert "blocked" not in eligibility_sql
    assert "retired" not in eligibility_sql

    source_fk = _composite_fk(
        RouteCognitionSegment.__table__,
        "fk_route_cognition_segments_primary_source_segment",
    )
    assert {element.parent.name for element in source_fk.elements} == {
        "primary_geometry_source_id",
        "segment_id",
    }
    assert source_fk.ondelete is None

    hash_fk = _composite_fk(
        RouteCognitionSegment.__table__,
        "fk_route_cognition_segments_primary_source_geometry_hash",
    )
    assert {element.parent.name for element in hash_fk.elements} == {
        "primary_geometry_source_id",
        "segment_id",
        "geometry_hash",
    }
    assert hash_fk.ondelete is None

    assert _unique_constraint_columns(
        SegmentGeometrySource.__table__,
        "uq_segment_geometry_sources_id_segment_geometry_hash",
    ) == {"id", "segment_id", "geometry_hash"}


def test_batch5_migration_builds_only_segment_source_and_whitelist_scope():
    migration = "migrations/versions/20260618_route_cognition_batch5.py"
    migration_text = Path(migration).read_text(encoding="utf-8")

    assert '"segment_geometry_sources"' in migration_text
    assert '"route_cognition_segments"' in migration_text
    assert '"segment_submissions"' not in migration_text
    assert '"route_collections"' not in migration_text
    assert '"concept_nodes"' not in migration_text
    assert '"route_segments"' not in migration_text
    assert "candidate" not in migration_text
    assert "external search" not in migration_text


def test_batch5_migration_composite_source_fk_does_not_set_null():
    migration = "migrations/versions/20260618_route_cognition_batch5.py"
    assert 'ondelete="SET NULL"' not in _constraint_block(
        migration,
        "fk_route_cognition_segments_primary_source_segment",
    )
    assert 'ondelete="SET NULL"' not in _constraint_block(
        migration,
        "fk_route_cognition_segments_primary_source_geometry_hash",
    )


def test_batch5_migration_declares_source_hash_unique_and_fk():
    migration = "migrations/versions/20260618_route_cognition_batch5.py"
    migration_text = Path(migration).read_text(encoding="utf-8")

    assert "uq_segment_geometry_sources_id_segment_geometry_hash" in migration_text
    assert "fk_route_cognition_segments_primary_source_geometry_hash" in migration_text
    assert "ck_segment_geometry_sources_material_pointer" in migration_text
    assert '"geometry_hash"' in _constraint_block(
        migration,
        "fk_route_cognition_segments_primary_source_geometry_hash",
    )


@pytest.fixture()
def batch5_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_batch5_tables(db)
    _create_batch5_sqlite_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_batch5_tables(db)


def test_can_create_segment_geometry_source(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db)

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 1


@pytest.mark.parametrize("source_type", ["bad_type", "legacy_existing"])
def test_invalid_and_legacy_source_type_are_rejected(db, batch5_sqlite_tables, source_type):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_source(db, source_type=source_type)


def test_invalid_quality_status_is_rejected(db, batch5_sqlite_tables):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_source(db, quality_status="approved")


def test_activity_clip_requires_durable_content_hash(db, batch5_sqlite_tables):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_source(db, source_type="activity_clip", source_content_hash=None)


@pytest.mark.parametrize("source_type", ["gpx_upload", "fit_upload", "admin_import"])
def test_file_and_import_sources_require_a_material_pointer(db, batch5_sqlite_tables, source_type):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_source(
            db,
            source_type=source_type,
            source_activity_id=None,
            source_file_id=None,
            source_url=None,
            source_content_hash=None,
        )


def test_file_source_can_use_content_hash_as_material_pointer(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(
        db,
        source_type="gpx_upload",
        source_activity_id=None,
        source_content_hash="content-hash-a",
    )

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 1


def test_file_source_can_use_file_id_without_content_hash(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(
        db,
        source_type="gpx_upload",
        source_activity_id=None,
        source_file_id="file-1",
        source_content_hash=None,
    )

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 1


@pytest.mark.parametrize("quality_status", ["raw", "simplified"])
def test_processing_states_are_not_geometry_source_quality_status(db, batch5_sqlite_tables, quality_status):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_source(db, quality_status=quality_status)


def test_source_start_index_must_be_less_than_end_index(db, batch5_sqlite_tables):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_source(db, source_start_index=7, source_end_index=7)


@pytest.mark.parametrize("column", ["geometry_hash", "normalization_version"])
def test_source_requires_geometry_hash_and_normalization_version(db, batch5_sqlite_tables, column):
    _seed_batch5_base(db)
    values = {
        "id": 1,
        "segment_id": 1,
        "source_type": "activity_clip",
        "source_activity_id": 1,
        "source_file_id": None,
        "geometry_hash": "geom-hash-a",
        "source_content_hash": "content-hash-a",
        "normalization_version": "norm-v1",
        "quality_status": "verified",
    }
    values[column] = None

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                """
                INSERT INTO segment_geometry_sources (
                    id, segment_id, source_type, source_activity_id, source_file_id,
                    geometry_hash, source_content_hash, normalization_version, quality_status
                )
                VALUES (
                    :id, :segment_id, :source_type, :source_activity_id, :source_file_id,
                    :geometry_hash, :source_content_hash, :normalization_version, :quality_status
                )
                """
            ),
            values,
        )


def test_legacy_reviewed_whitelist_can_be_created_without_source(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_whitelist(db, review_basis="legacy_reviewed", primary_geometry_source_id=None)

    row = db.execute(text("SELECT primary_geometry_source_id FROM route_cognition_segments")).one()
    assert row.primary_geometry_source_id is None


def test_provenance_verified_whitelist_can_be_created_with_source(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db)
    _insert_whitelist(db, review_basis="provenance_verified", primary_geometry_source_id=1)

    assert db.execute(text("SELECT count(*) FROM route_cognition_segments")).scalar_one() == 1


def test_provenance_verified_geometry_hash_must_match_primary_source(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db, geometry_hash="geom-hash-source")

    with pytest.raises(IntegrityError):
        _insert_whitelist(
            db,
            review_basis="provenance_verified",
            primary_geometry_source_id=1,
            geometry_hash="geom-hash-other",
        )


def test_legacy_reviewed_does_not_need_matching_geometry_source_hash(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_whitelist(
        db,
        review_basis="legacy_reviewed",
        primary_geometry_source_id=None,
        geometry_hash="legacy-reviewed-hash",
    )

    row = db.execute(text("SELECT geometry_hash FROM route_cognition_segments")).one()
    assert row.geometry_hash == "legacy-reviewed-hash"


def test_provenance_verified_without_source_is_rejected(db, batch5_sqlite_tables):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_whitelist(db, review_basis="provenance_verified", primary_geometry_source_id=None)


def test_legacy_reviewed_with_source_is_rejected(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db)

    with pytest.raises(IntegrityError):
        _insert_whitelist(db, review_basis="legacy_reviewed", primary_geometry_source_id=1)


def test_whitelist_requires_accepted_judgment_run(db, batch5_sqlite_tables):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_whitelist(
            db,
            review_basis="legacy_reviewed",
            primary_geometry_source_id=None,
            accepted_judgment_run_id=None,
        )


def test_whitelist_requires_reviewed_at(db, batch5_sqlite_tables):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_whitelist(
            db,
            review_basis="legacy_reviewed",
            primary_geometry_source_id=None,
            reviewed_at=None,
        )


@pytest.mark.parametrize("eligibility_status", ["eligible", "needs_review", "blocked", "retired"])
def test_pre_review_states_are_not_whitelist_eligibility_status(db, batch5_sqlite_tables, eligibility_status):
    _seed_batch5_base(db)

    with pytest.raises(IntegrityError):
        _insert_whitelist(
            db,
            review_basis="legacy_reviewed",
            primary_geometry_source_id=None,
            eligibility_status=eligibility_status,
        )


def test_source_from_segment_a_cannot_be_attached_to_segment_b(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db, id=1, segment_id=1)

    with pytest.raises(IntegrityError):
        _insert_whitelist(
            db,
            segment_id=2,
            review_basis="provenance_verified",
            primary_geometry_source_id=1,
        )


def test_same_segment_cannot_be_inserted_twice_into_whitelist(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_whitelist(db, review_basis="legacy_reviewed", primary_geometry_source_id=None)

    with pytest.raises(IntegrityError):
        _insert_whitelist(db, review_basis="legacy_reviewed", primary_geometry_source_id=None)


def test_same_geometry_source_cannot_be_reused_by_two_whitelist_rows(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db, id=1, segment_id=1)
    _insert_whitelist(db, segment_id=1, review_basis="provenance_verified", primary_geometry_source_id=1)

    with pytest.raises(IntegrityError):
        _insert_whitelist(db, segment_id=2, review_basis="provenance_verified", primary_geometry_source_id=1)


def test_deleting_referenced_judgment_run_is_restricted(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_whitelist(db, review_basis="legacy_reviewed", primary_geometry_source_id=None)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM judgment_runs WHERE id = 1"))
    db.rollback()

    assert db.execute(text("SELECT count(*) FROM route_cognition_segments")).scalar_one() == 1


def test_deleting_referenced_segment_does_not_orphan_whitelist(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_whitelist(db, review_basis="legacy_reviewed", primary_geometry_source_id=None)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM segments WHERE id = 1"))
    db.rollback()

    assert db.execute(text("SELECT count(*) FROM route_cognition_segments WHERE segment_id = 1")).scalar_one() == 1


def test_deleting_source_activity_sets_geometry_source_activity_to_null(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db)
    db.commit()

    db.execute(text("DELETE FROM activities WHERE id = 1"))

    row = db.execute(text("SELECT source_activity_id FROM segment_geometry_sources WHERE id = 1")).one()
    assert row.source_activity_id is None


def test_deleting_source_creator_sets_geometry_source_created_by_to_null(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_source(db)
    db.commit()

    db.execute(text("DELETE FROM users WHERE id = 1"))

    row = db.execute(text("SELECT created_by FROM segment_geometry_sources WHERE id = 1")).one()
    assert row.created_by is None


def test_deleting_reviewer_sets_whitelist_reviewed_by_to_null(db, batch5_sqlite_tables):
    _seed_batch5_base(db)
    _insert_whitelist(db, review_basis="legacy_reviewed", primary_geometry_source_id=None)
    db.commit()

    db.execute(text("DELETE FROM users WHERE id = 1"))

    row = db.execute(text("SELECT reviewed_by FROM route_cognition_segments WHERE segment_id = 1")).one()
    assert row.reviewed_by is None


def _seed_batch5_base(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO users (id, openid, is_admin)
            VALUES (1, 'batch5_user', 1)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO activities (id, user_id, status)
            VALUES (1, 1, 'completed')
            """
        )
    )
    for segment_id, name in ((1, "segment A"), (2, "segment B")):
        db.execute(
            text(
                """
                INSERT INTO segments (
                    id, name, distance, start_lat, start_lon, end_lat, end_lon, reference_line
                )
                VALUES (
                    :id, :name, 1000.0, 30.0, 120.0, 30.1, 120.1, 'LINESTRING(120 30, 120.1 30.1)'
                )
                """
            ),
            {"id": segment_id, "name": name},
        )
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (id)
            VALUES (1)
            """
        )
    )


def _insert_source(
    db,
    *,
    id: int = 1,
    segment_id: int = 1,
    source_type: str = "activity_clip",
    source_activity_id: int | None = 1,
    source_file_id: str | None = None,
    source_url: str | None = None,
    source_start_index: int | None = 1,
    source_end_index: int | None = 5,
    geometry_hash: str = "geom-hash-a",
    source_content_hash: str | None = "content-hash-a",
    normalization_version: str = "norm-v1",
    quality_status: str = "verified",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO segment_geometry_sources (
                id, segment_id, source_type, source_activity_id, source_file_id, source_url,
                source_start_index, source_end_index, original_coordinate_system,
                geometry_hash, source_content_hash, normalization_version, quality_status, created_by
            )
            VALUES (
                :id, :segment_id, :source_type, :source_activity_id, :source_file_id, :source_url,
                :source_start_index, :source_end_index, 'wgs84',
                :geometry_hash, :source_content_hash, :normalization_version, :quality_status, 1
            )
            """
        ),
        {
            "id": id,
            "segment_id": segment_id,
            "source_type": source_type,
            "source_activity_id": source_activity_id,
            "source_file_id": source_file_id,
            "source_url": source_url,
            "source_start_index": source_start_index,
            "source_end_index": source_end_index,
            "geometry_hash": geometry_hash,
            "source_content_hash": source_content_hash,
            "normalization_version": normalization_version,
            "quality_status": quality_status,
        },
    )


def _insert_whitelist(
    db,
    *,
    segment_id: int = 1,
    primary_geometry_source_id: int | None,
    review_basis: str,
    accepted_judgment_run_id: int | None = 1,
    eligibility_status: str = "active",
    geometry_hash: str = "geom-hash-a",
    reviewed_at: datetime | None = datetime(2026, 6, 18, tzinfo=timezone.utc),
) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_cognition_segments (
                segment_id, primary_geometry_source_id, review_basis, eligibility_status,
                geometry_hash, normalization_version, accepted_judgment_run_id,
                reviewed_by, reviewed_at, review_note
            )
            VALUES (
                :segment_id, :primary_geometry_source_id, :review_basis, :eligibility_status,
                :geometry_hash, 'norm-v1', :accepted_judgment_run_id,
                1, :reviewed_at, 'batch5 test'
            )
            """
        ),
        {
            "segment_id": segment_id,
            "primary_geometry_source_id": primary_geometry_source_id,
            "review_basis": review_basis,
            "accepted_judgment_run_id": accepted_judgment_run_id,
            "eligibility_status": eligibility_status,
            "geometry_hash": geometry_hash,
            "reviewed_at": reviewed_at,
        },
    )


def _create_batch5_sqlite_tables(db) -> None:
    db.execute(text("CREATE TABLE judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE segment_geometry_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_activity_id INTEGER,
                source_file_id TEXT,
                source_url TEXT,
                source_start_index INTEGER,
                source_end_index INTEGER,
                source_start_time DATETIME,
                source_end_time DATETIME,
                original_coordinate_system TEXT,
                geometry_hash TEXT NOT NULL,
                source_content_hash TEXT,
                normalization_version TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                quality_metrics_json TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (source_type IN ('activity_clip', 'gpx_upload', 'fit_upload', 'admin_import')),
                CHECK (quality_status IN ('verified', 'needs_review', 'rejected', 'deprecated')),
                CHECK (original_coordinate_system IS NULL OR original_coordinate_system IN ('wgs84', 'gcj02', 'unknown')),
                CHECK (source_start_index IS NULL OR source_end_index IS NULL OR source_start_index < source_end_index),
                CHECK (
                    (source_type = 'activity_clip' AND source_content_hash IS NOT NULL)
                    OR
                    (
                        source_type IN ('gpx_upload', 'fit_upload', 'admin_import')
                        AND (
                            source_file_id IS NOT NULL
                            OR source_url IS NOT NULL
                            OR source_content_hash IS NOT NULL
                        )
                    )
                ),
                UNIQUE(id, segment_id),
                UNIQUE(id, segment_id, geometry_hash),
                FOREIGN KEY(segment_id) REFERENCES segments(id),
                FOREIGN KEY(source_activity_id) REFERENCES activities(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                primary_geometry_source_id INTEGER UNIQUE,
                review_basis TEXT NOT NULL,
                eligibility_status TEXT NOT NULL,
                geometry_hash TEXT NOT NULL,
                normalization_version TEXT NOT NULL,
                accepted_judgment_run_id INTEGER NOT NULL,
                reviewed_by INTEGER,
                reviewed_at DATETIME NOT NULL,
                review_note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (review_basis IN ('provenance_verified', 'legacy_reviewed')),
                CHECK (eligibility_status IN ('active', 'suspended', 'deprecated')),
                CHECK (accepted_judgment_run_id IS NOT NULL),
                CHECK (geometry_hash IS NOT NULL),
                CHECK (normalization_version IS NOT NULL),
                CHECK (reviewed_at IS NOT NULL),
                CHECK (
                    (review_basis = 'provenance_verified' AND primary_geometry_source_id IS NOT NULL)
                    OR
                    (review_basis = 'legacy_reviewed' AND primary_geometry_source_id IS NULL)
                ),
                FOREIGN KEY(segment_id) REFERENCES segments(id),
                FOREIGN KEY(accepted_judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(primary_geometry_source_id, segment_id)
                    REFERENCES segment_geometry_sources(id, segment_id),
                FOREIGN KEY(primary_geometry_source_id, segment_id, geometry_hash)
                    REFERENCES segment_geometry_sources(id, segment_id, geometry_hash)
            )
            """
        )
    )


def _drop_batch5_tables(db) -> None:
    for table_name in (
        "route_cognition_segments",
        "segment_geometry_sources",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
