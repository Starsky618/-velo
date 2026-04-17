"""
Webhook subscription_id 校验测试（task-7.4）

验证 POST /api/strava/webhook 的双门校验逻辑：
- 第 1 道门：STRAVA_WEBHOOK_SUBSCRIPTION_ID 未配置或格式非法 → 503
- 第 2 道门：payload.subscription_id 和配置不匹配 → 403
- 匹配则走 service.handle_webhook_event 并返 200
"""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_webhook_rejects_when_not_configured(monkeypatch):
    """配置空串时返 503。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"subscription_id": 12345})
    assert resp.status_code == 503
    assert "未配置" in resp.json()["detail"]


def test_webhook_rejects_malformed_config(monkeypatch):
    """配置非数字也视为未配置（503）。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "abc")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"subscription_id": 12345})
    assert resp.status_code == 503


def test_webhook_rejects_wrong_subscription_id(monkeypatch):
    """subscription_id 不匹配返 403。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "999")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"subscription_id": 12345})
    assert resp.status_code == 403


def test_webhook_accepts_matching_subscription_id(monkeypatch):
    """subscription_id 匹配则走 service 并返 200。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "12345")

    # mock handle_webhook_event 防止真实 DB 调用
    from app.strava import service
    calls = []
    monkeypatch.setattr(
        service, "handle_webhook_event",
        lambda db, payload: calls.append(payload),
    )

    client = TestClient(app)
    resp = client.post(
        "/api/strava/webhook",
        json={"subscription_id": 12345, "object_type": "activity"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert len(calls) == 1
    assert calls[0]["subscription_id"] == 12345


def test_webhook_handles_missing_subscription_id_in_payload(monkeypatch):
    """payload 里没 subscription_id（伪造者漏填）也拦下。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "12345")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"object_type": "activity"})
    assert resp.status_code == 403
