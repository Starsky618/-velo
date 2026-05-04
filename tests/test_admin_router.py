"""admin router 骨架测试。"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.segment.models import Segment, SegmentCurationPool


@pytest.fixture()
def segment_for_delete(db):
    """创建一个可删除的测试赛段。"""
    segment = Segment(
        name="待删除赛段",
        description="admin router delete test",
        distance=1200.0,
        elevation_gain=80.0,
        elevation_loss=20.0,
        avg_gradient=6.6,
        elevation_profile="[100, 180]",
        start_lat=37.87,
        start_lon=112.55,
        end_lat=37.88,
        end_lon=112.56,
        reference_line="SRID=4326;LINESTRING(112.55 37.87, 112.56 37.88)",
        match_tolerance=50.0,
        min_match_ratio=0.8,
        difficulty="medium",
        max_gradient=8.0,
        city="taiyuan",
        created_at=datetime.now(timezone.utc),
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _make_segment(db, name, *, city="taiyuan", difficulty="medium", distance=1200.0):
    """创建候选池测试用赛段。"""
    segment = Segment(
        name=name,
        description=f"{name} description",
        distance=distance,
        elevation_gain=80.0,
        elevation_loss=20.0,
        avg_gradient=6.6,
        elevation_profile="[100, 180]",
        start_lat=37.87,
        start_lon=112.55,
        end_lat=37.88,
        end_lon=112.56,
        reference_line="SRID=4326;LINESTRING(112.55 37.87, 112.56 37.88)",
        match_tolerance=50.0,
        min_match_ratio=0.8,
        difficulty=difficulty,
        max_gradient=8.0,
        city=city,
        created_at=datetime.now(timezone.utc),
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


@pytest.fixture()
def curation_pool_items(db, admin_user):
    """创建 3 条候选池数据，覆盖列表、筛选、已选计数。"""
    taiyuan = _make_segment(db, "太原爬坡", city="taiyuan", difficulty="hard", distance=1800.0)
    beijing = _make_segment(db, "北京绕圈", city="beijing", difficulty="easy", distance=900.0)
    shanghai = _make_segment(db, "上海平路", city="shanghai", difficulty="medium", distance=1500.0)

    items = [
        SegmentCurationPool(
            segment_id=taiyuan.id,
            pool_score=98.5,
            pool_reason="high_attempts",
            selected_for_v5=False,
        ),
        SegmentCurationPool(
            segment_id=beijing.id,
            pool_score=75.0,
            pool_reason="difficulty_balance",
            selected_for_v5=True,
            selected_by_user_id=admin_user.id,
            selected_at=datetime.now(timezone.utc),
        ),
        SegmentCurationPool(
            segment_id=shanghai.id,
            pool_score=60.0,
            pool_reason="manual_added",
            selected_for_v5=False,
        ),
    ]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return items


def test_delete_segment_admin_only(client, auth_header, admin_header, segment_for_delete):
    """admin 新路径只允许管理员删除赛段，普通用户应被 403 拦下。"""
    res = client.delete(
        f"/api/admin/segments/{segment_for_delete.id}",
        headers=auth_header,
    )
    assert res.status_code == 403

    res = client.delete(
        f"/api/admin/segments/{segment_for_delete.id}",
        headers=admin_header,
    )
    assert res.status_code == 204


def test_delete_segment_admin_requires_auth(client, segment_for_delete):
    """没带 JWT 就像没出示门禁卡，请求应在身份层返回 401。"""
    res = client.delete(f"/api/admin/segments/{segment_for_delete.id}")

    assert res.status_code == 401


def test_delete_segment_admin_returns_404_for_missing_segment(client, admin_header):
    """管理员删除不存在的赛段时，应沿用 service 语义返回 404。"""
    res = client.delete("/api/admin/segments/999999", headers=admin_header)

    assert res.status_code == 404


def test_delete_segment_legacy_path_still_works(client, admin_header, segment_for_delete):
    """旧 DELETE /api/segments/{id} 保留兼容，管理员仍可删除。"""
    res = client.delete(
        f"/api/segments/{segment_for_delete.id}",
        headers=admin_header,
    )

    assert res.status_code == 204


def test_delete_segment_legacy_path_rejects_normal_user_403(
    client,
    auth_header,
    segment_for_delete,
):
    """旧路径虽然兼容，但普通用户仍应被 service 权限兜底拦下。"""
    res = client.delete(
        f"/api/segments/{segment_for_delete.id}",
        headers=auth_header,
    )

    assert res.status_code == 403


def test_list_curation_pool_admin_only(client, auth_header, admin_header, curation_pool_items):
    """候选池列表是后台清单，普通用户不能看，管理员能看到分页结果。"""
    res = client.get("/api/admin/curation-pool", headers=auth_header)
    assert res.status_code == 403

    res = client.get("/api/admin/curation-pool", headers=admin_header)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert data["selected_count"] == 1
    assert [item["segment_name"] for item in data["items"]] == [
        "太原爬坡",
        "北京绕圈",
        "上海平路",
    ]
    assert data["items"][0]["segment_city"] == "taiyuan"
    assert data["items"][0]["segment_difficulty"] == "hard"


def test_list_curation_pool_requires_auth(client):
    """匿名用户没有登录身份，应在 admin 依赖前被 401 拦下。"""
    res = client.get("/api/admin/curation-pool")

    assert res.status_code == 401


def test_list_curation_pool_filter_by_city(client, admin_header, curation_pool_items):
    """city 筛选应按关联 segment.city 过滤，不按候选池自身字段臆测。"""
    res = client.get(
        "/api/admin/curation-pool?city=beijing",
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["segment_name"] == "北京绕圈"
    assert data["items"][0]["segment_city"] == "beijing"


def test_list_curation_pool_filter_by_selected_and_difficulty(
    client,
    admin_header,
    curation_pool_items,
):
    """selected 是 bool 筛网，False 不能被 truthiness 写法漏掉。"""
    res = client.get(
        "/api/admin/curation-pool?selected=false&difficulty=hard",
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["segment_name"] == "太原爬坡"
    assert data["items"][0]["selected_for_v5"] is False
    assert data["items"][0]["segment_difficulty"] == "hard"


def test_update_pool_select_enqueues_ai_task(client, admin_header, curation_pool_items, monkeypatch):
    """false → true 像第一次打勾，应派发一次 AI 草稿生成任务。"""
    fake_queue = MagicMock()
    monkeypatch.setattr("app.admin.service.ai_drafts_queue", fake_queue)
    pool = curation_pool_items[0]

    res = client.patch(
        f"/api/admin/curation-pool/{pool.id}",
        json={"selected_for_v5": True},
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["selected_for_v5"] is True
    assert data["selected_by_user_id"] is not None
    assert data["selected_at"] is not None
    fake_queue.enqueue.assert_called_once_with(
        "app.agent.tasks.generate_segment_draft_task",
        pool.segment_id,
        job_timeout=120,
        retry={"max": 2, "interval": [30, 90]},
    )


def test_update_pool_select_idempotent_no_double_enqueue(
    client,
    admin_header,
    curation_pool_items,
    monkeypatch,
):
    """true → true 只是重复确认，不应重复派发 AI 任务。"""
    fake_queue = MagicMock()
    monkeypatch.setattr("app.admin.service.ai_drafts_queue", fake_queue)
    already_selected = curation_pool_items[1]

    res = client.patch(
        f"/api/admin/curation-pool/{already_selected.id}",
        json={"selected_for_v5": True},
        headers=admin_header,
    )

    assert res.status_code == 200
    assert res.json()["selected_for_v5"] is True
    fake_queue.enqueue.assert_not_called()


def test_update_pool_unselect_no_enqueue(client, admin_header, curation_pool_items, monkeypatch):
    """true → false 是取消勾选，只改候选池状态，不派发 AI 草稿任务。"""
    fake_queue = MagicMock()
    monkeypatch.setattr("app.admin.service.ai_drafts_queue", fake_queue)
    already_selected = curation_pool_items[1]

    res = client.patch(
        f"/api/admin/curation-pool/{already_selected.id}",
        json={"selected_for_v5": False},
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["selected_for_v5"] is False
    fake_queue.enqueue.assert_not_called()


def test_update_pool_enqueue_failure_rolls_back_selection(
    client,
    db,
    admin_header,
    curation_pool_items,
    monkeypatch,
):
    """enqueue 失败时要补偿恢复未选中，避免 selected=true 但没 task 的死局。"""
    fake_queue = MagicMock()
    fake_queue.enqueue.side_effect = RuntimeError("redis down")
    monkeypatch.setattr("app.admin.service.ai_drafts_queue", fake_queue)
    pool = curation_pool_items[0]

    res = client.patch(
        f"/api/admin/curation-pool/{pool.id}",
        json={"selected_for_v5": True},
        headers=admin_header,
    )

    assert res.status_code == 503
    assert res.json()["detail"] == "AI 草稿任务派发失败，请稍后重试"
    db.expire_all()
    reloaded = db.get(SegmentCurationPool, pool.id)
    assert reloaded.selected_for_v5 is False
    assert reloaded.selected_by_user_id is None
    assert reloaded.selected_at is None


def test_update_pool_50_limit_400(client, db, admin_header, admin_user):
    """已选 50 条时，再从未选切 true 应返回 400，避免精选池失控膨胀。"""
    for idx in range(51):
        segment = _make_segment(
            db,
            f"候选赛段 {idx}",
            city="taiyuan",
            difficulty="medium",
            distance=1000.0 + idx,
        )
        db.add(
            SegmentCurationPool(
                segment_id=segment.id,
                pool_score=100.0 - idx,
                pool_reason="high_attempts",
                selected_for_v5=idx < 50,
                selected_by_user_id=admin_user.id if idx < 50 else None,
            )
        )
    db.commit()
    unselected = (
        db.query(SegmentCurationPool)
        .filter(SegmentCurationPool.selected_for_v5.is_(False))
        .first()
    )

    res = client.patch(
        f"/api/admin/curation-pool/{unselected.id}",
        json={"selected_for_v5": True},
        headers=admin_header,
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "候选池已达 50 上限，请先取消勾选其他项"


def test_update_pool_pool_not_exist_404(client, admin_header):
    """不存在的候选池 id 应返回 404，而不是让 ORM None 继续走下去。"""
    res = client.patch(
        "/api/admin/curation-pool/999999",
        json={"selected_for_v5": True},
        headers=admin_header,
    )

    assert res.status_code == 404
