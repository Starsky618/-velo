"""腾讯地点检索测试：只 mock 腾讯网络请求，锁住太原地名查坐标这层防线。"""

import json
import os
import subprocess
import sys

import httpx
import pytest

from app.config import settings
from app.route_book.tencent_direction import TencentMapConfigError, TencentMapError


def test_search_place_sends_region_boundary_and_signed_params(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": 0,
                "data": [
                    {
                        "title": "蒙山大佛",
                        "address": "太原市晋源区",
                        "location": {"lat": 37.7101, "lng": 112.4312},
                    }
                ],
            }

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    def fake_convert(lat, lon):
        captured["converted_from"] = (lat, lon)
        return 37.704, 112.425

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_place.httpx.get", fake_get)
    monkeypatch.setattr("app.route_book.tencent_place.gcj02_to_wgs84", fake_convert)

    from app.route_book.tencent_place import _TENCENT_PLACE_PATH, _build_sig, search_place

    result = search_place("蒙山大佛")

    assert captured["url"].endswith("/ws/place/v1/search")
    assert captured["params"]["keyword"] == "蒙山大佛"
    assert captured["params"]["boundary"] == "region(太原,0)"
    assert captured["params"]["key"] == "test-key"
    assert captured["params"]["output"] == "json"
    assert captured["params"]["sig"] == _build_sig(
        _TENCENT_PLACE_PATH,
        {
            "keyword": "蒙山大佛",
            "boundary": "region(太原,0)",
            "key": "test-key",
            "output": "json",
        },
        "test-sk",
    )
    assert "test-sk" not in captured["params"].values()
    assert captured["timeout"] == 8.0
    assert captured["converted_from"] == (37.7101, 112.4312)
    assert result == {
        "keyword": "蒙山大佛",
        "title": "蒙山大佛",
        "address": "太原市晋源区",
        "lat": 37.704,
        "lon": 112.425,
        "source": "tencent_place",
    }


def test_search_place_returns_none_when_tencent_has_no_data(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": 0, "data": []}

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_place.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.route_book.tencent_place import search_place

    assert search_place("不存在的太原地点") is None


def test_search_place_reuses_config_error_when_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")

    from app.route_book.tencent_place import search_place

    with pytest.raises(TencentMapConfigError, match="TENCENT_MAP_KEY"):
        search_place("蒙山大佛")


def test_search_place_raises_tencent_error_for_network_and_api_failure(monkeypatch):
    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")

    def boom(*args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("app.route_book.tencent_place.httpx.get", boom)

    from app.route_book.tencent_place import search_place

    with pytest.raises(TencentMapError, match="腾讯地点检索请求失败"):
        search_place("蒙山大佛")


def test_search_place_http_status_error_does_not_expose_key_or_sig(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            request = httpx.Request(
                "GET",
                "https://apis.map.qq.com/ws/place/v1/search?key=test-key&sig=test-sig",
            )
            response = httpx.Response(403, request=request)
            response.raise_for_status()

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_place.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.route_book.tencent_place import search_place

    with pytest.raises(TencentMapError) as exc_info:
        search_place("蒙山大佛")

    message = str(exc_info.value)
    assert "腾讯地点检索请求失败" in message
    assert "test-key" not in message
    assert "test-sig" not in message
    assert "test-sk" not in message


def test_search_place_raises_tencent_error_for_bad_location(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": 0,
                "data": [{"title": "坏坐标", "location": {"lat": 91.0, "lng": 112.4}}],
            }

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_place.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.route_book.tencent_place import search_place

    with pytest.raises(TencentMapError, match="地点坐标越界"):
        search_place("坏坐标")


def test_poi_lookup_prints_json_without_secret(monkeypatch, capsys):
    def fake_search_place(keyword, region="太原"):
        assert region == "太原"
        if keyword == "不存在":
            return None
        return {
            "keyword": keyword,
            "title": keyword,
            "address": "太原市晋源区",
            "lat": 37.704,
            "lon": 112.425,
            "source": "tencent_place",
        }

    monkeypatch.setattr("app.route_book.tencent_place.search_place", fake_search_place)

    from scripts.poi_lookup import main

    exit_code = main(["蒙山大佛", "不存在"])

    assert exit_code == 0
    output = capsys.readouterr().out
    body = json.loads(output)
    assert body == [
        {
            "keyword": "蒙山大佛",
            "title": "蒙山大佛",
            "address": "太原市晋源区",
            "lat": 37.704,
            "lon": 112.425,
            "source": "tencent_place",
        },
        {"keyword": "不存在", "result": None},
    ]
    assert "test-sk" not in output


def test_poi_lookup_can_run_as_direct_script_without_import_crash():
    env = os.environ.copy()
    env["TENCENT_MAP_KEY"] = ""
    env["TENCENT_MAP_SK"] = ""

    completed = subprocess.run(
        [sys.executable, "scripts/poi_lookup.py", "蒙山大佛"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stderr)["error"] == "TENCENT_MAP_KEY / TENCENT_MAP_SK 未配置"
    assert "ModuleNotFoundError" not in completed.stderr
