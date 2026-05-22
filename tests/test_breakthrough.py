"""Sprint 9 task-8：FTP Breakthrough 自动检测 + 状态机 单元测试。

测试覆盖（最少 5 case）：
  1. 触发：新 eFTP > ftp × 1.05 → 写 pending event
  2. 阈下：新 eFTP ≤ ftp × 1.05 → 不写 event
  3. 用户无 ftp：跳过 / 不写 event
  4. 防抖：已有 pending → 老 pending 标 expired / 新 pending 替换
  5. estimator 异常：try/except 兜底 / 返 None / 不抛出
  6. endpoint：GET 自动过期 expires_at < now 的 pending
  7. endpoint：PATCH accepted → 同事务改 user.ftp
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.activity.breakthrough_detector import (
    BREAKTHROUGH_THRESHOLD,
    detect_breakthrough,
)
from app.activity.ftp_estimator import EstimationResult
from app.activity.models import BreakthroughEvent
from app.user.models import User


# ==================== 共享 fixture ====================


@pytest.fixture()
def user_with_ftp_220(db):
    """已填 ftp=220W 的用户 / 大多数 breakthrough 测试用这个基准。"""
    user = User(openid="bt_user_220", ftp=220)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user_no_ftp(db):
    """没填 ftp 的用户 / 应跳过检测 / 不能比突破"""
    user = User(openid="bt_user_no_ftp", ftp=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class _StubActivity:
    """轻量 stub / 不走 _activities_table 简化表 / 只给 detector 用 .id."""
    def __init__(self, activity_id: int):
        self.id = activity_id


@pytest.fixture()
def activity_high():
    """模拟一条触发突破的活动 / detector 只读 .id."""
    return _StubActivity(101)


@pytest.fixture()
def activity_low():
    """模拟一条不触发突破的活动 / detector 只读 .id."""
    return _StubActivity(102)


@pytest.fixture()
def activity_2():
    """第二条活动 / 用于防抖测试（确认老 pending 被覆盖）"""
    return _StubActivity(103)


# ==================== 检测器单元测试 ====================


class TestBreakthroughDetector:
    """检测器核心逻辑：阈值 / 防抖 / 兜底。"""

    def test_detect_writes_pending_event(self, db, user_with_ftp_220, activity_high):
        """case 1：新 eFTP=240 > 220 × 1.05=231 → 写 pending event。"""
        with patch(
            "app.activity.breakthrough_detector.estimate_ftp_for_user"
        ) as mock_est:
            mock_est.return_value = EstimationResult(
                ftp=240, confidence="high", method="cp3_no_hr", r2=0.97
            )
            event = detect_breakthrough(db, user_with_ftp_220, activity_high)

        assert event is not None
        assert event.status == "pending"
        assert event.old_ftp == 220
        assert event.suggested_ftp == 240
        assert event.user_id == user_with_ftp_220.id
        assert event.activity_id == activity_high.id
        # expires_at = detected_at + 7 days / 防漏写
        assert event.expires_at is not None

    def test_below_threshold_no_event(self, db, user_with_ftp_220, activity_low):
        """case 2：新 eFTP=225 ≤ 220 × 1.05=231 → 不写 event。"""
        with patch(
            "app.activity.breakthrough_detector.estimate_ftp_for_user"
        ) as mock_est:
            mock_est.return_value = EstimationResult(
                ftp=225, confidence="high", method="cp3_no_hr", r2=0.95
            )
            event = detect_breakthrough(db, user_with_ftp_220, activity_low)

        assert event is None
        # DB 中也不应有任何 pending 行
        count = db.query(BreakthroughEvent).filter_by(
            user_id=user_with_ftp_220.id, status="pending"
        ).count()
        assert count == 0

    def test_breakthrough_threshold_uses_raw_ftp_not_plus_5_bias(
        self, db, user_with_ftp_220, activity_low
    ):
        """case 2b：suggested 过阈值但 raw 未过阈值 → 不误报突破。"""
        with patch(
            "app.activity.breakthrough_detector.estimate_ftp_for_user"
        ) as mock_est:
            mock_est.return_value = EstimationResult(
                ftp=234,
                confidence="low",
                method="p20_hr_gated_cp3_check",
                r2=0.0,
                raw_ftp=229.0,
            )
            event = detect_breakthrough(db, user_with_ftp_220, activity_low)

        assert event is None

    def test_user_no_ftp_skip(self, db, user_no_ftp, activity_high):
        """case 3：用户 user.ftp=None → 跳过 / 不调 estimator / 返 None。"""
        with patch(
            "app.activity.breakthrough_detector.estimate_ftp_for_user"
        ) as mock_est:
            event = detect_breakthrough(db, user_no_ftp, activity_high)

        assert event is None
        # 守卫前置 / estimator 不应被调用（省 scipy 开销）
        mock_est.assert_not_called()

    def test_debounce_pending_overwritten(
        self, db, user_with_ftp_220, activity_high, activity_2
    ):
        """case 4：防抖 / 第二次检测把老 pending 标 expired / 用最新覆盖。"""
        with patch(
            "app.activity.breakthrough_detector.estimate_ftp_for_user"
        ) as mock_est:
            mock_est.return_value = EstimationResult(
                ftp=240, confidence="high", method="cp3_no_hr", r2=0.97
            )
            # 第 1 次：写 pending event activity_id=101
            detect_breakthrough(db, user_with_ftp_220, activity_high)
            # 第 2 次：用 activity_id=103 / 老的应被标 expired
            detect_breakthrough(db, user_with_ftp_220, activity_2)

        pending = (
            db.query(BreakthroughEvent)
            .filter_by(user_id=user_with_ftp_220.id, status="pending")
            .all()
        )
        # 只剩 1 条 pending
        assert len(pending) == 1
        # 留下的是最新那条
        assert pending[0].activity_id == activity_2.id

        # 老的转成 expired
        expired = (
            db.query(BreakthroughEvent)
            .filter_by(user_id=user_with_ftp_220.id, status="expired")
            .all()
        )
        assert len(expired) == 1
        assert expired[0].activity_id == activity_high.id

    def test_estimator_fail_silent(self, db, user_with_ftp_220, activity_high):
        """case 5：estimator 抛异常 → try/except 兜底 / 返 None / 不抛。"""
        with patch(
            "app.activity.breakthrough_detector.estimate_ftp_for_user"
        ) as mock_est:
            mock_est.side_effect = RuntimeError("scipy curve_fit fail")
            # 不 raise 异常 / 平静返 None
            event = detect_breakthrough(db, user_with_ftp_220, activity_high)

        assert event is None
        # DB 中无任何记录
        count = db.query(BreakthroughEvent).filter_by(
            user_id=user_with_ftp_220.id
        ).count()
        assert count == 0

    def test_estimator_returns_insufficient(
        self, db, user_with_ftp_220, activity_high
    ):
        """case 6（额外）：estimator 返 ftp=None / 数据不足 → 不写 event。"""
        with patch(
            "app.activity.breakthrough_detector.estimate_ftp_for_user"
        ) as mock_est:
            mock_est.return_value = EstimationResult(
                ftp=None, confidence="insufficient", method="cp3_no_hr", r2=0.0
            )
            event = detect_breakthrough(db, user_with_ftp_220, activity_high)

        assert event is None


# ==================== endpoint 测试 ====================


class TestBreakthroughEndpoints:
    """GET / PATCH endpoint 的状态机 + 权限。"""

    def test_list_returns_pending_only(
        self, client, db, user_with_ftp_220, auth_header_220, activity_high
    ):
        """GET 只返 pending / 不返 accepted/rejected/expired。"""
        # 直接写 3 条不同状态的 event
        now = datetime.now(timezone.utc)
        for status_val, aid in [
            ("pending", 200),
            ("accepted", 201),
            ("rejected", 202),
            ("expired", 203),
        ]:
            db.add(BreakthroughEvent(
                user_id=user_with_ftp_220.id,
                activity_id=aid,
                old_ftp=220,
                suggested_ftp=240,
                status=status_val,
                expires_at=now + timedelta(days=7),
            ))
        db.commit()

        resp = client.get("/api/user/me/breakthroughs", headers=auth_header_220)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["status"] == "pending"
        assert body[0]["suggested_ftp"] == 240

    def test_list_auto_expires_old_pending(
        self, client, db, user_with_ftp_220, auth_header_220
    ):
        """expires_at < now 的 pending → GET 时自动转 expired。"""
        now = datetime.now(timezone.utc)
        db.add(BreakthroughEvent(
            user_id=user_with_ftp_220.id,
            activity_id=300,
            old_ftp=220,
            suggested_ftp=240,
            status="pending",
            expires_at=now - timedelta(days=1),  # 1 天前过期
        ))
        db.commit()

        resp = client.get("/api/user/me/breakthroughs", headers=auth_header_220)
        assert resp.status_code == 200
        # 已过期 → list 应为空
        assert resp.json() == []

        # DB 中状态应已变 expired
        db.expire_all()  # 刷新 ORM 缓存
        event = db.query(BreakthroughEvent).filter_by(activity_id=300).first()
        assert event.status == "expired"

    def test_patch_accepted_updates_user_ftp(
        self, client, db, user_with_ftp_220, auth_header_220
    ):
        """PATCH accepted → 同事务改 user.ftp = suggested_ftp。"""
        now = datetime.now(timezone.utc)
        event = BreakthroughEvent(
            user_id=user_with_ftp_220.id,
            activity_id=400,
            old_ftp=220,
            suggested_ftp=245,
            status="pending",
            expires_at=now + timedelta(days=7),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        resp = client.patch(
            f"/api/user/me/breakthroughs/{event.id}",
            json={"status": "accepted"},
            headers=auth_header_220,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

        # 验证 user.ftp 被更新
        db.expire_all()
        user = db.query(User).filter_by(id=user_with_ftp_220.id).first()
        assert user.ftp == 245

    def test_patch_rejected_does_not_change_ftp(
        self, client, db, user_with_ftp_220, auth_header_220
    ):
        """PATCH rejected → 只改状态 / 不动 user.ftp。"""
        now = datetime.now(timezone.utc)
        event = BreakthroughEvent(
            user_id=user_with_ftp_220.id,
            activity_id=500,
            old_ftp=220,
            suggested_ftp=245,
            status="pending",
            expires_at=now + timedelta(days=7),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        resp = client.patch(
            f"/api/user/me/breakthroughs/{event.id}",
            json={"status": "rejected"},
            headers=auth_header_220,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        db.expire_all()
        user = db.query(User).filter_by(id=user_with_ftp_220.id).first()
        # user.ftp 保持 220 不变
        assert user.ftp == 220

    def test_patch_non_pending_returns_400(
        self, client, db, user_with_ftp_220, auth_header_220
    ):
        """PATCH 已处理事件（非 pending）→ 400 防双击。"""
        now = datetime.now(timezone.utc)
        event = BreakthroughEvent(
            user_id=user_with_ftp_220.id,
            activity_id=600,
            old_ftp=220,
            suggested_ftp=245,
            status="accepted",  # 已是 accepted
            expires_at=now + timedelta(days=7),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        resp = client.patch(
            f"/api/user/me/breakthroughs/{event.id}",
            json={"status": "accepted"},
            headers=auth_header_220,
        )
        assert resp.status_code == 400

    def test_patch_invalid_status_422(
        self, client, db, user_with_ftp_220, auth_header_220
    ):
        """PATCH 非法 status（如 'pending'）→ 422 Literal 拦截。"""
        now = datetime.now(timezone.utc)
        event = BreakthroughEvent(
            user_id=user_with_ftp_220.id,
            activity_id=700,
            old_ftp=220,
            suggested_ftp=245,
            status="pending",
            expires_at=now + timedelta(days=7),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        # 'pending' 不在 Literal['accepted', 'rejected'] 内
        resp = client.patch(
            f"/api/user/me/breakthroughs/{event.id}",
            json={"status": "pending"},
            headers=auth_header_220,
        )
        assert resp.status_code == 422

    def test_patch_other_user_event_404(
        self, client, db, user_with_ftp_220, auth_header_220
    ):
        """权限：用户不能改别人的事件 → 404（filter by user_id 隔离）。"""
        # 创建另一个用户的 event
        other_user = User(openid="bt_other", ftp=200)
        db.add(other_user)
        db.commit()
        db.refresh(other_user)

        now = datetime.now(timezone.utc)
        event = BreakthroughEvent(
            user_id=other_user.id,
            activity_id=800,
            old_ftp=200,
            suggested_ftp=220,
            status="pending",
            expires_at=now + timedelta(days=7),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        # 用 user_with_ftp_220 的 token 去改 other_user 的 event → 404
        resp = client.patch(
            f"/api/user/me/breakthroughs/{event.id}",
            json={"status": "accepted"},
            headers=auth_header_220,
        )
        assert resp.status_code == 404


# ==================== 共享 endpoint fixture ====================


@pytest.fixture()
def auth_header_220(user_with_ftp_220):
    """user_with_ftp_220 的 JWT header / endpoint 测试用。"""
    from app.user.service import create_token

    token = create_token(user_with_ftp_220.id)
    return {"Authorization": f"Bearer {token}"}
