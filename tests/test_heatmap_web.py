from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from app.config import settings
from app.heatmap_web import service as heatmap_web


ROOT = Path(__file__).resolve().parents[1]


class TicketRedis:
    def __init__(self):
        self.values = {}
        self.lock_calls = []

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def getdel(self, key):
        return self.values.pop(key, None)

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def lock(self, key, timeout=None, blocking_timeout=None):
        self.lock_calls.append((key, timeout, blocking_timeout))
        return FakeLock()


class FakeLock:
    def acquire(self):
        return True

    def release(self):
        return None


class QueueRecorder:
    def __init__(self):
        self.calls = []

    def fetch_job(self, _job_id):
        return None

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_web_ticket_is_opaque_and_single_use():
    redis = TicketRedis()
    with patch("app.heatmap_web.service._redis_client", return_value=redis):
        ticket = heatmap_web.create_web_ticket(7, 9)
        assert len(ticket) >= 40
        stored_key = next(iter(redis.values))
        assert ticket not in stored_key
        assert stored_key.startswith("heatmap:web-ticket:v1:")
        assert heatmap_web.consume_web_ticket(ticket) == {
            "viewer_user_id": 7,
            "target_user_id": 9,
        }
        try:
            heatmap_web.consume_web_ticket(ticket)
        except heatmap_web.HeatmapWebSessionError as exc:
            assert "已过期或已使用" in str(exc)
        else:
            raise AssertionError("一次性热图票据被重复消费")


def test_heatmap_session_is_audience_scoped_and_version_bound():
    redis = TicketRedis()
    token = heatmap_web.create_session_token(7, 9)
    identity = heatmap_web.decode_session_token(token)
    assert identity["viewer_user_id"] == 7
    assert identity["target_user_id"] == 9
    assert len(str(identity["session_id"])) == 32

    with patch("app.heatmap_web.service._redis_client", return_value=redis):
        heatmap_web.remember_session_version(str(identity["session_id"]), None, "g2-deadbeef")
        heatmap_web.validate_session_version(str(identity["session_id"]), None, "g2-deadbeef")
        try:
            heatmap_web.validate_session_version(str(identity["session_id"]), None, "g1-old")
        except heatmap_web.HeatmapWebSessionError as exc:
            assert "版本已更新" in str(exc)
        else:
            raise AssertionError("会话接受了未授权的热图版本")


def test_old_artifact_generation_is_revoked_immediately():
    redis = TicketRedis()
    redis.values["heatmap:generation:user_9"] = b"8"
    with patch("app.heatmap_web.service._redis_client", return_value=redis):
        heatmap_web.validate_current_generation(9, "g8-current")
        try:
            heatmap_web.validate_current_generation(9, "g7-stale")
        except heatmap_web.HeatmapWebSessionError as exc:
            assert "版本已更新" in str(exc)
        else:
            raise AssertionError("旧热图会话在 generation 推进后仍能读取私有 PNG")


def test_session_coverage_rejects_tiles_outside_signed_manifest():
    redis = TicketRedis()
    session_id = "a" * 32
    with patch("app.heatmap_web.service._redis_client", return_value=redis):
        heatmap_web.remember_session_coverage(
            session_id,
            None,
            "g8-current",
            {"15": [[100, 200]]},
        )
        heatmap_web.validate_session_tile(
            session_id, None, "g8-current", 15, 100, 200
        )
        try:
            heatmap_web.validate_session_tile(
                session_id, None, "g8-current", 15, 101, 200
            )
        except heatmap_web.HeatmapTileNotCovered:
            pass
        else:
            raise AssertionError("清单外瓦片坐标触发了正式渲染路径")


def test_session_coverage_cannot_be_reused_by_a_new_artifact_version():
    redis = TicketRedis()
    session_id = "b" * 32
    with heatmap_web._SESSION_COVERAGE_CACHE_LOCK:
        heatmap_web._SESSION_COVERAGE_CACHE.clear()
    with patch("app.heatmap_web.service._redis_client", return_value=redis):
        heatmap_web.remember_session_coverage(
            session_id,
            None,
            "g8-old",
            {"15": [[100, 200]]},
        )
        with heatmap_web._SESSION_COVERAGE_CACHE_LOCK:
            heatmap_web._SESSION_COVERAGE_CACHE.clear()
        try:
            heatmap_web.validate_session_tile(
                session_id, None, "g8-new", 15, 100, 200
            )
        except heatmap_web.HeatmapWebSessionError as exc:
            assert "会话已过期" in str(exc)
        else:
            raise AssertionError("新版本复用了旧版本签发的瓦片清单")


def test_versioned_tile_artifact_path_is_user_audience_and_year_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "HEATMAP_TILE_DIR", str(tmp_path))
    path = heatmap_web.tile_artifact_path(
        7, "owner", "g2-deadbeef", 2026, 15, 100, 200
    )
    assert path == (
        tmp_path
        / "user_7"
        / "owner"
        / "year_2026"
        / "g2-deadbeef"
        / "live"
        / "15"
        / "100"
        / "200.png"
    )


def test_prune_keeps_current_version_and_delete_user_purges_all(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "HEATMAP_TILE_DIR", str(tmp_path))
    current = heatmap_web.tile_artifact_path(7, "owner", "g8-current", None, 15, 1, 1)
    stale = heatmap_web.tile_artifact_path(7, "owner", "g7-stale", 2025, 15, 1, 1)
    public = heatmap_web.tile_artifact_path(7, "public", "g8-public", None, 15, 1, 1)
    for path in (current, stale, public):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")

    redis = TicketRedis()
    redis.values["heatmap:generation:user_7"] = b"8"
    with patch("app.heatmap_web.service._redis_client", return_value=redis):
        result = heatmap_web.prune_stale_tile_artifacts_task(7, "owner", "g8-current")
        assert result == {"status": "pruned", "deleted": 1}
        assert current.exists()
        assert not stale.exists()
        assert public.exists()
        assert heatmap_web.purge_user_tile_artifacts(7) == 1
    assert not (tmp_path / "user_7").exists()


def test_purge_locks_even_when_user_artifact_directory_does_not_exist(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "HEATMAP_TILE_DIR", str(tmp_path))
    redis = TicketRedis()
    with patch("app.heatmap_web.service._redis_client", return_value=redis):
        assert heatmap_web.purge_user_tile_artifacts(7) == 0

    assert redis.lock_calls == [
        ("heatmap:artifact-mutation:v1:user_7", 60, 10)
    ]


def test_orphan_sweep_keeps_existing_user_and_removes_deleted_user_without_redis(
    db,
    test_user,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "HEATMAP_TILE_DIR", str(tmp_path))
    existing = tmp_path / f"user_{test_user.id}"
    orphan = tmp_path / "user_999999"
    interrupted = tmp_path / (".orphan-user_888888-" + "a" * 32 + ".deleting")
    for path in (existing, orphan, interrupted):
        path.mkdir(parents=True)
        (path / "tile.png").write_bytes(b"png")

    assert heatmap_web.sweep_orphan_user_artifacts(db) == 2
    assert existing.exists()
    assert not orphan.exists()
    assert not interrupted.exists()


def test_stale_artifact_prune_uses_low_priority_heatmap_queue():
    queue = QueueRecorder()
    with patch("app.queue.heatmap_tiles_queue", queue):
        queued = heatmap_web.enqueue_stale_artifact_prune(7, "owner", "g8-current")

    assert queued is True
    assert len(queue.calls) == 1
    args, kwargs = queue.calls[0]
    assert args[:4] == (
        "app.heatmap_web.service.prune_stale_tile_artifacts_task",
        7,
        "owner",
        "g8-current",
    )
    assert kwargs["job_id"].startswith("heatmap-prune-v1-user-7-")


def test_parent_fallback_keeps_overzoomed_line_thin():
    image = Image.new("RGBA", (512, 512), (255, 0, 0, 0))
    ImageDraw.Draw(image).line((100, 0, 100, 511), fill=(255, 49, 95, 255), width=3)
    source = BytesIO()
    image.save(source, format="PNG")

    payload = heatmap_web._crop_parent_tile(source.getvalue(), 3, 1, 0)

    with Image.open(BytesIO(payload)) as child:
        alpha_bounds = child.getchannel("A").getbbox()
        assert alpha_bounds is not None
        assert alpha_bounds[2] - alpha_bounds[0] <= 6


def test_blank_tile_is_a_valid_transparent_png(client):
    response = client.get("/heatmap/blank.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"

    with Image.open(BytesIO(response.content)) as image:
        image.verify()
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (1, 1)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0


def test_webgl_client_keeps_previous_layers_during_version_switch():
    source = (ROOT / "app" / "heatmap_web" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "new TMap.ImageTileLayer" in source
    assert "new URL(path, window.location.href).href" in source
    assert "sourceManifest.coverage_mode !== 'parent'" in source
    assert "Math.floor(x / scale)" in source
    assert "map.fitBounds(bounds, { padding: 72, duration: 0 })" in source
    assert "const previousLayers = [fallbackLayer, detailLayer]" in source
    assert "sourceManifest, sourceYear, coverage" in source
    assert "await preloadVisibleFallback" in source
    assert "results.every(Boolean)" in source
    assert "loadManifest(option.value).catch(showLoadError)" in source


def test_web_session_endpoint_requires_auth_and_returns_only_one_time_url(client, auth_header):
    assert client.post("/api/user/me/heatmap/web-session", json={}).status_code == 401
    with (
        patch("app.heatmap_web.router.user_service.get_user_by_id"),
        patch("app.heatmap_web.router.heatmap_web.create_web_ticket", return_value="opaque-ticket"),
    ):
        response = client.post(
            "/api/user/me/heatmap/web-session",
            json={},
            headers=auth_header,
        )
    assert response.status_code == 200
    assert response.json() == {"url": "/heatmap/session?ticket=opaque-ticket"}
    assert "Bearer" not in response.text


def test_ticket_landing_redirects_to_clean_url_and_sets_http_only_cookie(client):
    with patch(
        "app.heatmap_web.router.heatmap_web.consume_web_ticket",
        return_value={"viewer_user_id": 1, "target_user_id": 1},
    ):
        response = client.get(
            "/heatmap/session?ticket=" + "x" * 24,
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/heatmap/app"
    cookie = response.headers["set-cookie"]
    assert "velo_heatmap_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "ticket=" not in response.headers["location"]


def test_manifest_binds_version_and_queues_only_base_tiles(client):
    token = heatmap_web.create_session_token(1, 1)
    payload = {
        "generation": 7,
        "cache_version": "g7-deadbeef",
        "min_zoom": 3,
        "max_zoom": 18,
        "tile_count": 3,
        "activity_count": 293,
        "center": {"longitude": 112.56, "latitude": 37.85},
        "available_years": [2026],
        "focus_points": [[112.4, 37.7], [112.7, 38.0]],
        "all_points": [[110.0, 35.0], [118.0, 41.0]],
        "tiles": {
            "3": [[6, 3]],
            "11": [[1664, 791]],
            "15": [[26620, 12680]],
            "18": [[213000, 101300]],
        },
    }
    with (
        patch(
            "app.heatmap_web.router.user_service.get_user_heatmap_tile_manifest",
            return_value=payload,
        ),
        patch("app.heatmap_web.router.heatmap_web.remember_session_version") as remember,
        patch("app.heatmap_web.router.heatmap_web.remember_session_coverage"),
        patch(
            "app.heatmap_web.router.heatmap_web.enqueue_stale_artifact_prune",
            return_value=True,
        ) as prune,
        patch(
            "app.heatmap_web.router.heatmap_web.enqueue_base_tile_prewarm",
            return_value=1,
        ) as enqueue,
    ):
        response = client.get(
            "/heatmap/manifest",
            cookies={"velo_heatmap_session": token},
        )
    assert response.status_code == 200
    assert response.json()["min_zoom"] == 3
    assert response.json()["fallback_max_zoom"] == 15
    assert response.json()["coverage_mode"] == "parent"
    assert response.json()["coverage_max_zoom"] == 15
    assert set(response.json()["tiles"]) == {"3", "11", "15"}
    assert "18" not in response.json()["tiles"]
    remember.assert_called_once()
    prune.assert_called_once_with(1, "owner", "g7-deadbeef")
    assert enqueue.call_args.args[-1] == [
        (3, 6, 3),
        (11, 1664, 791),
        (15, 26620, 12680),
    ]


def test_public_manifest_never_queues_private_base_tiles(client):
    token = heatmap_web.create_session_token(1, 2)
    payload = {
        "generation": 7,
        "cache_version": "g7-public",
        "min_zoom": 3,
        "max_zoom": 18,
        "tile_count": 1,
        "activity_count": 1,
        "center": {"longitude": 112.56, "latitude": 37.85},
        "available_years": [2026],
        "focus_points": [[112.4, 37.7], [112.7, 38.0]],
        "all_points": [[112.4, 37.7], [112.7, 38.0]],
        "tiles": {"11": [[1664, 791]]},
    }
    with (
        patch(
            "app.heatmap_web.router.user_service.get_user_heatmap_tile_manifest",
            return_value=payload,
        ) as manifest,
        patch("app.heatmap_web.router.heatmap_web.remember_session_version"),
        patch("app.heatmap_web.router.heatmap_web.remember_session_coverage"),
        patch(
            "app.heatmap_web.router.heatmap_web.enqueue_stale_artifact_prune",
            return_value=True,
        ) as prune,
        patch(
            "app.heatmap_web.router.heatmap_web.enqueue_base_tile_prewarm"
        ) as prewarm,
    ):
        response = client.get(
            "/heatmap/manifest",
            cookies={"velo_heatmap_session": token},
        )

    assert response.status_code == 200
    assert response.json()["audience"] == "public"
    assert manifest.call_args.kwargs["include_private"] is False
    assert manifest.call_args.kwargs["min_zoom"] == 3
    prune.assert_called_once_with(2, "public", "g7-public")
    prewarm.assert_not_called()


def test_live_tile_requires_manifest_bound_version(client):
    token = heatmap_web.create_session_token(1, 1)
    with (
        patch(
            "app.heatmap_web.router.heatmap_web.validate_session_version",
            side_effect=heatmap_web.HeatmapWebSessionError("热图版本已更新，请刷新页面"),
        ),
        patch("app.heatmap_web.router.heatmap_web.get_live_tile_artifact") as render,
    ):
        response = client.get(
            "/heatmap/live-tiles/g1-old/15/1/1.png",
            cookies={"velo_heatmap_session": token},
        )
    assert response.status_code == 401
    render.assert_not_called()


def test_live_tile_rejects_generation_revoked_after_manifest(client):
    token = heatmap_web.create_session_token(1, 1)
    with (
        patch("app.heatmap_web.router.heatmap_web.validate_session_version"),
        patch("app.heatmap_web.router.heatmap_web.validate_session_tile"),
        patch(
            "app.heatmap_web.router.heatmap_web.validate_current_artifact_version",
            side_effect=heatmap_web.HeatmapWebSessionError(
                "热图版本已更新，请刷新页面"
            ),
        ),
        patch("app.heatmap_web.router.heatmap_web.get_live_tile_artifact") as render,
    ):
        response = client.get(
            "/heatmap/live-tiles/g7-stale/15/1/1.png",
            cookies={"velo_heatmap_session": token},
        )
    assert response.status_code == 401
    render.assert_not_called()


def test_same_generation_db_fingerprint_change_revokes_old_artifact():
    with patch(
        "app.user.service_heatmap_tiles.get_current_heatmap_tile_version",
        return_value="g7-dnewfingerprint",
    ):
        try:
            heatmap_web.validate_current_artifact_version(
                Mock(), 1, "public", "g7-doldfingerprint"
            )
        except heatmap_web.HeatmapWebSessionError as exc:
            assert "版本已更新" in str(exc)
        else:
            raise AssertionError("Redis generation 未推进时旧公开 PNG 被继续读取")


def test_privacy_change_during_tile_read_is_checked_again_before_response(client):
    token = heatmap_web.create_session_token(1, 1)
    with (
        patch("app.heatmap_web.router.heatmap_web.validate_session_version"),
        patch("app.heatmap_web.router.heatmap_web.validate_session_tile"),
        patch(
            "app.heatmap_web.router.heatmap_web.validate_current_artifact_version",
            side_effect=[
                None,
                heatmap_web.HeatmapWebSessionError(
                    "热图版本已更新，请刷新页面"
                ),
            ],
        ) as validate,
        patch(
            "app.heatmap_web.router.heatmap_web.get_live_tile_artifact",
            return_value=b"old-private-png",
        ) as render,
    ):
        response = client.get(
            "/heatmap/live-tiles/g7-old/15/1/1.png",
            cookies={"velo_heatmap_session": token},
        )
    assert response.status_code == 401
    assert validate.call_count == 2
    render.assert_called_once()


def test_manifest_outside_tile_returns_blank_without_db_or_disk_renderer(client):
    token = heatmap_web.create_session_token(1, 1)
    with (
        patch("app.heatmap_web.router.heatmap_web.validate_session_version"),
        patch(
            "app.heatmap_web.router.heatmap_web.validate_session_tile",
            side_effect=heatmap_web.HeatmapTileNotCovered(
                "heatmap tile outside manifest"
            ),
        ),
        patch(
            "app.heatmap_web.router.heatmap_web.validate_current_artifact_version"
        ) as current,
        patch("app.heatmap_web.router.heatmap_web.get_live_tile_artifact") as render,
    ):
        response = client.get(
            "/heatmap/live-tiles/g8-current/15/100/200.png",
            cookies={"velo_heatmap_session": token},
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    with Image.open(BytesIO(response.content)) as image:
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0
    current.assert_not_called()
    render.assert_not_called()
