"""
admin H5 端到端探针单测（task-monitor-admin-h5）。

不连真 docker network（CI 没有 admin-h5 容器），全 mock httpx：
- 5 条路径覆盖 / 与 task-1.C.1 测试风格保持一致
- 不真调飞书 / 用 mock 验证调用次数 + 文本内容
"""

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.monitor import admin_h5_health


WEBHOOK_SECRET_MARKER = "must-not-enter-admin-monitor-log"


@pytest.fixture(autouse=True)
def _fresh_redis_dedup(monkeypatch):
    """每个测试自动给一个 mock redis_conn / 默认 `set` 返 True（首次发送）。

    防测试间相互影响（同一进程跑多个 test 同 sig 会被静默掉）+ 不真连 Redis。
    个别测试想要"已 dedup"场景再覆盖 set 的返回值。
    """
    fake_redis = MagicMock()
    fake_redis.set = MagicMock(return_value=True)  # 默认让告警发出去
    monkeypatch.setattr("app.queue.redis_conn", fake_redis)
    return fake_redis


def _make_response(status_code: int) -> MagicMock:
    """造一个 mock httpx.Response，避免真实 Response 构造对 status_code 的限制。"""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture()
def configured_webhook(monkeypatch):
    """大多数测试假设 FEISHU_BOT_WEBHOOK 已配（生产场景）。"""
    monkeypatch.setattr(
        admin_h5_health.settings,
        "FEISHU_BOT_WEBHOOK",
        f"https://example.com/feishu/test?secret={WEBHOOK_SECRET_MARKER}",
    )


def test_all_green_returns_empty_no_webhook_call(configured_webhook):
    """两个探测项都 200/401（预期值）→ 返空列表 + 不调 webhook。"""

    def fake_get(url, **kwargs):
        if url.endswith("/"):
            return _make_response(200)  # 静态站
        if "/api/admin/whoami" in url:
            return _make_response(401)  # 反代到 api 通畅
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(httpx, "get", side_effect=fake_get) as mock_get, \
         patch.object(httpx, "post") as mock_post:
        result = admin_h5_health.scan_admin_h5_health()

    assert result == []
    assert mock_get.call_count == 2
    mock_post.assert_not_called()  # 全绿不发告警


def test_static_site_502_triggers_alert(configured_webhook):
    """静态站返 502（admin-h5 nginx 挂）→ 探测失败 + 告警。"""

    def fake_get(url, **kwargs):
        if url.endswith("/"):
            return _make_response(502)
        return _make_response(401)

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post:
        result = admin_h5_health.scan_admin_h5_health()

    assert "static_site" in result
    assert mock_post.call_count == 1
    posted_text = mock_post.call_args.kwargs["json"]["content"]["text"]
    assert "static_site" in posted_text
    assert "502" in posted_text


def test_api_proxy_502_triggers_alert(configured_webhook):
    """反代到 api 返 502（即本次 2026-05-06 事故场景）→ 告警 + 包含 api_proxy。"""

    def fake_get(url, **kwargs):
        if url.endswith("/"):
            return _make_response(200)
        if "/api/admin/whoami" in url:
            return _make_response(502)  # 真实事故场景
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post:
        result = admin_h5_health.scan_admin_h5_health()

    assert result == ["api_proxy"]
    posted_text = mock_post.call_args.kwargs["json"]["content"]["text"]
    assert "api_proxy" in posted_text
    assert "nginx 反代挂" in posted_text


def test_network_error_treated_as_failure(configured_webhook):
    """网络层错（admin-h5 容器挂 / DNS 不到）→ 探测失败 + 告警含 network 关键字。"""

    def fake_get(url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post:
        result = admin_h5_health.scan_admin_h5_health()

    # 两条都网络失败
    assert "static_site" in result
    assert "api_proxy" in result
    posted_text = mock_post.call_args.kwargs["json"]["content"]["text"]
    assert "network" in posted_text
    assert "ConnectError" in posted_text


def test_feishu_webhook_failure_does_not_block(configured_webhook, caplog):
    """飞书 webhook 5xx / 网络异常 → catch 后仍返失败列表（业务不阻断）。"""

    def fake_get(url, **kwargs):
        return _make_response(502)  # 触发告警

    def fake_post(*args, **kwargs):
        request = httpx.Request(
            "POST",
            f"https://example.com/feishu/test?secret={WEBHOOK_SECRET_MARKER}",
        )
        response = httpx.Response(502, request=request)
        raise httpx.HTTPStatusError("feishu down", request=request, response=response)

    with caplog.at_level(logging.ERROR, logger=admin_h5_health.logger.name):
        with patch.object(httpx, "get", side_effect=fake_get), \
             patch.object(httpx, "post", side_effect=fake_post):
            result = admin_h5_health.scan_admin_h5_health()

    # 即便飞书挂，仍返失败项让 main() 退码 1
    assert "static_site" in result
    assert "api_proxy" in result
    assert WEBHOOK_SECRET_MARKER not in caplog.text
    assert "error_type=HTTPStatusError" in caplog.text
    assert "status_code=502" in caplog.text


def test_unconfigured_webhook_skips_post_but_returns_failures(monkeypatch):
    """FEISHU_BOT_WEBHOOK 未配（dev / CI）→ 跳过 webhook 但仍返失败列表。"""
    monkeypatch.setattr(admin_h5_health.settings, "FEISHU_BOT_WEBHOOK", "")

    def fake_get(url, **kwargs):
        return _make_response(502)

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post:
        result = admin_h5_health.scan_admin_h5_health()

    assert "static_site" in result
    mock_post.assert_not_called()  # 未配 webhook 不该调


def test_main_exit_code_green():
    """main() 全绿返 0。"""

    def fake_get(url, **kwargs):
        if url.endswith("/"):
            return _make_response(200)
        return _make_response(401)

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post"):
        assert admin_h5_health.main() == 0


def test_main_exit_code_failure():
    """main() 任意一项失败返 1（cron 监控用）。"""

    def fake_get(url, **kwargs):
        return _make_response(502)

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post"):
        assert admin_h5_health.main() == 1


def test_api_proxy_200_treated_as_failure(configured_webhook):
    """反代探测严格断言 4xx：200 应判失败（codex I1：SPA fallback 漏报防御）。

    场景：admin-h5 nginx 配置坏 / location /api/ 失效 → 请求落到 location /
    被 try_files 兜底返 SPA index.html 200，反代实际挂但旧版宽松判定会漏报。
    """

    def fake_get(url, **kwargs):
        if url.endswith("/"):
            return _make_response(200)  # 静态站正常
        if "/api/admin/whoami" in url:
            return _make_response(200)  # 反代失效落到 SPA fallback
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post:
        result = admin_h5_health.scan_admin_h5_health()

    assert "api_proxy" in result
    posted_text = mock_post.call_args.kwargs["json"]["content"]["text"]
    assert "反代未生效" in posted_text or "SPA fallback" in posted_text


def test_alert_deduplication_within_ttl(configured_webhook, _fresh_redis_dedup):
    """同 sig 5 分钟内只发一次飞书（codex I2：告警风暴防御）。"""

    def fake_get(url, **kwargs):
        return _make_response(502)  # 持续失败

    # 第 1 次：Redis SETNX 成功（首次） → 发 webhook
    _fresh_redis_dedup.set.return_value = True
    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post_1:
        result_1 = admin_h5_health.scan_admin_h5_health()

    assert mock_post_1.call_count == 1
    assert "static_site" in result_1
    # 验证 Redis SETNX 调用参数（key + ex + nx）
    set_call = _fresh_redis_dedup.set.call_args
    assert "monitor:admin_h5:last_alert:" in set_call.args[0]
    assert set_call.kwargs["nx"] is True
    assert set_call.kwargs["ex"] == admin_h5_health.ALERT_DEDUP_TTL_SEC

    # 第 2 次：Redis SETNX 返 False（key 还在 TTL 内）→ 静默不发 webhook
    _fresh_redis_dedup.set.return_value = False
    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post_2:
        result_2 = admin_h5_health.scan_admin_h5_health()

    # 仍返失败列表（main 退码 1 / 内部状态正确），但不重复发飞书
    assert "static_site" in result_2
    mock_post_2.assert_not_called()


def test_alert_dedup_redis_failure_falls_back_to_sending(configured_webhook, _fresh_redis_dedup):
    """Redis 不可达时退化为不去抖（宁可重复也不漏告警）。"""
    _fresh_redis_dedup.set.side_effect = ConnectionError("redis down")

    def fake_get(url, **kwargs):
        return _make_response(502)

    with patch.object(httpx, "get", side_effect=fake_get), \
         patch.object(httpx, "post") as mock_post:
        result = admin_h5_health.scan_admin_h5_health()

    assert "static_site" in result
    mock_post.assert_called_once()  # Redis 挂仍发告警
