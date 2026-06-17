"""路线百科灌库脚本测试——先在模拟仓库里验收路线手册能否安全进库。"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text


FIXTURE_ROUTES = Path(__file__).parent / "fixtures" / "routes"


def _load_script():
    from scripts import import_route_guides

    return import_route_guides


@pytest.fixture()
def route_guide_tables(db):
    from app.route_book.models import RouteBook, RouteGuide, RouteVersion

    if db.bind.dialect.name == "postgresql":
        RouteBook.__table__.create(bind=db.bind, checkfirst=True)
        RouteVersion.__table__.create(bind=db.bind, checkfirst=True)
    else:
        db.execute(text("DROP TABLE IF EXISTS route_guides"))
        db.execute(text("DROP TABLE IF EXISTS route_versions"))
        db.execute(text("DROP TABLE IF EXISTS route_books"))
        db.execute(text(
            """
            CREATE TABLE route_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                name VARCHAR(128) NOT NULL,
                distance FLOAT NOT NULL,
                climb FLOAT,
                reference_line TEXT NOT NULL,
                file_id VARCHAR(512),
                file_type VARCHAR(8),
                source VARCHAR(32) NOT NULL,
                source_activity_id INTEGER,
                city VARCHAR(32) NOT NULL DEFAULT 'unknown',
                is_official BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME,
                visibility VARCHAR(16) NOT NULL DEFAULT 'private',
                publish_status VARCHAR(16) NOT NULL DEFAULT 'draft',
                line_hash VARCHAR(64),
                elevation_profile TEXT,
                current_version_id INTEGER
            )
            """
        ))
        db.execute(text(
            """
            CREATE TABLE route_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_book_id INTEGER NOT NULL,
                version_no INTEGER NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'current',
                created_by INTEGER,
                geometry_source VARCHAR(32) NOT NULL,
                navigation_status VARCHAR(16) NOT NULL DEFAULT 'ready',
                reference_line_snapshot TEXT NOT NULL,
                line_hash VARCHAR(64) NOT NULL,
                distance FLOAT NOT NULL,
                climb FLOAT,
                elevation_profile TEXT,
                point_count INTEGER,
                component_snapshot_hash VARCHAR(64),
                validation_warnings_json TEXT,
                navigation_metadata_json TEXT,
                created_at DATETIME,
                UNIQUE(route_book_id, version_no),
                UNIQUE(id, route_book_id)
            )
            """
        ))
    RouteGuide.__table__.create(bind=db.bind, checkfirst=True)
    try:
        yield RouteBook, RouteGuide
    finally:
        RouteGuide.__table__.drop(bind=db.bind, checkfirst=True)
        if db.bind.dialect.name == "postgresql":
            RouteVersion.__table__.drop(bind=db.bind, checkfirst=True)
            RouteBook.__table__.drop(bind=db.bind, checkfirst=True)
        else:
            db.execute(text("DROP TABLE IF EXISTS route_versions"))
            db.execute(text("DROP TABLE IF EXISTS route_books"))


def _copy_fixture(tmp_path: Path, *route_names: str) -> Path:
    target = tmp_path / "routes"
    target.mkdir()
    for route_name in route_names:
        shutil.copytree(FIXTURE_ROUTES / route_name, target / route_name)
    return target


def test_imports_gpx_route_and_creates_official_route_book(db, route_guide_tables, tmp_path, monkeypatch):
    if db.bind.dialect.name != "postgresql":
        pytest.skip("requires PostGIS")
    from app.route_book.models import RouteVersion

    RouteBook, RouteGuide = route_guide_tables
    script = _load_script()
    content_dir = _copy_fixture(tmp_path, "test-gpx-route")
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--content-dir", str(content_dir)])

    guide = db.query(RouteGuide).filter_by(name="测试 GPX 路线").one()
    book = db.query(RouteBook).filter_by(id=guide.route_book_id).one()
    profile = json.loads(guide.elevation_profile)
    assert guide.city == "太原"
    assert guide.highlights == "[\"起点清晰\", \"终点清晰\"]"
    assert guide.cover_url == "https://example.com/test-gpx.jpg"
    assert book.is_official is True
    assert book.source == "file_upload"
    assert book.file_type == "gpx"
    assert book.file_id
    assert book.city == "taiyuan"
    assert book.visibility == "public"
    assert book.publish_status == "published"
    assert book.current_version_id is not None
    version = db.query(RouteVersion).filter_by(route_book_id=book.id).one()
    assert version.id == book.current_version_id
    assert version.version_no == 1
    assert version.status == "current"
    assert version.navigation_status == "ready"
    assert version.geometry_source == "file_upload"
    assert len(profile) <= 100
    assert profile[0][0] == 0
    assert profile[-1][0] > profile[0][0]
    assert all(curr[0] >= prev[0] for prev, curr in zip(profile, profile[1:]))


def _write_gpx(path: Path, elevations: list[float | None]) -> None:
    points = []
    for index, elevation in enumerate(elevations):
        ele_tag = "" if elevation is None else f"<ele>{elevation}</ele>"
        points.append(f'<trkpt lat="{37.0 + index * 0.001}" lon="112.0">{ele_tag}</trkpt>')
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest">
  <trk>
    <trkseg>
      {"".join(points)}
    </trkseg>
  </trk>
</gpx>
""",
        encoding="utf-8",
    )


def test_parse_track_uses_numeric_meta_distance_and_climb_overrides(tmp_path):
    script = _load_script()
    route_dir = tmp_path / "routes" / "with-meta"
    route_dir.mkdir(parents=True)
    (route_dir / "guide.md").write_text("# 有 meta 的路线\n", encoding="utf-8")
    (route_dir / "meta.json").write_text(
        json.dumps({"name": "有 meta 的路线", "distance_km": 12.3, "climb_m": 456}),
        encoding="utf-8",
    )
    track_path = route_dir / "track.gpx"
    _write_gpx(track_path, [10.0, 30.0, 20.0])

    route = script.load_routes(tmp_path / "routes")[0]
    parsed = script.parse_track(
        route.track_path,
        distance_override_m=route.distance_override_m,
        climb_override_m=route.climb_override_m,
    )

    assert parsed.distance == 12300.0
    assert parsed.climb == 456
    assert parsed.elevation_profile is not None


def test_parse_track_without_elevation_and_without_override_stores_nulls(tmp_path):
    script = _load_script()
    track_path = tmp_path / "track.gpx"
    _write_gpx(track_path, [None, None, None])

    parsed = script.parse_track(track_path)

    assert parsed.climb is None
    assert parsed.elevation_profile is None


def test_parse_track_without_elevation_uses_climb_override_but_keeps_profile_null(tmp_path):
    script = _load_script()
    track_path = tmp_path / "track.gpx"
    _write_gpx(track_path, [None, None, None])

    parsed = script.parse_track(track_path, climb_override_m=314)

    assert parsed.climb == 314
    assert parsed.elevation_profile is None


def test_imports_route_without_gpx_as_track_pending(db, route_guide_tables, tmp_path, monkeypatch):
    RouteBook, RouteGuide = route_guide_tables
    script = _load_script()
    content_dir = _copy_fixture(tmp_path, "test-no-track")
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--content-dir", str(content_dir)])

    guide = db.query(RouteGuide).filter_by(name="测试无轨迹路线").one()
    assert guide.city == "太原"
    assert guide.route_book_id is None
    assert guide.elevation_profile is None
    assert guide.gallery_urls is None  # meta 没有 gallery_urls 键 → 存 NULL（老路线无图不报错）
    assert db.query(RouteBook).count() == 0


def test_missing_guide_md_exits_before_writing(db, route_guide_tables, tmp_path, monkeypatch, capsys):
    _, RouteGuide = route_guide_tables
    script = _load_script()
    route_dir = tmp_path / "routes" / "broken"
    route_dir.mkdir(parents=True)
    (route_dir / "meta.json").write_text(
        json.dumps({"name": "缺 guide 路线", "highlights": "[\"缺文件\"]"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    with pytest.raises(SystemExit) as exc:
        script.main(["--content-dir", str(tmp_path / "routes")])

    assert exc.value.code == 1
    assert "guide.md" in capsys.readouterr().out
    assert db.query(RouteGuide).count() == 0


def test_bad_highlights_exits_before_writing(db, route_guide_tables, tmp_path, monkeypatch, capsys):
    _, RouteGuide = route_guide_tables
    script = _load_script()
    route_dir = tmp_path / "routes" / "bad-highlights"
    route_dir.mkdir(parents=True)
    (route_dir / "guide.md").write_text("# 坏 highlights\n", encoding="utf-8")
    (route_dir / "meta.json").write_text(
        json.dumps({"name": "坏 highlights 路线", "highlights": "\"不是数组\""}),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    with pytest.raises(SystemExit) as exc:
        script.main(["--content-dir", str(tmp_path / "routes")])

    assert exc.value.code == 1
    assert "highlights" in capsys.readouterr().out
    assert db.query(RouteGuide).count() == 0


def test_gallery_urls_list_is_stored_as_json_text(db, route_guide_tables, tmp_path, monkeypatch):
    # 实景图入库：meta.json 里发布脚本写的是真 JSON 数组，落库存 JSON 文本；
    # 缺省（老路线还没图）存 NULL，前端整块隐藏。
    _, RouteGuide = route_guide_tables
    script = _load_script()
    route_dir = tmp_path / "routes" / "with-gallery"
    route_dir.mkdir(parents=True)
    (route_dir / "guide.md").write_text("# 带实景图的路线\n", encoding="utf-8")
    (route_dir / "meta.json").write_text(
        json.dumps({
            "name": "带实景图的路线",
            "gallery_urls": ["/uploads/route_covers/with-gallery/g01.jpg", "/uploads/route_covers/with-gallery/g02.jpg"],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--content-dir", str(tmp_path / "routes")])

    guide = db.query(RouteGuide).filter_by(name="带实景图的路线").one()
    assert json.loads(guide.gallery_urls) == [
        "/uploads/route_covers/with-gallery/g01.jpg",
        "/uploads/route_covers/with-gallery/g02.jpg",
    ]


def test_gallery_urls_survive_idempotent_rerun(db, route_guide_tables, tmp_path, monkeypatch):
    # 重灌幂等：meta.json 没变时再跑一遍，gallery_urls 原样保留（不洗掉、不重复建 guide）
    _, RouteGuide = route_guide_tables
    script = _load_script()
    route_dir = tmp_path / "routes" / "rerun-gallery"
    route_dir.mkdir(parents=True)
    (route_dir / "guide.md").write_text("# 重灌路线\n", encoding="utf-8")
    (route_dir / "meta.json").write_text(
        json.dumps({"name": "重灌路线", "gallery_urls": ["/uploads/route_covers/rerun-gallery/g01_abcd1234.jpg"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--content-dir", str(tmp_path / "routes")])
    script.main(["--content-dir", str(tmp_path / "routes")])

    assert db.query(RouteGuide).count() == 1
    guide = db.query(RouteGuide).filter_by(name="重灌路线").one()
    assert json.loads(guide.gallery_urls) == ["/uploads/route_covers/rerun-gallery/g01_abcd1234.jpg"]


def test_bad_gallery_urls_exits_before_writing(db, route_guide_tables, tmp_path, monkeypatch, capsys):
    # gallery_urls 必须是字符串数组——混进非字符串元素要在打开数据库之前拦住（与 highlights 同纪律）。
    _, RouteGuide = route_guide_tables
    script = _load_script()
    route_dir = tmp_path / "routes" / "bad-gallery"
    route_dir.mkdir(parents=True)
    (route_dir / "guide.md").write_text("# 坏 gallery\n", encoding="utf-8")
    (route_dir / "meta.json").write_text(
        json.dumps({"name": "坏 gallery 路线", "gallery_urls": "不是数组"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    with pytest.raises(SystemExit) as exc:
        script.main(["--content-dir", str(tmp_path / "routes")])

    assert exc.value.code == 1
    assert "gallery_urls" in capsys.readouterr().out
    assert db.query(RouteGuide).count() == 0


def test_idempotent_rerun_updates_existing_guide_and_book(db, route_guide_tables, tmp_path, monkeypatch):
    if db.bind.dialect.name != "postgresql":
        pytest.skip("requires PostGIS")
    RouteBook, RouteGuide = route_guide_tables
    script = _load_script()
    content_dir = _copy_fixture(tmp_path, "test-gpx-route")
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--content-dir", str(content_dir)])
    first_guide = db.query(RouteGuide).filter_by(name="测试 GPX 路线").one()
    first_book_id = first_guide.route_book_id
    (content_dir / "test-gpx-route" / "guide.md").write_text("# 测试 GPX 路线\n\n第二版介绍。\n", encoding="utf-8")
    script.main(["--content-dir", str(content_dir)])

    guide = db.query(RouteGuide).filter_by(name="测试 GPX 路线").one()
    assert db.query(RouteGuide).count() == 1
    assert db.query(RouteBook).count() == 1
    assert guide.route_book_id == first_book_id
    assert guide.content_md.endswith("第二版介绍。\n")


def test_missing_highlights_is_optional_and_stored_as_null(db, route_guide_tables, tmp_path, monkeypatch):
    """highlights 是可选字段（spec §3.6 必填只有 name）——缺省存 NULL 不报错。

    锁死高危双审 C1 的修正：之前脚本把 highlights 写成必填，任何一条没亮点的路线会卡死整次灌库。
    """
    _, RouteGuide = route_guide_tables
    script = _load_script()
    route_dir = tmp_path / "routes" / "no-highlights"
    route_dir.mkdir(parents=True)
    (route_dir / "guide.md").write_text("# 无亮点路线\n\n一条朴素的路。\n", encoding="utf-8")
    (route_dir / "meta.json").write_text(json.dumps({"name": "无亮点路线"}), encoding="utf-8")
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--content-dir", str(tmp_path / "routes")])

    guide = db.query(RouteGuide).filter_by(name="无亮点路线").one()
    assert guide.highlights is None
    assert guide.route_book_id is None


def test_track_pending_guide_upgrades_to_route_book_on_rerun(db, route_guide_tables, tmp_path, monkeypatch):
    """track_pending 升级路径（卡 §6 #2）：先无 GPX 灌 → 补 GPX 重跑 → 同一 guide 挂上 book，不新建 guide。

    这是汾河等"先有介绍后补轨迹"路线的真实生命周期，幂等键 = name。
    """
    if db.bind.dialect.name != "postgresql":
        pytest.skip("requires PostGIS")
    RouteBook, RouteGuide = route_guide_tables
    script = _load_script()
    content_dir = _copy_fixture(tmp_path, "test-no-track")
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--content-dir", str(content_dir)])
    pending = db.query(RouteGuide).filter_by(name="测试无轨迹路线").one()
    assert pending.route_book_id is None
    pending_id = pending.id

    # 补 GPX（借 gpx fixture 的轨迹文件）后重跑——升级不重建
    shutil.copy(FIXTURE_ROUTES / "test-gpx-route" / "track.gpx", content_dir / "test-no-track" / "track.gpx")
    script.main(["--content-dir", str(content_dir)])

    upgraded = db.query(RouteGuide).filter_by(name="测试无轨迹路线").one()
    assert upgraded.id == pending_id
    assert upgraded.route_book_id is not None
    assert upgraded.elevation_profile is not None
    assert db.query(RouteGuide).count() == 1
    assert db.query(RouteBook).count() == 1


def test_dry_run_prints_plan_and_makes_no_db_writes(db, route_guide_tables, monkeypatch, capsys):
    RouteBook, RouteGuide = route_guide_tables
    script = _load_script()

    def fail_session():
        raise AssertionError("dry-run must not open a DB session")

    monkeypatch.setattr(script, "SessionLocal", fail_session)

    script.main(["--dry-run", "--content-dir", str(FIXTURE_ROUTES)])

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "测试 GPX 路线" in out
    assert "测试无轨迹路线" in out
    assert "would create/update route_book" in out
    assert "status=track_pending" in out
    assert db.query(RouteGuide).count() == 0
    assert db.query(RouteBook).count() == 0
