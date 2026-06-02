"""约骑模块 Task 2：路书 API 测试。"""

from datetime import datetime, timezone
from typing import get_args

from app.activity.models import Activity, Trackpoint
from app.main import app
from app.route_book.router import router as route_book_router
from app.route_book import schemas


# task2 阶段 route_book router 还没挂进 app.main（task4 才统一挂载所有 router）。
# 这里在测试 app 上临时挂一次，让 TestClient 能请求 /api/route-books。
# 幂等判断：多个测试文件可能都想挂，避免重复 include 同一 router。
if not any(getattr(route, "path", "") == "/api/route-books" for route in app.router.routes):
    app.include_router(route_book_router)


def test_generic_create_source_excludes_tencent_direction():
    assert get_args(schemas.RouteBookCreateSource) == ("file_upload", "activity_derived")
    assert "tencent_direction" in get_args(schemas.RouteBookSource)


def _activity(db, user_id: int, **overrides):
    data = {
        "user_id": user_id,
        "title": "周末路线",
        "status": "completed",
        "activity_type": "cycling",
        "file_url": "202605/ride.gpx",
        "distance": 42000.0,
        "elevation_gain": 580.0,
        "started_at": datetime(2026, 5, 20, 1, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    activity = Activity(**data)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    db.add_all([
        Trackpoint(activity_id=activity.id, seq=0, latitude=37.8, longitude=112.5, distance=0.0),
        Trackpoint(activity_id=activity.id, seq=1, latitude=37.9, longitude=112.6, distance=42000.0),
    ])
    db.commit()
    return activity


def test_activity_derived_requires_source_activity_id(client, auth_header):
    res = client.post(
        "/api/route-books",
        data={"name": "无来源", "source": "activity_derived"},
        headers=auth_header,
    )
    assert res.status_code == 422
    assert "source_activity_id" in res.text


def test_activity_derived_rejects_other_user_activity(client, db, auth_header, admin_user):
    other_activity = _activity(db, admin_user.id)

    res = client.post(
        "/api/route-books",
        data={"name": "别人的路线", "source": "activity_derived", "source_activity_id": str(other_activity.id)},
        headers=auth_header,
    )

    assert res.status_code == 403


def test_activity_derived_creates_route_book(client, db, auth_header, test_user):
    activity = _activity(db, test_user.id, city="taiyuan")

    res = client.post(
        "/api/route-books",
        data={"name": "汾河训练线", "source": "activity_derived", "source_activity_id": str(activity.id)},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "汾河训练线"
    assert body["source"] == "activity_derived"
    assert body["source_activity_id"] == activity.id
    assert body["file_id"] is None
    assert body["file_type"] is None
    assert body["city"] == "taiyuan"


def test_file_upload_supports_gpx_and_preserves_file_id(client, auth_header, monkeypatch):
    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "route.gpx"
            return "202605/route.gpx"

    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 1234.0,
        "climb": 50.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
    })

    res = client.post(
        "/api/route-books",
        data={"name": "上传路线", "source": "file_upload"},
        files={"file": ("route.gpx", b"<?xml version='1.0'?><gpx></gpx>", "application/gpx+xml")},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "202605/route.gpx"
    assert body["file_type"] == "gpx"


def test_file_upload_supports_fit_and_preserves_file_id(client, auth_header, monkeypatch):
    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "route.fit"
            return "202605/route.fit"

    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 2345.0,
        "climb": 80.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
    })

    res = client.post(
        "/api/route-books",
        data={"name": "FIT 路线", "source": "file_upload"},
        files={"file": ("route.fit", b"fit-bytes", "application/octet-stream")},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "202605/route.fit"
    assert body["file_type"] == "fit"


def test_tencent_direction_requires_server_key(client, auth_header, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "")

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "腾讯规划路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 503
    assert "TENCENT_MAP_KEY" in res.text


def test_tencent_direction_creates_route_book(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    def fake_plan(start, end):
        assert start == (37.8001, 112.5001)
        assert end == (37.8601, 112.5601)
        return {
            "distance": 6800.0,
            "duration": 28,
            "points": [
                {"lat": 37.8001, "lon": 112.5001},
                {"lat": 37.8301, "lon": 112.5301},
                {"lat": 37.8601, "lon": 112.5601},
            ],
        }

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", fake_plan)

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "腾讯规划路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "腾讯规划路线"
    assert body["source"] == "tencent_direction"
    assert body["file_id"] is None
    assert body["file_type"] is None
    assert body["source_activity_id"] is None
    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).first()
    assert route is not None
    assert route.distance == 6800.0
    assert route.source == "tencent_direction"


def test_tencent_direction_applies_user_rate_limit(client, auth_header, test_user, monkeypatch):
    calls = []

    def fake_rate_limit(user_id, key_prefix, limit, window_sec):
        calls.append((user_id, key_prefix, limit, window_sec))

    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_user", fake_rate_limit)
    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", lambda start, end: {
        "distance": 6800.0,
        "duration": 28,
        "points": [
            {"lat": 37.8001, "lon": 112.5001},
            {"lat": 37.8601, "lon": 112.5601},
        ],
    })

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "限流路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 200
    assert calls == [(test_user.id, "route-book-tencent-direction", 10, 300)]


def test_tencent_direction_rejects_same_point_before_calling_tencent(client, auth_header, monkeypatch):
    called = False

    def fake_plan(start, end):
        nonlocal called
        called = True
        return {"distance": 1.0, "duration": 1, "points": []}

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", fake_plan)

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "原地路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8001,
            "to_lon": 112.5001,
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert called is False


def test_tencent_direction_rejects_too_short_route(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", lambda start, end: {
        "distance": 20.0,
        "duration": 1,
        "points": [
            {"lat": 37.8001, "lon": 112.5001},
            {"lat": 37.8002, "lon": 112.5002},
        ],
    })

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "太短路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8002,
            "to_lon": 112.5002,
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert db.query(RouteBook).filter(RouteBook.name == "太短路线").first() is None


def test_tencent_direction_rejects_empty_polyline(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", lambda start, end: {
        "distance": 0.0,
        "duration": 0,
        "points": [],
    })

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "空路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert db.query(RouteBook).filter(RouteBook.name == "空路线").first() is None


def test_list_supports_public_mine_and_city_filters(client, db, auth_header, admin_header, test_user, admin_user):
    from app.route_book.models import RouteBook

    mine = RouteBook(
        creator_id=test_user.id,
        name="我的训练路线",
        distance=1800.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    other = RouteBook(
        creator_id=admin_user.id,
        name="别人的路线",
        distance=2200.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add_all([mine, other])
    db.commit()
    db.refresh(mine)
    db.refresh(other)

    list_res = client.get("/api/route-books?city=taiyuan", headers=auth_header)
    assert list_res.status_code == 200
    names = [item["name"] for item in list_res.json()["items"]]
    assert "我的训练路线" in names
    assert "别人的路线" in names

    public_res = client.get("/api/route-books?city=taiyuan")
    assert public_res.status_code == 200
    assert len(public_res.json()["items"]) == 2

    mine_res = client.get("/api/route-books?mine=1", headers=auth_header)
    assert mine_res.status_code == 200
    mine_names = [item["name"] for item in mine_res.json()["items"]]
    assert "我的训练路线" in mine_names
    assert "别人的路线" not in mine_names

    unauth_mine = client.get("/api/route-books?mine=1")
    assert unauth_mine.status_code == 401

    detail_res = client.get(f"/api/route-books/{other.id}", headers=auth_header)
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == other.id


def test_delete_route_book_is_owner_only(client, db, auth_header, admin_header, test_user):
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=test_user.id,
        name="可删路线",
        distance=1000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    forbidden = client.delete(f"/api/route-books/{route.id}", headers=admin_header)
    assert forbidden.status_code == 403

    ok = client.delete(f"/api/route-books/{route.id}", headers=auth_header)
    assert ok.status_code == 204


def test_activity_candidates_only_returns_current_user_completed_cycling(client, db, auth_header, test_user, admin_user):
    own = _activity(db, test_user.id, title="自己的骑行", city="taiyuan")
    _activity(db, test_user.id, title="跑步", activity_type="running")
    _activity(db, test_user.id, title="失败上传", status="failed")
    _activity(db, admin_user.id, title="别人骑行")

    res = client.get("/api/route-books/activity-candidates", headers=auth_header)

    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["id"] for item in items] == [own.id]


def test_activity_derived_rejects_non_completed_or_non_cycling(client, db, auth_header, test_user):
    # 还在处理中的活动不能衍生路书（轨迹尚未落库）
    processing = _activity(db, test_user.id, status="processing")
    res = client.post(
        "/api/route-books",
        data={"name": "未完成", "source": "activity_derived", "source_activity_id": str(processing.id)},
        headers=auth_header,
    )
    assert res.status_code == 422

    # 跑步类活动不能衍生骑行路书
    running = _activity(db, test_user.id, activity_type="running")
    res2 = client.post(
        "/api/route-books",
        data={"name": "跑步", "source": "activity_derived", "source_activity_id": str(running.id)},
        headers=auth_header,
    )
    assert res2.status_code == 422


def test_activity_derived_missing_activity_returns_404(client, auth_header):
    res = client.post(
        "/api/route-books",
        data={"name": "不存在的活动", "source": "activity_derived", "source_activity_id": "999999"},
        headers=auth_header,
    )
    assert res.status_code == 404


def test_file_upload_without_file_returns_422(client, auth_header):
    res = client.post(
        "/api/route-books",
        data={"name": "没传文件", "source": "file_upload"},
        headers=auth_header,
    )
    assert res.status_code == 422


def test_delete_tolerates_storage_failure(client, db, auth_header, test_user, monkeypatch):
    # storage 删文件失败（磁盘权限/IO）不该阻塞用户：DB 是 source of truth，记录已删即算成功。
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=test_user.id,
        name="带文件的路线",
        distance=1000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="file_upload",
        file_id="202605/orphan.gpx",
        file_type="gpx",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    def boom(file_id):
        raise OSError("disk gone")

    monkeypatch.setattr("app.route_book.service._storage.delete", boom)

    res = client.delete(f"/api/route-books/{route.id}", headers=auth_header)
    assert res.status_code == 204


def test_file_upload_unparseable_returns_422_not_500(client, auth_header, monkeypatch):
    # 真实 GPX/FIT 解析器对损坏文件抛 GPXParseError(Exception)——它不继承 ValueError，
    # 若不在 service 层转译，会穿透 router 成 500。用户上传坏文件应得 422 而不是 500。
    from app.parsing.gpx_parser import GPXParseError

    monkeypatch.setattr("app.route_book.service.validate_ride_file", lambda f, b: None)

    def boom(self, content, **kw):
        raise GPXParseError("文件损坏无法解析")

    monkeypatch.setattr("app.parsing.gpx_parser.GPXParser.parse", boom)

    res = client.post(
        "/api/route-books",
        data={"name": "坏GPX", "source": "file_upload"},
        files={"file": ("x.gpx", b"whatever", "application/gpx+xml")},
        headers=auth_header,
    )
    assert res.status_code == 422


def test_create_rejects_overlong_name(client, db, auth_header, test_user):
    # name DB 列是 VARCHAR(128)；超长 name 不该走到 commit 才 DataError 500，
    # 应在请求层（Form max_length）拦成 422。
    activity = _activity(db, test_user.id)
    res = client.post(
        "/api/route-books",
        data={"name": "x" * 200, "source": "activity_derived", "source_activity_id": str(activity.id)},
        headers=auth_header,
    )
    assert res.status_code == 422
