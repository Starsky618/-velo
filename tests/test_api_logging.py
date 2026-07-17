import logging

import httpx


def test_api_does_not_log_http_client_request_urls(caplog):
    """第三方请求 URL 可能带鉴权查询参数，API 日志不得以 INFO 输出。"""
    import app.main  # noqa: F401

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING

    caplog.set_level(logging.INFO)
    transport = httpx.MockTransport(lambda _request: httpx.Response(200))
    with httpx.Client(transport=transport) as client:
        response = client.get(
            "https://example.invalid/",
            params={"key": "test-secret", "sig": "test-signature"},
        )

    assert response.status_code == 200
    assert "test-secret" not in caplog.text
    assert "test-signature" not in caplog.text
