"""
v5 task-1.C.1：app/monitor/processing_health.py 真 PG 集成测试。

为啥不用 SQLite mock：
- Activity.updated_at 是 tz-aware（DateTime(timezone=True)）
- SQLite 不存 timezone 信息，读出来变 naive → datetime.now(UTC) - naive 抛 TypeError（陷阱 #2）
- monitor 函数本身正确，是 SQLite 不准 / 不是代码 bug

测试覆盖 5 条路径（全 mock httpx 不真调飞书）：
1. 无 stuck activity → 返空 + 不调 webhook
2. 有 stuck 5+ 分钟 → 返 id + 调 webhook 一次（含告警文本断言）
3. processing < 4 分钟 → 不算 stuck（返空 + 不调）
4. 飞书 5xx / 网络异常 → catch 后仍返 stuck list
5. FEISHU_BOT_WEBHOOK 未配 → 跳过推送但仍返 stuck list

测试间用 _PREFIX 隔离 + 结束清理。
"""

import os
from datetime import datetime, timedelta, timezone
import logging
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity
from app.monitor import processing_health
from app.user.models import User


UTC = timezone.utc
_PREFIX = "[task-1.C.1 monitor]"


def _db_url() -> str:
    """容器内用 DATABASE_URL，宿主机退回 localhost:5435。"""
    return (
        os.getenv("VELO_TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql://velo:velo@localhost:5435/velo"
    )


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_db_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"dev stack PostgreSQL 不可用: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session(pg_engine):
    Session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        _cleanup(db)
        yield db
    finally:
        _cleanup(db)
        db.close()


def _cleanup(db):
    db.execute(text(
        "DELETE FROM activities WHERE title LIKE :prefix"
    ), {"prefix": f"{_PREFIX}%"})
    db.execute(text(
        "DELETE FROM users WHERE openid LIKE :prefix"
    ), {"prefix": "monitor_test_%"})
    db.commit()


def _make_user(db, suffix: str) -> User:
    u = User(openid=f"monitor_test_{suffix}", nickname="monitor 测试用户")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_processing_activity(db, user_id: int, suffix: str, updated_minutes_ago: int) -> Activity:
    """直插一条 status='processing' 的 activity / updated_at 强制设为 N 分钟前。"""
    now = datetime.now(UTC)
    a = Activity(
        user_id=user_id,
        title=f"{_PREFIX} {suffix}",
        status="processing",
        data_source="gpx",
        activity_type="cycling",
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    # 直接 UPDATE updated_at 到指定过去时间（绕过 onupdate 自动覆盖）
    db.execute(
        update(Activity).where(Activity.id == a.id).values(
            updated_at=now - timedelta(minutes=updated_minutes_ago),
        )
    )
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture()
def fake_webhook(monkeypatch):
    """假 webhook URL 让推送路径被触发；真请求由 patch httpx mock 拦截。"""
    from app.config import settings
    monkeypatch.setattr(settings, "FEISHU_BOT_WEBHOOK", "https://fake-feishu.local/webhook")
    return "https://fake-feishu.local/webhook"


def test_scan_no_stuck_activities_returns_empty(pg_session, fake_webhook):
    """全无 stuck → 返 [] 不调 webhook。"""
    user = _make_user(pg_session, "no_stuck")
    # 不建任何 processing activity

    with patch.object(processing_health, "httpx") as mock_httpx:
        result = processing_health.scan_processing_health(pg_session)

    assert result == []
    mock_httpx.post.assert_not_called()


def test_scan_stuck_5min_triggers_alert(pg_session, fake_webhook):
    """processing 卡 5 分钟 → 返 id + 调 webhook 一次 + 告警文本含 user/id/elapsed。"""
    user = _make_user(pg_session, "stuck5")
    a = _make_processing_activity(pg_session, user.id, "stuck5", updated_minutes_ago=5)

    with patch.object(processing_health, "httpx") as mock_httpx:
        result = processing_health.scan_processing_health(pg_session)

    assert a.id in result
    mock_httpx.post.assert_called_once()
    call_args = mock_httpx.post.call_args
    body = call_args.kwargs["json"]["content"]["text"]
    assert f"id={a.id}" in body
    assert f"user_id={user.id}" in body
    assert "elapsed=" in body


def test_scan_processing_under_4min_no_alert(pg_session, fake_webhook):
    """processing 才 2 分钟 < 4 阈值 → 不告警。"""
    user = _make_user(pg_session, "ok2min")
    _make_processing_activity(pg_session, user.id, "ok2min", updated_minutes_ago=2)

    with patch.object(processing_health, "httpx") as mock_httpx:
        result = processing_health.scan_processing_health(pg_session)

    assert result == []
    mock_httpx.post.assert_not_called()


def test_scan_feishu_network_error_swallowed_returns_stuck_list(pg_session, fake_webhook):
    """网络层异常（连不上 / 超时）→ catch 后仍返 stuck list。"""
    user = _make_user(pg_session, "feishu_net")
    a = _make_processing_activity(pg_session, user.id, "feishu_net", updated_minutes_ago=6)

    with patch.object(processing_health, "httpx") as mock_httpx:
        mock_httpx.post.side_effect = RuntimeError("simulated network down")
        result = processing_health.scan_processing_health(pg_session)

    assert a.id in result
    mock_httpx.post.assert_called_once()


def test_scan_feishu_5xx_response_swallowed_returns_stuck_list(
    pg_session,
    fake_webhook,
    caplog,
):
    """
    飞书 502 响应 → raise_for_status() 抛 HTTPStatusError → catch 后仍返 stuck list
    （codex 异源审 2026-04-30 抓 Important：httpx.post 默认遇 5xx 不抛 / 必须 raise_for_status）。
    """
    import httpx as real_httpx

    user = _make_user(pg_session, "feishu_5xx")
    a = _make_processing_activity(pg_session, user.id, "feishu_5xx", updated_minutes_ago=6)

    # 构造一个真假 Response 对象 / status_code=502，调 raise_for_status() 会抛 HTTPStatusError
    fake_response = real_httpx.Response(
        status_code=502,
        request=real_httpx.Request(
            "POST",
            "https://fake-feishu.local/webhook?secret=must-not-enter-monitor-log",
        ),
    )

    with caplog.at_level(logging.ERROR, logger=processing_health.logger.name):
        with patch.object(processing_health, "httpx") as mock_httpx:
            mock_httpx.post.return_value = fake_response
            # 把 patch 的 httpx 模块的异常类指回真 httpx，让 raise_for_status 能正常抛
            mock_httpx.HTTPStatusError = real_httpx.HTTPStatusError
            # 不该抛异常给 caller
            result = processing_health.scan_processing_health(pg_session)

    assert a.id in result
    mock_httpx.post.assert_called_once()
    assert "must-not-enter-monitor-log" not in caplog.text
    assert "error_type=HTTPStatusError" in caplog.text
    assert "status_code=502" in caplog.text


def test_scan_no_webhook_skips_post_keeps_stuck_list(pg_session, monkeypatch):
    """FEISHU_BOT_WEBHOOK="" → 跳过推送但仍返 stuck list。"""
    from app.config import settings
    monkeypatch.setattr(settings, "FEISHU_BOT_WEBHOOK", "")

    user = _make_user(pg_session, "no_webhook")
    a = _make_processing_activity(pg_session, user.id, "no_webhook", updated_minutes_ago=7)

    with patch.object(processing_health, "httpx") as mock_httpx:
        result = processing_health.scan_processing_health(pg_session)

    assert a.id in result
    mock_httpx.post.assert_not_called()
