"""
task-7.2：OAuth state 一次性消费的单测。

覆盖 4 个场景：
1. build_authorize_url 生成正确的 URL 和 Redis 写入
2. verify_state_and_consume happy path
3. state 未找到（过期/伪造）
4. 重放攻击（同 state 第二次使用必失败）
5. CSRF 攻击验证（攻击者无法把受害者 Strava 绑到攻击者账号，只能绑到自己）
"""

from unittest.mock import MagicMock

import pytest

from app.strava.service import (
    InvalidStateError,
    build_authorize_url,
    verify_state_and_consume,
)


def test_build_authorize_url_contains_nonce():
    """URL 应含 state 参数，Redis 应以 "strava_state:{nonce}" 为 key 存入 user_id。"""
    redis = MagicMock()
    url = build_authorize_url(user_id=42, redis=redis)

    # URL 应包含 state 参数
    assert "state=" in url
    # Redis setex 应被调用一次
    redis.setex.assert_called_once()
    call_args = redis.setex.call_args
    assert call_args[0][0].startswith("strava_state:")
    assert call_args[0][1] == 600
    assert call_args[0][2] == "42"


def test_build_authorize_url_requests_read_all_scope():
    """task-hotfix-2026-05-11 / CLAUDE.md 陷阱清单 #20 回归。

    authorize URL 必须申请 `activity:read_all` scope（不是 `activity:read`），
    否则用户的私密活动（visibility=Only You）永远拉不到。
    """
    redis = MagicMock()
    url = build_authorize_url(user_id=42, redis=redis)

    # scope 参数必须包含 activity:read_all（防止反向改回 activity:read）
    assert "scope=read,activity:read_all" in url, (
        f"authorize URL 缺少 activity:read_all scope; url={url}"
    )
    # 显式断言不含弱 scope（防止半残升级）
    assert "scope=read,activity:read&" not in url
    assert "scope=read,activity:read " not in url


def test_verify_state_happy_path():
    """state 存在时返回对应 user_id。"""
    redis = MagicMock()
    redis.getdel.return_value = b"42"

    user_id = verify_state_and_consume("valid_nonce", redis)
    assert user_id == 42
    redis.getdel.assert_called_once_with("strava_state:valid_nonce")


def test_verify_state_not_found_raises():
    """state 不存在（过期 / 伪造）应抛 InvalidStateError。"""
    redis = MagicMock()
    redis.getdel.return_value = None

    with pytest.raises(InvalidStateError) as exc_info:
        verify_state_and_consume("missing_nonce", redis)
    assert "已使用" in str(exc_info.value) or "过期" in str(exc_info.value)


def test_verify_state_replay_attack():
    """重放攻击：同一个 state 第二次用必失败（GETDEL 原子删除）。"""
    redis = MagicMock()
    # 第一次 getdel 返回 user_id，第二次返回 None（getdel 原子删除）
    redis.getdel.side_effect = [b"42", None]

    # 第一次成功
    assert verify_state_and_consume("nonce1", redis) == 42
    # 第二次失败
    with pytest.raises(InvalidStateError):
        verify_state_and_consume("nonce1", redis)


def test_csrf_attack_fails():
    """
    CSRF 攻击概念验证。

    场景：攻击者 A（user_id=100）先调 /authorize 获得 state_A。
    攻击者诱骗受害者 V（user_id=200）点含 state_A 的链接完成 Strava 授权。
    Strava 回调带 state_A 给后端——后端从 state_A 查到 user_id=100（攻击者自己），
    绑定的 token 会被写到攻击者 A 的账号下，不是受害者 V。
    因此：受害者 V 的 VELO 账号保持未绑定，数据不被泄漏。
    """
    redis = MagicMock()
    # 攻击者 A 调 authorize，Redis 存 {state_A: 100}
    url = build_authorize_url(100, redis)
    state_A = url.split("state=")[1]

    # Strava 回调带 state_A 给后端
    redis.getdel.return_value = b"100"
    resolved_user_id = verify_state_and_consume(state_A, redis)

    # 关键：resolved_user_id 是攻击者 A 的 ID，不是受害者 V 的
    assert resolved_user_id == 100  # 绑到攻击者自己账号，受害者未受影响
