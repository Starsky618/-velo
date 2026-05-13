# 任务 3.A.3：5.D.2 AI 草稿审核 endpoint

## 🎯 目标

`app/admin/router.py` 追加 3 个 AI 草稿审核 endpoint：
- `POST /api/admin/ai/segment-drafts/{segment_id}/generate` 触发 AI 生成（202 enqueue）
- `GET /api/admin/ai/segment-drafts` 列出草稿（status filter）
- `PATCH /api/admin/ai/segment-drafts/{draft_id}` 编辑 / 改状态（approved 时同步 segments.description）

## ⛓ 前置依赖

- task-3.A.2（admin 框架 + curation-pool 已有）
- task-1.B.1（agent 模块 + ai_drafts_queue 已 expose）

## 🔗 前置契约

`segment_ai_drafts` 与 `segment_curation_pool` **不强一致**：任意 segment 都可能通过 `POST .../generate` 手动生成草稿，也可能通过 `PATCH curation-pool` 勾选自动生成草稿。list endpoint 不假设草稿一定来自已选候选池，也不要求两张表同步。

## 📤 输出契约

| 接口 | 用途 |
|---|---|
| POST .../generate | 202 + enqueue（不同步等 AI） |
| GET .../segment-drafts | 列表 + status filter（pending/human_edited/approved/rejected） |
| PATCH .../{draft_id} | 编辑 human_edited_text / 改 status；approved 时同步 segments.description |

## 🛠 完整代码

抄 spec §4.3（行 2342-2378），含 endpoint 三处 + service 编排。

```python
# app/admin/router.py 追加
@router.post("/ai/segment-drafts/{segment_id}/generate", status_code=202)
def generate_ai_draft(
    segment_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # 预校验 segment 存在（避免 enqueue 后到 worker 才发现）
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, "赛段不存在")
    
    # 第二轮双审 C10 修复：202 + enqueue（不同步等 Anthropic）
    job = ai_drafts_queue.enqueue(
        'app.agent.tasks.generate_segment_draft_task',
        segment_id,
        job_timeout=120,
        retry={'max': 2, 'interval': [30, 90]},
    )
    return {"job_id": job.id, "segment_id": segment_id, "status": "enqueued"}


@router.get("/ai/segment-drafts", response_model=schemas.AiDraftListResponse)
def list_ai_drafts(
    status: str = Query("pending", regex="^(pending|human_edited|approved|rejected)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return admin_service.list_ai_drafts(db, status, page, page_size)


@router.patch("/ai/segment-drafts/{draft_id}", response_model=schemas.AiDraftResponse)
def update_ai_draft(
    draft_id: int,
    body: schemas.AiDraftPatchRequest,  # human_edited_text? / status?
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return admin_service.update_ai_draft(db, draft_id, body, admin.id)
```

### `app/admin/service.py` 追加

```python
from app.segment.models import Segment, SegmentAiDraft


def list_ai_drafts(db: Session, status: str, page: int, page_size: int) -> dict:
    query = (
        db.query(SegmentAiDraft, Segment.name.label('segment_name'))
        .join(Segment, SegmentAiDraft.segment_id == Segment.id)
        .filter(SegmentAiDraft.status == status)
    )
    total = query.count()
    items = (
        query.order_by(SegmentAiDraft.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": items, "total": total}


def update_ai_draft(db: Session, draft_id: int, body, admin_id: int) -> SegmentAiDraft:
    draft = db.get(SegmentAiDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "草稿不存在")
    
    # 状态机校验
    if body.status:
        valid_statuses = {'pending', 'human_edited', 'approved', 'rejected'}
        if body.status not in valid_statuses:
            raise HTTPException(422, f"非法状态 {body.status}")
        draft.status = body.status
    
    if body.human_edited_text is not None:
        draft.human_edited_text = body.human_edited_text
        draft.editor_user_id = admin_id
    
    # status='approved' 同步 segments.description（一致性约束）
    if body.status == 'approved' and draft.human_edited_text:
        seg = db.get(Segment, draft.segment_id)
        if seg:
            seg.description = draft.human_edited_text
    
    db.commit()
    db.refresh(draft)
    return draft
```

## ✅ 测试

```python
def test_post_generate_202_enqueues(mock_queue):
def test_post_generate_segment_not_exist_404():
def test_list_ai_drafts_filter_by_status():
def test_patch_ai_draft_human_edited_text():
def test_patch_ai_draft_approved_syncs_segment_description():
def test_patch_ai_draft_rejected_no_sync():
def test_patch_ai_draft_invalid_status_422():
def test_patch_ai_draft_not_exist_404():
```

## 📝 commit

```
feat(admin): 任务 3.A.3 AI 草稿审核 endpoint (5.D.2)

- POST .../generate（202 + enqueue ai_drafts_queue，不同步等 Anthropic）
- GET .../segment-drafts（filter by status + 分页）
- PATCH .../{draft_id}（human_edited_text / status; approved 同步 segments.description）

状态机：pending → human_edited → approved/rejected
```

## 🔍 自检三问

1. **同步 description 一致性**：approved 时 `seg.description = draft.human_edited_text` 在同事务内 commit——不会出现 draft approved 但 description 没同步的中间态？  
   → 是。同 db.commit() 原子。spec §6.1 风险表已列"approved 同步失败 → status 保 approved + 异步重试"作 fallback。

2. **enqueue 用单例**：`ai_drafts_queue` 是 task-0.8 expose 的（不就地构造）。R3-I4 已规范。  
   → 是。

3. **状态机后退**：approved 后再改回 pending 应该允许吗？  
   → spec §6.5 已拍："approved draft 后改 segments.description → 重新走 pending → human_edited → approved 流转"。本 endpoint 允许任何 status 切换，service 层不阻止；admin 通过 H5 UI 谨慎操作。
