"""路线百科 API 测试——验证官方路线手册列表和详情能稳定喂给小程序。"""

from datetime import datetime, timezone

from sqlalchemy import text

from app.route_book.models import RouteBook, RouteGuide, RouteVersion


def _create_route_guides_table(db):
    db.execute(text("CREATE TABLE IF NOT EXISTS judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    RouteGuide.__table__.create(bind=db.bind, checkfirst=True)


def _drop_route_guides_table(db):
    RouteGuide.__table__.drop(bind=db.bind, checkfirst=True)
    db.execute(text("DROP TABLE IF EXISTS judgment_runs"))


def _route_book(db, name="天龙山路书"):
    route = RouteBook(
        name=name,
        distance=12340.0,
        climb=456.0,
        reference_line="SRID=4326;LINESTRING(112.50 37.80, 112.60 37.90)",
        source="file_upload",
        file_id="routes/tianlongshan.gpx",
        file_type="gpx",
        city="taiyuan",
        is_official=True,
        visibility="public",
        publish_status="published",
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    route._preview_points_override = [[112.5, 37.8], [112.6, 37.9]]
    return route


def _attach_current_version(db, route, **overrides):
    data = {
        "route_book_id": route.id,
        "version_no": 1,
        "status": "current",
        "created_by": route.creator_id,
        "geometry_source": route.source,
        "navigation_status": "ready",
        "reference_line_snapshot": "SRID=4326;LINESTRING(112.50 37.80, 112.60 37.90)",
        "line_hash": "hash-" + str(route.id),
        "distance": route.distance,
        "climb": route.climb,
        "elevation_points_snapshot": "[[112.5,37.8,701.2],[112.6,37.9,735.8]]",
        "navigation_metadata_json": (
            "{\"elevation\":{\"method\":\"glo30_meaningful_ascent_v1\","
            "\"source_name\":\"Copernicus DEM GLO-30 Public\","
            "\"license_id\":\"Copernicus DEM Licence\","
            "\"accuracy_m\":4.0,"
            "\"horizontal_resolution_m\":30.0,"
            "\"processing_grid_m\":20.0,"
            "\"median_filter_points\":3,"
            "\"smoothing_sigma_m\":100.0,"
            "\"ascent_prominence_m\":3.0,"
            "\"ascent_minimum_span_m\":100.0,"
            "\"maximum_processing_distance_m\":1000000.0,"
            "\"dataset_id\":\"COP-DEM_GLO-30-DGED\","
            "\"vertical_datum\":\"EGM2008 (EPSG:3855)\","
            "\"grid_registration\":\"RasterPixelIsPoint\","
            "\"point_count\":2}}"
        ),
        "point_count": 2,
    }
    data.update(overrides)
    version = RouteVersion(
        **data,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    route.current_version_id = version.id
    db.add(route)
    db.commit()
    db.refresh(route)
    return version


def _guide(db, **overrides):
    data = {
        "name": "天龙山西线",
        "city": "太原",
        "route_book_id": None,
        "content_md": "# 天龙山西线\n\n一条适合周末爬坡的路线。",
        "cover_url": None,
        "highlights": "[\"坡长稳定\", \"补给清楚\"]",
        "elevation_profile": None,
    }
    data.update(overrides)
    guide = RouteGuide(**data)
    db.add(guide)
    db.commit()
    db.refresh(guide)
    return guide


def test_list_includes_track_pending_with_null_metrics(client, db):
    _create_route_guides_table(db)
    try:
        _guide(db, name="汾河二库", highlights=None)

        res = client.get("/api/route-guides")

        assert res.status_code == 200
        body = res.json()
        assert body == {
            "items": [
                {
                    "id": body["items"][0]["id"],
                    "name": "汾河二库",
                    "city": "太原",
                    "ready": False,
                    "cover_url": None,
                    "highlights": None,
                    "distance": None,
                    "climb": None,
                }
            ]
        }
        assert "preview_points" not in body["items"][0]
    finally:
        _drop_route_guides_table(db)


def test_detail_ready_true_returns_profile_preview_and_km_distance(client, db):
    _create_route_guides_table(db)
    try:
        route = _route_book(db)
        guide = _guide(
            db,
            route_book_id=route.id,
            elevation_profile="[[0, 780], [3.5, 920], [12.34, 1100]]",
        )

        res = client.get(f"/api/route-guides/{guide.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["ready"] is True
        assert body["route_book_id"] == route.id
        assert body["distance"] == 12.34
        assert body["climb"] == 456.0
        assert body["elevation_profile"] == [[0, 780], [3.5, 920], [12.34, 1100]]
        assert body["preview_points"] == [[112.5, 37.8], [112.6, 37.9]]
        assert body["export_ready"] is False
        assert body["export_formats"] == []
        assert body["export_block_reason"] == "no_current_version"
    finally:
        _drop_route_guides_table(db)


def test_detail_export_ready_only_for_public_published_current_version(client, db):
    _create_route_guides_table(db)
    try:
        route = _route_book(db)
        version = _attach_current_version(db, route)
        guide = _guide(db, route_book_id=route.id, source_route_version_id=version.id)

        res = client.get(f"/api/route-guides/{guide.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["ready"] is True
        assert body["export_ready"] is True
        assert body["export_formats"] == ["gpx", "tcx"]
        assert body["export_block_reason"] is None
    finally:
        _drop_route_guides_table(db)


def test_detail_export_not_ready_when_current_version_is_not_navigation_ready(client, db):
    _create_route_guides_table(db)
    try:
        route = _route_book(db)
        version = _attach_current_version(db, route, navigation_status="pending")
        guide = _guide(db, route_book_id=route.id, source_route_version_id=version.id)

        res = client.get(f"/api/route-guides/{guide.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["ready"] is True
        assert body["export_ready"] is False
        assert body["export_formats"] == []
        assert body["export_block_reason"] == "no_current_version"
    finally:
        _drop_route_guides_table(db)


def test_detail_export_not_ready_when_route_lacks_complete_elevation(client, db):
    _create_route_guides_table(db)
    try:
        route = _route_book(db)
        version = _attach_current_version(db, route, elevation_points_snapshot=None)
        guide = _guide(db, route_book_id=route.id, source_route_version_id=version.id)

        res = client.get(f"/api/route-guides/{guide.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["ready"] is True
        assert body["export_ready"] is False
        assert body["export_formats"] == []
        assert body["export_block_reason"] == "no_elevation"
    finally:
        _drop_route_guides_table(db)


def test_detail_export_block_reason_distinguishes_no_route_and_private_route(client, db):
    _create_route_guides_table(db)
    try:
        no_route = _guide(db, name="只有文字的路线", route_book_id=None)
        private_route = _route_book(db, name="未公开路线")
        private_route.visibility = "private"
        private_route.publish_status = "published"
        _attach_current_version(db, private_route)
        private_guide = _guide(db, name="挂着私密路书的路线", route_book_id=private_route.id)

        no_route_body = client.get(f"/api/route-guides/{no_route.id}").json()
        private_body = client.get(f"/api/route-guides/{private_guide.id}").json()

        assert no_route_body["ready"] is False
        assert no_route_body["export_ready"] is False
        assert no_route_body["export_formats"] == []
        assert no_route_body["export_block_reason"] == "no_route_book"
        assert private_body["ready"] is True
        assert private_body["export_ready"] is False
        assert private_body["export_formats"] == []
        assert private_body["export_block_reason"] == "not_public"
    finally:
        _drop_route_guides_table(db)


def test_detail_ready_false_keeps_content_but_hides_track_fields(client, db):
    _create_route_guides_table(db)
    try:
        guide = _guide(db, name="清徐夜骑", route_book_id=None, elevation_profile=None)

        res = client.get(f"/api/route-guides/{guide.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "清徐夜骑"
        assert body["content_md"].startswith("# 天龙山西线")
        assert body["ready"] is False
        assert body["route_book_id"] is None
        assert body["distance"] is None
        assert body["climb"] is None
        assert body["elevation_profile"] is None
        assert body["preview_points"] is None
        assert body["export_ready"] is False
        assert body["export_formats"] == []
        assert body["export_block_reason"] == "no_route_book"
    finally:
        _drop_route_guides_table(db)


def test_detail_does_not_expose_internal_provenance(client, db):
    _create_route_guides_table(db)
    try:
        guide = _guide(
            db,
            source_ref="route-workspace/tianlongshan/route.json @ 2026-06-18",
            content_hash="f" * 64,
            imported_at=datetime.now(timezone.utc),
            content_origin="content_routes_import",
            source_route_version_id=None,
        )

        detail = client.get(f"/api/route-guides/{guide.id}").json()
        listing = client.get("/api/route-guides").json()["items"][0]

        for payload in (detail, listing):
            assert "source_ref" not in payload
            assert "content_hash" not in payload
            assert "imported_at" not in payload
            assert "content_origin" not in payload
            assert "source_route_version_id" not in payload
    finally:
        _drop_route_guides_table(db)


def test_detail_gallery_urls_json_text_is_loaded_as_list(client, db):
    # 实景图链路：DB 里存 JSON 文本，详情接口要还原成数组；没图的路线返回 None
    # （前端按 no-dash 判例整块隐藏长廊）。列表接口不带 gallery_urls——书架页用不上，省流量。
    _create_route_guides_table(db)
    try:
        with_photos = _guide(
            db,
            name="崛围山",
            gallery_urls="[\"/uploads/route_covers/jueweishan/g01.jpg\", \"/uploads/route_covers/jueweishan/g02.jpg\"]",
        )
        without_photos = _guide(db, name="清徐夜骑", gallery_urls=None)

        res_with = client.get(f"/api/route-guides/{with_photos.id}")
        res_without = client.get(f"/api/route-guides/{without_photos.id}")
        res_list = client.get("/api/route-guides")

        assert res_with.status_code == 200
        assert res_with.json()["gallery_urls"] == [
            "/uploads/route_covers/jueweishan/g01.jpg",
            "/uploads/route_covers/jueweishan/g02.jpg",
        ]
        assert res_without.json()["gallery_urls"] is None
        assert all("gallery_urls" not in item for item in res_list.json()["items"])
    finally:
        _drop_route_guides_table(db)


def test_detail_gallery_urls_bad_data_degrades_not_500(client, db):
    # DB 里混进坏数据（空串/坏 JSON）时，详情页应该"少一块内容"而不是整页 500；
    # 合法空数组 [] 原样返回（前端按 length 隐藏长廊）
    _create_route_guides_table(db)
    try:
        empty_str = _guide(db, name="空串路线", gallery_urls="")
        bad_json = _guide(db, name="坏JSON路线", gallery_urls="{not json")
        empty_list = _guide(db, name="空数组路线", gallery_urls="[]")

        assert client.get(f"/api/route-guides/{empty_str.id}").json()["gallery_urls"] is None
        assert client.get(f"/api/route-guides/{bad_json.id}").json()["gallery_urls"] is None
        assert client.get(f"/api/route-guides/{empty_list.id}").json()["gallery_urls"] == []
    finally:
        _drop_route_guides_table(db)


def test_highlights_json_text_is_loaded_as_list(client, db):
    _create_route_guides_table(db)
    try:
        guide = _guide(db, highlights="[\"本地骑友常走\", \"下坡注意控速\"]")

        res = client.get(f"/api/route-guides/{guide.id}")

        assert res.status_code == 200
        assert res.json()["highlights"] == ["本地骑友常走", "下坡注意控速"]
    finally:
        _drop_route_guides_table(db)


def test_route_guide_not_found_returns_404(client, db):
    _create_route_guides_table(db)
    try:
        res = client.get("/api/route-guides/999999")

        assert res.status_code == 404
    finally:
        _drop_route_guides_table(db)


def test_route_books_and_route_guides_prefixes_do_not_conflict(client, db):
    _create_route_guides_table(db)
    try:
        route = _route_book(db, name="旧路书入口")
        guide = _guide(db, name="官方手册入口")

        route_book_res = client.get(f"/api/route-books/{route.id}")
        route_guide_res = client.get(f"/api/route-guides/{guide.id}")

        assert route_book_res.status_code == 200
        assert route_book_res.json()["name"] == "旧路书入口"
        assert route_guide_res.status_code == 200
        assert route_guide_res.json()["name"] == "官方手册入口"
    finally:
        _drop_route_guides_table(db)
