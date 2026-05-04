"""admin router 骨架测试。"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.segment.models import Segment, SegmentAiDraft, SegmentCurationPool


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


@pytest.fixture()
def ai_drafts(db, admin_user):
    """创建 AI 草稿审核台测试数据，覆盖 pending / approved 两种列表状态。"""
    pending_segment = _make_segment(db, "AI 草稿待审核", city="taiyuan")
    approved_segment = _make_segment(db, "AI 草稿已通过", city="beijing")
    now = datetime.now(timezone.utc)
    drafts = [
        SegmentAiDraft(
            segment_id=pending_segment.id,
            ai_draft_text="AI 第一稿：太原爬坡节奏鲜明。",
            status="pending",
            created_at=now,
            updated_at=now,
        ),
        SegmentAiDraft(
            segment_id=approved_segment.id,
            ai_draft_text="AI 第一稿：北京绕圈适合训练。",
            human_edited_text="人工定稿：北京绕圈适合节奏训练。",
            status="approved",
            editor_user_id=admin_user.id,
            created_at=now,
            updated_at=now,
        ),
    ]
    db.add_all(drafts)
    db.commit()
    for draft in drafts:
        db.refresh(draft)
    return drafts


def test_generate_ai_draft_admin_only_and_enqueues(
    client,
    auth_header,
    admin_header,
    curation_pool_items,
    monkeypatch,
):
    """手动生成入口只允许 admin；通过后只 enqueue，不同步等 AI 返回。"""
    fake_queue = MagicMock()
    fake_job = MagicMock(id="job-3a3")
    fake_queue.enqueue.return_value = fake_job
    monkeypatch.setattr("app.admin.service.ai_drafts_queue", fake_queue)
    segment_id = curation_pool_items[0].segment_id

    res = client.post(
        f"/api/admin/ai/segment-drafts/{segment_id}/generate",
        headers=auth_header,
    )
    assert res.status_code == 403

    res = client.post(
        f"/api/admin/ai/segment-drafts/{segment_id}/generate",
        headers=admin_header,
    )

    assert res.status_code == 202
    assert res.json() == {
        "job_id": "job-3a3",
        "segment_id": segment_id,
        "status": "enqueued",
    }
    fake_queue.enqueue.assert_called_once_with(
        "app.agent.tasks.generate_segment_draft_task",
        segment_id,
        job_timeout=120,
        retry={"max": 2, "interval": [30, 90]},
    )


def test_generate_ai_draft_missing_segment_404(client, admin_header, monkeypatch):
    """不存在的 segment 要在 enqueue 前拦下，不把坏任务丢给 worker。"""
    fake_queue = MagicMock()
    monkeypatch.setattr("app.admin.service.ai_drafts_queue", fake_queue)

    res = client.post(
        "/api/admin/ai/segment-drafts/999999/generate",
        headers=admin_header,
    )

    assert res.status_code == 404
    assert res.json()["detail"] == "赛段不存在"
    fake_queue.enqueue.assert_not_called()


def test_generate_ai_draft_queue_failure_returns_503(
    client,
    admin_header,
    curation_pool_items,
    monkeypatch,
):
    """Redis/RQ 派发失败时返回 503，避免后台看到不明 500。"""
    fake_queue = MagicMock()
    fake_queue.enqueue.side_effect = RuntimeError("redis down")
    monkeypatch.setattr("app.admin.service.ai_drafts_queue", fake_queue)
    segment_id = curation_pool_items[0].segment_id

    res = client.post(
        f"/api/admin/ai/segment-drafts/{segment_id}/generate",
        headers=admin_header,
    )

    assert res.status_code == 503
    assert res.json()["detail"] == "AI 草稿任务派发失败，请稍后重试"


def test_list_ai_drafts_filter_by_status(client, admin_header, ai_drafts):
    """草稿审核台按 status 筛选，并返回关联 segment_name 供后台展示。"""
    res = client.get(
        "/api/admin/ai/segment-drafts?status=pending",
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == ai_drafts[0].id
    assert data["items"][0]["segment_name"] == "AI 草稿待审核"
    assert data["items"][0]["ai_draft_text"] == "AI 第一稿：太原爬坡节奏鲜明。"
    assert data["items"][0]["status"] == "pending"


def test_list_ai_drafts_rejects_invalid_status(client, admin_header):
    """status 只能是 4 个状态机值，拼错应在请求层 422。"""
    res = client.get(
        "/api/admin/ai/segment-drafts?status=published",
        headers=admin_header,
    )

    assert res.status_code == 422


def test_patch_ai_draft_human_edited_text(client, admin_header, ai_drafts):
    """编辑人工稿应写入 editor_user_id，并把 pending 草稿推进到 human_edited。"""
    res = client.patch(
        f"/api/admin/ai/segment-drafts/{ai_drafts[0].id}",
        json={"human_edited_text": "人工改稿：太原爬坡适合间歇训练。"},
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["human_edited_text"] == "人工改稿：太原爬坡适合间歇训练。"
    assert data["status"] == "human_edited"
    assert data["editor_user_id"] is not None


def test_patch_approved_draft_text_reopens_review(client, db, admin_header, ai_drafts):
    """已通过草稿被再次编辑时，应退回 human_edited，等待重新 approved 后再发布。"""
    approved_draft = ai_drafts[1]

    res = client.patch(
        f"/api/admin/ai/segment-drafts/{approved_draft.id}",
        json={"human_edited_text": "二次改稿：北京绕圈加入补给提示。"},
        headers=admin_header,
    )

    assert res.status_code == 200
    assert res.json()["status"] == "human_edited"
    db.expire_all()
    segment = db.get(Segment, approved_draft.segment_id)
    assert segment.description == "AI 草稿已通过 description"


def test_patch_ai_draft_approved_syncs_segment_description(
    client,
    db,
    admin_header,
    ai_drafts,
):
    """approved 与 segments.description 必须同事务落库，避免草稿通过但前台仍旧文案。"""
    res = client.patch(
        f"/api/admin/ai/segment-drafts/{ai_drafts[0].id}",
        json={
            "human_edited_text": "人工定稿：太原爬坡适合周末挑战。",
            "status": "approved",
        },
        headers=admin_header,
    )

    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    db.expire_all()
    segment = db.get(Segment, ai_drafts[0].segment_id)
    assert segment.description == "人工定稿：太原爬坡适合周末挑战。"


def test_patch_ai_draft_rejected_no_sync(client, db, admin_header, ai_drafts):
    """rejected 是打回留档，不应该污染正式 segment.description。"""
    res = client.patch(
        f"/api/admin/ai/segment-drafts/{ai_drafts[0].id}",
        json={
            "human_edited_text": "这版暂不发布。",
            "status": "rejected",
        },
        headers=admin_header,
    )

    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    db.expire_all()
    segment = db.get(Segment, ai_drafts[0].segment_id)
    assert segment.description == "AI 草稿待审核 description"


def test_patch_ai_draft_not_exist_404(client, admin_header):
    """不存在的 draft_id 应返回 404，而不是 db.get(None) 后继续改。"""
    res = client.patch(
        "/api/admin/ai/segment-drafts/999999",
        json={"status": "rejected"},
        headers=admin_header,
    )

    assert res.status_code == 404


@pytest.fixture()
def admin_segments(db, admin_user):
    """创建批量管理测试数据：有草稿 / 无草稿 / 已入池三种组合。"""
    taiyuan = _make_segment(
        db,
        "批量太原爬坡",
        city="taiyuan",
        difficulty="hard",
        distance=1800.0,
    )
    beijing = _make_segment(
        db,
        "批量北京绕圈",
        city="beijing",
        difficulty="easy",
        distance=900.0,
    )
    shanghai = _make_segment(
        db,
        "批量上海平路",
        city="shanghai",
        difficulty="medium",
        distance=1500.0,
    )
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            SegmentAiDraft(
                segment_id=taiyuan.id,
                ai_draft_text="太原草稿",
                status="pending",
                created_at=now,
                updated_at=now,
            ),
            SegmentCurationPool(
                segment_id=taiyuan.id,
                pool_score=99.0,
                pool_reason="high_attempts",
                selected_for_v5=True,
                selected_by_user_id=admin_user.id,
                selected_at=now,
            ),
            SegmentCurationPool(
                segment_id=beijing.id,
                pool_score=75.0,
                pool_reason="difficulty_balance",
                selected_for_v5=False,
            ),
        ]
    )
    db.commit()
    return {
        "taiyuan": taiyuan,
        "beijing": beijing,
        "shanghai": shanghai,
    }


def test_list_segments_admin_only(client, auth_header, admin_header, admin_segments):
    """批量管理列表是 admin H5 内部工具，普通用户应被 403 拦下。"""
    res = client.get("/api/admin/segments", headers=auth_header)
    assert res.status_code == 403

    res = client.get("/api/admin/segments", headers=admin_header)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert {item["name"] for item in data["items"]} == {
        "批量太原爬坡",
        "批量北京绕圈",
        "批量上海平路",
    }


def test_list_segments_admin_includes_internal_statuses(
    client,
    admin_header,
    admin_segments,
):
    """admin 视角比公开列表多 draft_status / pool_status，方便后台批量筛修。"""
    res = client.get("/api/admin/segments?city=taiyuan", headers=admin_header)

    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["id"] == admin_segments["taiyuan"].id
    assert item["distance"] == 1.8
    assert item["description"] == "批量太原爬坡 description"
    assert item["draft_status"] == "pending"
    assert item["pool_status"] == "selected"


def test_list_segments_admin_filter_by_has_draft(client, admin_header, admin_segments):
    """has_draft=True 只看已有 AI 草稿的赛段，False 只看还没草稿的赛段。"""
    res = client.get("/api/admin/segments?has_draft=true", headers=admin_header)
    assert res.status_code == 200
    assert [item["name"] for item in res.json()["items"]] == ["批量太原爬坡"]

    res = client.get("/api/admin/segments?has_draft=false", headers=admin_header)
    assert res.status_code == 200
    assert {item["name"] for item in res.json()["items"]} == {
        "批量北京绕圈",
        "批量上海平路",
    }


def test_list_segments_admin_filter_by_city_and_difficulty(
    client,
    admin_header,
    admin_segments,
):
    """city / difficulty 应按 Segment 字段筛选，供 H5 后台快速定位脏元数据。"""
    res = client.get(
        "/api/admin/segments?city=beijing&difficulty=easy",
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "批量北京绕圈"
    assert data["items"][0]["pool_status"] == "candidate"


def test_patch_segment_admin_updates_only_allowed_fields(
    client,
    db,
    admin_header,
    admin_segments,
):
    """PATCH 只允许修 4 个运营字段，不能碰 reference_line / distance 等核心赛段定义。"""
    target = admin_segments["shanghai"]

    res = client.patch(
        f"/api/admin/segments/{target.id}",
        json={
            "name": "上海平路修正版",
            "description": "人工修正后的城市与难度",
            "city": "hangzhou",
            "difficulty": "hard",
        },
        headers=admin_header,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "上海平路修正版"
    assert data["description"] == "人工修正后的城市与难度"
    assert data["city"] == "hangzhou"
    assert data["difficulty"] == "hard"
    db.expire_all()
    reloaded = db.get(Segment, target.id)
    assert reloaded.distance == 1500.0
    assert reloaded.reference_line is not None


def test_patch_segment_admin_rejects_extra_field(client, admin_header, admin_segments):
    """请求体出现 4 字段之外的 key 应 422，避免静默忽略造成管理员误判。"""
    res = client.patch(
        f"/api/admin/segments/{admin_segments['taiyuan'].id}",
        json={"distance": 9999.0},
        headers=admin_header,
    )

    assert res.status_code == 422


def test_patch_segment_admin_invalid_city_422(client, admin_header, admin_segments):
    """city 只能是 spec 枚举，拼错不应写进 segments。"""
    res = client.patch(
        f"/api/admin/segments/{admin_segments['taiyuan'].id}",
        json={"city": "nanjing"},
        headers=admin_header,
    )

    assert res.status_code == 422


def test_patch_segment_admin_not_exist_404(client, admin_header):
    """不存在的 segment_id 应返回 404，不让 None 继续 setattr。"""
    res = client.patch(
        "/api/admin/segments/999999",
        json={"name": "不存在"},
        headers=admin_header,
    )

    assert res.status_code == 404
