# 任务 3.A.2：5.D.1 候选池 endpoint（GET + PATCH）

## 🎯 目标

`app/admin/router.py` 追加候选池 2 endpoint：
- `GET /api/admin/curation-pool` 列出候选池（filter selected / city / difficulty）
- `PATCH /api/admin/curation-pool/{id}` 切换 selected_for_v5（false → true 时 enqueue AI 生成 task）

## ⛓ 前置依赖

- task-3.A.1（admin 框架）
- task-3.C.1（候选池脚本生成 segment_curation_pool 数据）

## 📤 输出契约

| 接口 | 用途 |
|---|---|
| GET /api/admin/curation-pool | admin 列表查看 + 勾选 |
| PATCH /api/admin/curation-pool/{id} | 勾选 → 触发 AI 草稿生成（enqueue ai_drafts_queue） |

## 🛠 完整代码

抄 spec §4.3 GET /api/admin/curation-pool + PATCH /api/admin/curation-pool/{id}（行 2380-2410）。

```python
# app/admin/router.py 追加
from app.admin import service as admin_service
from app.segment.models import SegmentCurationPool

@router.get("/curation-pool", response_model=schemas.CurationPoolListResponse)
def list_curation_pool(
    selected: bool | None = Query(None),
    city: str | None = Query(None, regex="^(beijing|...|unknown)$"),
    difficulty: str | None = Query(None, regex="^(easy|medium|hard|extreme)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return admin_service.list_curation_pool(db, selected, city, difficulty, page, page_size)


@router.patch("/curation-pool/{pool_id}", response_model=schemas.CurationPoolItem)
def update_curation_pool(
    pool_id: int,
    body: schemas.CurationPoolPatchRequest,  # selected_for_v5: bool
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """selected false→true 时 enqueue AI 草稿生成 task。"""
    return admin_service.update_curation_pool(db, pool_id, body.selected_for_v5, admin.id)
```

### `app/admin/service.py` 追加

```python
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.segment.models import Segment, SegmentCurationPool
from app.queue import ai_drafts_queue  # task-0.8 expose 的单例


def list_curation_pool(db: Session, selected, city, difficulty, page, page_size) -> dict:
    query = db.query(SegmentCurationPool).join(
        Segment, SegmentCurationPool.segment_id == Segment.id
    )
    if selected is not None:
        query = query.filter(SegmentCurationPool.selected_for_v5 == selected)
    if city:
        query = query.filter(Segment.city == city)
    if difficulty:
        query = query.filter(Segment.difficulty == difficulty)
    
    total = query.count()
    selected_count = (
        db.query(func.count(SegmentCurationPool.id))
        .filter(SegmentCurationPool.selected_for_v5 == True)
        .scalar()
    )
    items = (
        query.order_by(SegmentCurationPool.pool_score.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": items,
        "total": total,
        "selected_count": selected_count,
    }


def update_curation_pool(db: Session, pool_id: int, selected_for_v5: bool, admin_id: int) -> SegmentCurationPool:
    """selected false→true 时 enqueue AI 草稿生成。"""
    pool = db.get(SegmentCurationPool, pool_id)
    if pool is None:
        raise HTTPException(404, "候选项不存在")
    
    # 候选池上限 50（PRD 拍）
    if selected_for_v5 and not pool.selected_for_v5:
        current_selected = (
            db.query(func.count(SegmentCurationPool.id))
            .filter(SegmentCurationPool.selected_for_v5 == True)
            .scalar()
        )
        if current_selected >= 50:
            raise HTTPException(400, "候选池已达 50 上限，请先取消勾选其他项")
    
    was_selected = pool.selected_for_v5
    pool.selected_for_v5 = selected_for_v5
    if selected_for_v5:
        pool.selected_by_user_id = admin_id
        pool.selected_at = func.now()
    db.commit()
    
    # false → true 触发 AI 草稿生成（异步）
    if selected_for_v5 and not was_selected:
        ai_drafts_queue.enqueue(
            'app.agent.tasks.generate_segment_draft_task',
            pool.segment_id,
            job_timeout=120,
            retry={'max': 2, 'interval': [30, 90]},
        )
    return pool
```

## ✅ 测试

```python
def test_list_curation_pool_admin_only(): 
def test_list_curation_pool_filter_by_city():
def test_update_pool_select_enqueues_ai_task(mock_ai_queue):
    # 关键：false → true 应触发 ai_drafts_queue.enqueue
def test_update_pool_select_idempotent_no_double_enqueue():
    # true → true 不重新 enqueue
def test_update_pool_50_limit_400():
def test_update_pool_pool_not_exist_404():
```

## 📝 commit

```
feat(admin): 任务 3.A.2 候选池 endpoint (GET + PATCH)

- GET /api/admin/curation-pool（filter selected/city/difficulty + 分页 + selected_count）
- PATCH /api/admin/curation-pool/{id}（false→true enqueue ai_drafts_queue）
- service.list_curation_pool / update_curation_pool
- 50 上限校验（PRD 拍）
```

## 🔍 自检三问

1. **enqueue 一次**：subagent 注意 `if selected_for_v5 and not was_selected` 守卫——重复 PATCH true 不会重复 enqueue。  
   → 是。

2. **50 上限**：限制是否同 admin 跨请求并发的边界条件守得住？  
   → 接受小幅超标（admin 操作低频）。需严格可加 advisory lock 类似 from-activity，但 v5 简化。

3. **enqueue 用 ai_drafts_queue 实例**（task-0.8 expose）：禁止就地 Queue('ai_drafts')。  
   → 是，第三轮 R3-I4 已规范。
