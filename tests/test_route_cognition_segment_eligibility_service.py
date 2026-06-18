"""路线认知 Batch 6 测试——确认正式 segment 只能从内部安全入口进白名单。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.route_cognition.geometry_hash import (
    SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    hash_segment_geometry_wkt,
)
from app.route_cognition.services.segment_eligibility import (
    SegmentGeometrySourceInput,
    SegmentEligibilityError,
    admit_legacy_reviewed_segment,
    admit_provenance_verified_segment,
)


def test_segment_geometry_hash_is_stable_for_same_geometry():
    first = hash_segment_geometry_wkt("SRID=4326;LINESTRING(120 30, 120.1 30.1)")
    second = hash_segment_geometry_wkt("  SRID=4326;LINESTRING(120 30,   120.1 30.1)  ")

    assert first == second
    assert len(first) == 64
    assert SEGMENT_GEOMETRY_NORMALIZATION_VERSION == "route_cognition_segment_geometry_v1"


def test_legacy_reviewed_admission_succeeds_with_human_review(db, batch6_sqlite_tables):
    _seed_batch6_base(db)

    row = admit_legacy_reviewed_segment(
        db,
        segment_id=1,
        accepted_judgment_run_id=1,
        reviewer_id=1,
        review_note="人工确认旧赛段可进入路线认知",
    )

    assert row.review_basis == "legacy_reviewed"
    assert row.primary_geometry_source_id is None
    assert row.eligibility_status == "active"
    assert row.geometry_hash
    assert row.normalization_version == SEGMENT_GEOMETRY_NORMALIZATION_VERSION
    assert row.reviewed_by == 1
    assert row.reviewed_at is not None


def test_legacy_reviewed_does_not_create_geometry_source(db, batch6_sqlite_tables):
    _seed_batch6_base(db)

    admit_legacy_reviewed_segment(
        db,
        segment_id=1,
        accepted_judgment_run_id=1,
        reviewer_id=1,
        review_note="人工确认旧赛段可进入路线认知",
    )

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 0


def test_legacy_reviewed_requires_existing_judgment_run(db, batch6_sqlite_tables):
    _seed_batch6_base(db)

    with pytest.raises(SegmentEligibilityError, match="judgment_run"):
        admit_legacy_reviewed_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=999,
            reviewer_id=1,
            review_note="缺 judgment_run 应失败",
        )


def test_legacy_reviewed_rejects_non_human_review_judgment(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_judgment_run(db, id=2, run_type="semantic_agent")

    with pytest.raises(SegmentEligibilityError, match="human_review"):
        admit_legacy_reviewed_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=2,
            reviewer_id=1,
            review_note="semantic agent 不能直接准入",
        )


def test_legacy_reviewed_rejects_unsuccessful_judgment(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_judgment_run(db, id=2, status="failed")

    with pytest.raises(SegmentEligibilityError, match="succeeded"):
        admit_legacy_reviewed_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=2,
            reviewer_id=1,
            review_note="失败 judgment 不能准入",
        )


def test_legacy_reviewed_rejects_unaccepted_confidence_state(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_judgment_run(db, id=2, confidence_state="proposed")

    with pytest.raises(SegmentEligibilityError, match="confidence_state"):
        admit_legacy_reviewed_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=2,
            reviewer_id=1,
            review_note="未接受 judgment 不能准入",
        )


def test_legacy_reviewed_rejects_judgment_for_another_segment(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_judgment_run(db, id=2, segment_id=2)

    with pytest.raises(SegmentEligibilityError, match="segment_id"):
        admit_legacy_reviewed_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=2,
            reviewer_id=1,
            review_note="跨 segment judgment 不能准入",
        )


def test_legacy_reviewed_rejects_duplicate_segment(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    admit_legacy_reviewed_segment(
        db,
        segment_id=1,
        accepted_judgment_run_id=1,
        reviewer_id=1,
        review_note="首次准入",
    )

    with pytest.raises(SegmentEligibilityError, match="already admitted"):
        admit_legacy_reviewed_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            review_note="重复准入",
        )


def test_legacy_reviewed_does_not_auto_backfill_other_segments(db, batch6_sqlite_tables):
    _seed_batch6_base(db)

    admit_legacy_reviewed_segment(
        db,
        segment_id=1,
        accepted_judgment_run_id=1,
        reviewer_id=1,
        review_note="只准入一个 segment",
    )

    rows = db.execute(text("SELECT segment_id FROM route_cognition_segments ORDER BY segment_id")).all()
    assert [row.segment_id for row in rows] == [1]


def test_provenance_verified_admission_succeeds_with_verified_source(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    current_segment_hash = _current_segment_hash(db)
    _insert_source(db, geometry_hash=current_segment_hash, normalization_version="source-norm-v1")

    row = admit_provenance_verified_segment(
        db,
        segment_id=1,
        accepted_judgment_run_id=1,
        reviewer_id=1,
        primary_geometry_source_id=1,
        review_note="真实来源已核验",
    )

    assert row.review_basis == "provenance_verified"
    assert row.primary_geometry_source_id == 1
    assert row.eligibility_status == "active"
    assert row.geometry_hash == current_segment_hash
    assert row.normalization_version == "source-norm-v1"


def test_provenance_verified_rejects_existing_source_with_mismatched_geometry_hash(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_source(db, geometry_hash="not-current-segment-hash")

    with pytest.raises(SegmentEligibilityError, match="current segment geometry_hash"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            primary_geometry_source_id=1,
            review_note="source hash 不能和 segment 当前线条不一致",
        )


def test_provenance_verified_rejects_source_from_another_segment(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_source(db, segment_id=2)

    with pytest.raises(SegmentEligibilityError, match="source.segment_id"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            primary_geometry_source_id=1,
            review_note="错挂 source 应失败",
        )


@pytest.mark.parametrize("quality_status", ["needs_review", "rejected", "deprecated"])
def test_provenance_verified_rejects_non_verified_source_quality(
    db,
    batch6_sqlite_tables,
    quality_status,
):
    _seed_batch6_base(db)
    _insert_source(db, quality_status=quality_status)

    with pytest.raises(SegmentEligibilityError, match="verified"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            primary_geometry_source_id=1,
            review_note="非 verified source 不能准入",
        )


def test_provenance_verified_rejects_source_without_geometry_hash(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_source(db, geometry_hash="")

    with pytest.raises(SegmentEligibilityError, match="geometry_hash"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            primary_geometry_source_id=1,
            review_note="空 hash 不能准入",
        )


def test_provenance_verified_rejects_source_without_normalization_version(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_source(db, normalization_version="")

    with pytest.raises(SegmentEligibilityError, match="normalization_version"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            primary_geometry_source_id=1,
            review_note="空 normalization version 不能准入",
        )


def test_provenance_verified_can_create_verified_source_in_same_transaction(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    current_segment_hash = _current_segment_hash(db)

    row = admit_provenance_verified_segment(
        db,
        segment_id=1,
        accepted_judgment_run_id=1,
        reviewer_id=1,
        source_input=SegmentGeometrySourceInput(
            source_type="admin_import",
            source_file_id="files/segment-1.gpx",
            geometry_hash=current_segment_hash,
            normalization_version="source-norm-v1",
            quality_status="verified",
        ),
        review_note="同事务创建来源并准入",
    )

    assert row.primary_geometry_source_id is not None
    assert row.geometry_hash == current_segment_hash
    source_hash = db.execute(text("SELECT geometry_hash FROM segment_geometry_sources WHERE id = :id"), {"id": row.primary_geometry_source_id}).scalar_one()
    assert source_hash == current_segment_hash
    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 1


def test_provenance_verified_rejects_created_source_with_mismatched_geometry_hash(db, batch6_sqlite_tables):
    _seed_batch6_base(db)

    with pytest.raises(SegmentEligibilityError, match="current segment geometry_hash"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            source_input=SegmentGeometrySourceInput(
                source_type="admin_import",
                source_file_id="files/segment-1.gpx",
                geometry_hash="not-current-segment-hash",
                normalization_version="source-norm-v1",
                quality_status="verified",
            ),
            review_note="新建 source hash 也必须等于当前 segment 线条",
        )

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 0


def test_provenance_verified_refuses_created_source_without_durable_pointer(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    current_segment_hash = _current_segment_hash(db)

    with pytest.raises(SegmentEligibilityError, match="durable material pointer"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            source_input=SegmentGeometrySourceInput(
                source_type="admin_import",
                geometry_hash=current_segment_hash,
                normalization_version="source-norm-v1",
                quality_status="verified",
            ),
            review_note="缺长期来源指针应失败",
        )

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 0


def test_provenance_verified_refuses_activity_clip_without_content_hash(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    current_segment_hash = _current_segment_hash(db)

    with pytest.raises(SegmentEligibilityError, match="source_content_hash"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            source_input=SegmentGeometrySourceInput(
                source_type="activity_clip",
                source_activity_id=1,
                geometry_hash=current_segment_hash,
                normalization_version="source-norm-v1",
                quality_status="verified",
            ),
            review_note="activity_clip 不能只靠 activity_id",
        )


@pytest.mark.parametrize("start_index,end_index", [(3, 3), (4, 3)])
def test_provenance_verified_refuses_created_source_with_invalid_index_order(
    db,
    batch6_sqlite_tables,
    start_index,
    end_index,
):
    _seed_batch6_base(db)
    current_segment_hash = _current_segment_hash(db)

    with pytest.raises(SegmentEligibilityError, match="source_start_index"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            source_input=SegmentGeometrySourceInput(
                source_type="admin_import",
                source_file_id="files/segment-1.gpx",
                source_start_index=start_index,
                source_end_index=end_index,
                geometry_hash=current_segment_hash,
                normalization_version="source-norm-v1",
                quality_status="verified",
            ),
            review_note="裁剪索引必须严格递增",
        )

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 0


def test_provenance_verified_refuses_created_source_with_invalid_coordinate_system(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    current_segment_hash = _current_segment_hash(db)

    with pytest.raises(SegmentEligibilityError, match="original_coordinate_system"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            source_input=SegmentGeometrySourceInput(
                source_type="admin_import",
                source_file_id="files/segment-1.gpx",
                original_coordinate_system="bd09",
                geometry_hash=current_segment_hash,
                normalization_version="source-norm-v1",
                quality_status="verified",
            ),
            review_note="坐标系必须在 Batch 5 白名单内",
        )

    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 0


def test_provenance_verified_rejects_duplicate_source_reuse(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_source(db)
    admit_provenance_verified_segment(
        db,
        segment_id=1,
        accepted_judgment_run_id=1,
        reviewer_id=1,
        primary_geometry_source_id=1,
        review_note="首次准入",
    )

    with pytest.raises(SegmentEligibilityError, match="already admitted"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            primary_geometry_source_id=1,
            review_note="重复使用 source",
        )


def test_provenance_verified_rejects_existing_source_without_durable_pointer(db, batch6_sqlite_tables):
    _seed_batch6_base(db)
    _insert_source(
        db,
        source_type="gpx_upload",
        source_file_id=None,
        source_url=None,
        source_content_hash=None,
    )

    with pytest.raises(SegmentEligibilityError, match="durable material pointer"):
        admit_provenance_verified_segment(
            db,
            segment_id=1,
            accepted_judgment_run_id=1,
            reviewer_id=1,
            primary_geometry_source_id=1,
            review_note="缺长期来源指针不能准入",
        )


def test_batch6_does_not_create_public_route_cognition_router():
    assert not Path("app/route_cognition/router.py").exists()


def test_batch6_does_not_add_migration():
    migration_names = {path.name for path in Path("migrations/versions").glob("*route_cognition_batch*.py")}
    assert migration_names == {
        "20260618_route_cognition_batch4.py",
        "20260618_route_cognition_batch5.py",
    }


def test_batch6_does_not_touch_route_content_surfaces():
    changed_files = _git_tracked_and_diff_names()
    assert not any(path.startswith("content/routes/") for path in changed_files)
    assert not any(path.endswith("guide.md") for path in changed_files)
    assert "route_guides.content_md" not in "\n".join(changed_files)


def test_batch6_does_not_touch_old_segment_surfaces():
    changed_files = _git_tracked_and_diff_names()
    changed_text = "\n".join(changed_files)
    assert "segment_efforts" not in changed_text
    assert "segments.reference_line" not in changed_text


@pytest.fixture()
def batch6_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_batch6_tables(db)
    _create_batch6_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_batch6_tables(db)


def _git_tracked_and_diff_names() -> list[str]:
    import subprocess

    commands = [
        ["git", "show", "--name-only", "--format=", "HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    names: set[str] = set()
    for command in commands:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        names.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(names)


def _seed_batch6_base(db) -> None:
    db.execute(text("INSERT INTO users (id, openid, is_admin) VALUES (1, 'batch6_reviewer', 1)"))
    db.execute(text("INSERT INTO activities (id, user_id, status) VALUES (1, 1, 'completed')"))
    for segment_id, name in ((1, "segment A"), (2, "segment B")):
        db.execute(
            text(
                """
                INSERT INTO segments (
                    id, name, distance, start_lat, start_lon, end_lat, end_lon, reference_line
                )
                VALUES (
                    :id, :name, 1000.0, 30.0, 120.0, 30.1, 120.1, :reference_line
                )
                """
            ),
            {
                "id": segment_id,
                "name": name,
                "reference_line": f"SRID=4326;LINESTRING(120 {30 + segment_id}, 120.1 {30.1 + segment_id})",
            },
        )
    _insert_judgment_run(db, id=1, segment_id=1)


def _insert_judgment_run(
    db,
    *,
    id: int,
    run_type: str = "human_review",
    status: str = "succeeded",
    confidence_state: str = "human_accepted",
    segment_id: int | None = 1,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (
                id, run_type, status, trigger_type, segment_id, confidence_state, created_by_user_id
            )
            VALUES (
                :id, :run_type, :status, 'manual_segment_admission',
                :segment_id, :confidence_state, 1
            )
            """
        ),
        {
            "id": id,
            "run_type": run_type,
            "status": status,
            "segment_id": segment_id,
            "confidence_state": confidence_state,
        },
    )


def _current_segment_hash(db, segment_id: int = 1) -> str:
    reference_line_wkt = db.execute(
        text("SELECT ST_AsText(reference_line) FROM segments WHERE id = :segment_id"),
        {"segment_id": segment_id},
    ).scalar_one()
    return hash_segment_geometry_wkt(reference_line_wkt)


def _insert_source(
    db,
    *,
    id: int = 1,
    segment_id: int = 1,
    source_type: str = "activity_clip",
    source_activity_id: int | None = 1,
    source_file_id: str | None = None,
    source_url: str | None = None,
    source_content_hash: str | None = "content-hash-a",
    geometry_hash: str | None = None,
    normalization_version: str = "norm-v1",
    quality_status: str = "verified",
) -> None:
    if geometry_hash is None:
        geometry_hash = _current_segment_hash(db, segment_id)
    db.execute(
        text(
            """
            INSERT INTO segment_geometry_sources (
                id, segment_id, source_type, source_activity_id, source_file_id, source_url,
                geometry_hash, source_content_hash, normalization_version, quality_status, created_by
            )
            VALUES (
                :id, :segment_id, :source_type, :source_activity_id, :source_file_id, :source_url,
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
            "source_content_hash": source_content_hash,
            "geometry_hash": geometry_hash,
            "normalization_version": normalization_version,
            "quality_status": quality_status,
        },
    )


def _create_batch6_tables(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE judgment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                segment_id INTEGER,
                confidence_state TEXT NOT NULL,
                created_by_user_id INTEGER
            )
            """
        )
    )
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


def _drop_batch6_tables(db) -> None:
    for table_name in (
        "route_cognition_segments",
        "segment_geometry_sources",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
