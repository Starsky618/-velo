"""生产 API 合同探针单测：只用 MockTransport，不连接生产。"""

import json

import httpx
import pytest

from scripts import check_live_api_contract as probe


REQUIREMENTS = [
    ("POST", "/api/route-books/manual-drawn"),
    ("POST", "/api/route-books/manual-drawn/snap-preview"),
    ("GET", "/api/route-books/{route_book_id}/detail"),
]


def _transport(*, paths=None, health_status=200, health_body=None, openapi_status=200):
    paths = paths if paths is not None else {
        "/api/route-books/manual-drawn": {"post": {}},
        "/api/route-books/manual-drawn/snap-preview": {"post": {}},
        "/api/route-books/{route_book_id}/detail": {"get": {}},
    }
    health_body = health_body if health_body is not None else {"status": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(health_status, json=health_body)
        if request.url.path == "/openapi.json":
            return httpx.Response(
                openapi_status,
                json={
                    "openapi": "3.1.0",
                    "info": {"title": "VELO API"},
                    "paths": paths,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    return httpx.MockTransport(handler)


def test_contract_passes_when_all_methods_exist():
    result = probe.probe_live_api_contract(
        "https://api.weiluai.top/",
        REQUIREMENTS,
        transport=_transport(),
    )

    assert result["status"] == "pass"
    assert result["missing"] == []
    assert result["openapi"] == {
        "http_status": 200,
        "version": "3.1.0",
        "title": "VELO API",
        "path_count": 3,
    }


@pytest.mark.parametrize(
    ("paths", "missing"),
    [
        (
            {
                "/api/route-books/manual-drawn": {"post": {}},
                "/api/route-books/manual-drawn/snap-preview": {"post": {}},
            },
            "GET:/api/route-books/{route_book_id}/detail",
        ),
        (
            {
                "/api/route-books/manual-drawn": {"get": {}},
                "/api/route-books/manual-drawn/snap-preview": {"post": {}},
                "/api/route-books/{route_book_id}/detail": {"get": {}},
            },
            "POST:/api/route-books/manual-drawn",
        ),
    ],
)
def test_contract_mismatch_names_missing_method_or_path(paths, missing):
    result = probe.probe_live_api_contract(
        "https://api.weiluai.top",
        REQUIREMENTS,
        transport=_transport(paths=paths),
    )

    assert result["status"] == "contract_mismatch"
    assert missing in result["missing"]


@pytest.mark.parametrize(
    "transport, reason",
    [
        (_transport(health_status=503), "health_http_503"),
        (_transport(health_body={"status": "degraded"}), "health_status_not_ok"),
        (_transport(openapi_status=404), "openapi_http_404"),
        (_transport(paths=[]), "openapi_paths_invalid"),
    ],
)
def test_unavailable_evidence_is_not_reported_as_contract_mismatch(transport, reason):
    result = probe.probe_live_api_contract(
        "https://api.weiluai.top",
        REQUIREMENTS,
        transport=transport,
    )

    assert result["status"] == "probe_unavailable"
    assert result["reason"] == reason
    assert result["missing"] == []


@pytest.mark.parametrize(
    ("openapi", "reason"),
    [
        (
            {"info": {"title": "VELO API"}, "paths": {}},
            "openapi_version_invalid",
        ),
        (
            {
                "openapi": "3.1.0",
                "info": {"title": "VELO API"},
                "paths": {"/api/route-books/manual-drawn": {"post": None}},
            },
            "openapi_operation_invalid",
        ),
    ],
)
def test_malformed_openapi_cannot_create_a_false_pass(openapi, reason):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json=openapi)

    result = probe.probe_live_api_contract(
        "https://api.weiluai.top",
        REQUIREMENTS,
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "probe_unavailable"
    assert result["reason"] == reason


def test_network_error_reports_only_exception_type():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret detail must not escape")

    result = probe.probe_live_api_contract(
        "https://api.weiluai.top",
        REQUIREMENTS,
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "probe_unavailable"
    assert result["error_type"] == "ConnectError"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "value",
    [
        "TRACE:/health",
        "POST:relative",
        "GET:/health?token=secret",
        "broken",
    ],
)
def test_parse_requirement_rejects_ambiguous_input(value):
    with pytest.raises(probe.InputError):
        probe.parse_requirement(value)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:secret@api.weiluai.top",
        "https://api.weiluai.top?token=secret",
        "https://api.weiluai.top/v1",
        "https://api.weiluai.top:bad",
        "https://[broken-ipv6",
        "file:///tmp/openapi.json",
    ],
)
def test_base_url_rejects_credentials_and_non_origin_urls(base_url):
    with pytest.raises(probe.InputError):
        probe.normalize_base_url(base_url)


def test_probe_sends_only_two_gets_without_auth_or_body():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(
            200,
            json={
                "info": {"title": "VELO API"},
                "openapi": "3.1.0",
                "paths": {
                    "/api/route-books/manual-drawn": {"post": {}},
                    "/api/route-books/manual-drawn/snap-preview": {"post": {}},
                    "/api/route-books/{route_book_id}/detail": {"get": {}},
                },
            },
        )

    result = probe.probe_live_api_contract(
        "https://api.weiluai.top",
        REQUIREMENTS,
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "pass"
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/health"),
        ("GET", "/openapi.json"),
    ]
    assert all("authorization" not in request.headers for request in requests)
    assert all(request.content == b"" for request in requests)


def test_main_returns_machine_readable_input_error(capsys):
    exit_code = probe.main(
        [
            "--base-url",
            "https://api.weiluai.top?token=secret",
            "--require",
            "GET:/health",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == probe.EXIT_INPUT
    assert output["status"] == "invalid_input"
    assert "secret" not in json.dumps(output)


def test_main_does_not_echo_invalid_requirement(capsys):
    exit_code = probe.main(
        [
            "--base-url",
            "https://api.weiluai.top",
            "--require",
            "GET:/health?token=secret",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == probe.EXIT_INPUT
    assert output == {"status": "invalid_input", "reason": "method/path 格式非法"}
    assert "secret" not in json.dumps(output)


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        ("pass", probe.EXIT_OK),
        ("probe_unavailable", probe.EXIT_UNAVAILABLE),
        ("contract_mismatch", probe.EXIT_MISMATCH),
    ],
)
def test_main_maps_probe_status_to_stable_exit_code(monkeypatch, capsys, status, expected_exit):
    monkeypatch.setattr(
        probe,
        "probe_live_api_contract",
        lambda *_args, **_kwargs: {"status": status},
    )

    exit_code = probe.main(
        [
            "--base-url",
            "https://api.weiluai.top",
            "--require",
            "GET:/health",
        ]
    )

    assert exit_code == expected_exit
    assert json.loads(capsys.readouterr().out)["status"] == status
