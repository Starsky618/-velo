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
                        "id": "poi-main",
                        "title": "蒙山大佛",
                        "address": "太原市晋源区",
                        "category": "旅游景点:人文古迹",
                        # 官方文档和真实回包的类型可能不一致，出口统一为字符串
                        "category_code": 110201,
                        "type": 0,
                        "ad_info": {
                            "adcode": 140110,
                            "province": "山西省",
                            "city": "太原市",
                            "district": "晋源区",
                        },
                        "location": {"lat": 37.7101, "lng": 112.4312},
                        "tel": "should-not-leak",
                        "sub_pois": [
                            {
                                "id": 9988,
                                "title": "蒙山大佛入口",
                                "address": "蒙山景区入口",
                                "category_code": "110201",
                                "location": {"lat": 37.711, "lng": 112.432},
                                "tel": "sub-secret",
                            }
                        ],
                    }
                ],
            }

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    def fake_convert(lat, lon):
        captured.setdefault("converted_from", []).append((lat, lon))
        if (lat, lon) == (37.7101, 112.4312):
            return 37.704, 112.425
        return 37.705, 112.426

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_place.httpx.get", fake_get)
    monkeypatch.setattr("app.route_book.tencent_place.gcj02_to_wgs84", fake_convert)

    from app.route_book.tencent_place import _TENCENT_PLACE_PATH, _build_sig, search_place

    result = search_place("蒙山大佛")

    assert captured["url"].endswith("/ws/place/v1/search")
    assert captured["params"]["keyword"] == "蒙山大佛"
    assert captured["params"]["boundary"] == "region(太原,0)"
    assert captured["params"]["added_fields"] == "category_code"
    assert captured["params"]["get_subpois"] == "1"
    assert captured["params"]["key"] == "test-key"
    assert captured["params"]["output"] == "json"
    assert captured["params"]["sig"] == _build_sig(
        _TENCENT_PLACE_PATH,
        {
            "keyword": "蒙山大佛",
            "boundary": "region(太原,0)",
            "added_fields": "category_code",
            "get_subpois": "1",
            "key": "test-key",
            "output": "json",
        },
        "test-sk",
    )
    assert "test-sk" not in captured["params"].values()
    assert captured["timeout"] == 8.0
    assert captured["converted_from"] == [
        (37.7101, 112.4312),
        (37.711, 112.432),
    ]
    assert result == {
        "keyword": "蒙山大佛",
        "title": "蒙山大佛",
        "address": "太原市晋源区",
        "lat": 37.704,
        "lon": 112.425,
        "source": "tencent_place",
        "provider_poi_id": "poi-main",
        "category": "旅游景点:人文古迹",
        "category_code": "110201",
        "type": "0",
        "adcode": "140110",
        "province": "山西省",
        "city": "太原市",
        "district": "晋源区",
        "gcj_lat": 37.7101,
        "gcj_lon": 112.4312,
        "sub_pois": [
            {
                "keyword": "蒙山大佛",
                "title": "蒙山大佛入口",
                "address": "蒙山景区入口",
                "lat": 37.705,
                "lon": 112.426,
                "source": "tencent_sub_place",
                "provider_poi_id": "9988",
                "category": None,
                "category_code": "110201",
                "type": None,
                "adcode": None,
                "province": None,
                "city": None,
                "district": None,
                "gcj_lat": 37.711,
                "gcj_lon": 112.432,
            }
        ],
    }
    assert "should-not-leak" not in repr(result)
    assert "sub-secret" not in repr(result)


def test_suggest_places_preserves_provider_fields_with_stable_types(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": 0,
                "data": [
                    {
                        "id": 123,
                        "title": "迎泽大桥",
                        "address": "迎泽区",
                        "category": "基础设施:道路附属:桥",
                        "category_code": 271214,
                        "type": 0,
                        "ad_info": {
                            "adcode": 140106,
                            "province": "山西省",
                            "city": "太原市",
                            "district": "迎泽区",
                        },
                        "location": {"lat": "37.86", "lng": "112.56"},
                        "tel": "private-phone",
                    },
                    {
                        "id": "poi-tunnel",
                        "title": "天清隧道",
                        "category": "地名地址:道路名",
                        "category_code": "261200",
                        "type": "0",
                        "adcode": "140110",
                        "province": "山西省",
                        "city": "太原市",
                        "district": "晋源区",
                        "location": {"lat": 37.70, "lng": 112.40},
                    },
                    {
                        "id": "bad-coordinate",
                        "title": "坏坐标",
                        "location": {"lat": 91, "lng": 112.4},
                    },
                ],
            }

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_place.httpx.get", fake_get)
    monkeypatch.setattr(
        "app.route_book.tencent_place.gcj02_to_wgs84",
        lambda lat, lon: (lat - 0.01, lon - 0.01),
    )

    from app.route_book.tencent_place import _TENCENT_SUGGEST_PATH, _build_sig, suggest_places

    result = suggest_places(" 迎泽 ")

    assert captured["url"].endswith("/ws/place/v1/suggestion")
    assert captured["params"]["added_fields"] == "category_code"
    assert captured["params"]["sig"] == _build_sig(
        _TENCENT_SUGGEST_PATH,
        {
            "keyword": "迎泽",
            "region": "太原",
            "region_fix": "1",
            "page_index": "1",
            "page_size": "8",
            "added_fields": "category_code",
            "key": "test-key",
            "output": "json",
        },
        "test-sk",
    )
    assert captured["timeout"] == 8.0
    assert len(result) == 2
    assert result[0] == {
        "keyword": "迎泽",
        "title": "迎泽大桥",
        "address": "迎泽区",
        "lat": 37.85,
        "lon": 112.55,
        "source": "tencent_suggestion",
        "provider_poi_id": "123",
        "category": "基础设施:道路附属:桥",
        "category_code": "271214",
        "type": "0",
        "adcode": "140106",
        "province": "山西省",
        "city": "太原市",
        "district": "迎泽区",
        "gcj_lat": 37.86,
        "gcj_lon": 112.56,
    }
    assert result[1]["provider_poi_id"] == "poi-tunnel"
    assert result[1]["category_code"] == "261200"
    assert result[1]["adcode"] == "140110"
    assert "private-phone" not in repr(result)


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
