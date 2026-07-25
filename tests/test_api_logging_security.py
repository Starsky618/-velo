"""API 日志不能把第三方请求 URL 中的凭据写进容器日志。"""

import logging
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from app.main import app as _app  # noqa: F401  导入入口配置真实 API 日志等级
from app.middleware import rate_limit


def test_api_suppresses_http_client_request_urls_at_info_level(caplog):
    secret_marker = "key=must-not-enter-api-log&sig=must-not-enter-api-log"

    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info(
            "HTTP Request: GET https://provider.invalid/path?%s",
            secret_marker,
        )
        logging.getLogger("httpcore").info(
            "request.url=https://provider.invalid/path?%s",
            secret_marker,
        )

    assert secret_marker not in caplog.text
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_rate_limit_webhook_error_does_not_log_signed_url(monkeypatch, caplog):
    secret_marker = "must-not-enter-rate-limit-log"
    webhook = f"https://example.com/feishu/hook?secret={secret_marker}"
    monkeypatch.setattr(rate_limit.settings, "FEISHU_BOT_WEBHOOK", webhook)

    fake_redis = MagicMock()
    fake_redis.incr.return_value = 2
    fake_redis.set.return_value = True
    monkeypatch.setattr(rate_limit, "redis_conn", fake_redis)

    response = httpx.Response(502, request=httpx.Request("POST", webhook))
    monkeypatch.setattr(rate_limit.httpx, "post", lambda *args, **kwargs: response)

    with caplog.at_level(logging.ERROR, logger=rate_limit.logger.name):
        with pytest.raises(HTTPException) as exc_info:
            rate_limit.check_rate_limit_by_user(7, "test", 1, 60)

    assert exc_info.value.status_code == 429
    assert secret_marker not in caplog.text
    assert "error_type=HTTPStatusError" in caplog.text
    assert "status_code=502" in caplog.text
