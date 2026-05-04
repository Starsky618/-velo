# 任务 3.A.4：5.D.3 批量管理 endpoint

## 🎯 目标

`app/admin/router.py` 追加 segments 批量管理 2 endpoint：
- `GET /api/admin/segments` admin 视角列表（含 draft_status 等内部字段）
- `PATCH /api/admin/segments/{id}` 修改 segment 部分字段（name / description / city / difficulty）

## ⛓ 前置依赖

task-3.A.3（admin 框架已建 + AI 草稿编辑路径已闭环）。

## 📤 输出契约

| 接口 | 用途 |
|---|---|
| GET /api/admin/segments | admin 比 GET /api/segments 多内部字段（draft_status / pool_status） |
| PATCH /api/admin/segments/{id} | 修部分字段（name / description / city / difficulty 4 字段，其他不允许 admin 改） |

## 🛠 完整代码

抄 spec §4.3（行 2399-2420）。

```python
# app/admin/router.py 追加
@router.get("/segments", response_model=schemas.AdminSegmentListResponse)
def list_segments_admin(
    city: str | None = Query(None, regex="^(beijing|...|unknown)$"),
    difficulty: str | None = Query(None, regex="^(easy|medium|hard|extreme)$"),
    has_draft: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return admin_service.list_segments_admin(db, city, difficulty, has_draft, page, page_size)


@router.patch("/segments/{segment_id}", response_model=schemas.SegmentResponse)
def update_segment_admin(
    segment_id: int,
    body: schemas.AdminSegmentPatchRequest,  # name? / description? / city? / difficulty?
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, "赛段不存在")
    
    if body.name is not None:
        seg.name = body.name
    if body.description is not None:
        seg.description = body.description
    if body.city is not None:
        seg.city = body.city
    if body.difficulty is not None:
        seg.difficulty = body.difficulty
    
    db.commit()
    db.refresh(seg)
    return seg
```

### `app/admin/service.py` 追加

```python
def list_segments_admin(db: Session, city, difficulty, has_draft, page, page_size) -> dict:
    query = db.query(Segment).outerjoin(
        SegmentAiDraft, SegmentAiDraft.segment_id == Segment.id
    )
    if city:
        query = query.filter(Segment.city == city)
    if difficulty:
        query = query.filter(Segment.difficulty == difficulty)
    if has_draft is True:
        query = query.filter(SegmentAiDraft.id.isnot(None))
    elif has_draft is False:
        query = query.filter(SegmentAiDraft.id.is_(None))
    
    total = query.count()
    items = (
        query.order_by(Segment.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": items, "total": total}
```

## ✅ 测试

```python
def test_list_segments_admin_filter_by_has_draft():
def test_list_segments_admin_includes_draft_status():
def test_patch_segment_admin_only_4_fields():
    # 尝试改 name/description/city/difficulty 之外字段 → 422 schema 拒绝
def test_patch_segment_admin_invalid_city_422():
def test_patch_segment_admin_not_exist_404():
def test_patch_segment_admin_normal_user_403():
```

## 📝 commit

```
feat(admin): 任务 3.A.4 批量管理 endpoint (5.D.3)

- GET /api/admin/segments（admin 视角 + has_draft filter + draft_status 字段）
- PATCH /api/admin/segments/{id}（仅 name/description/city/difficulty 4 字段）
- service.list_segments_admin
```

## 🔍 自检三问

1. **字段白名单**：PATCH body 只允许 4 字段，schema 显式声明（不用 dict 直接 setattr）—— 防 admin 误改 reference_line / distance 等核心字段。  
   → 是。AdminSegmentPatchRequest 只声明 4 optional 字段，并用 `extra="forbid"` 让多余键直接 422，避免管理员以为 distance/reference_line 等核心字段已被修改。

2. **OUTER JOIN drafts 有重复行风险吗**：list segments outerjoin segment_ai_drafts—— 如果同 segment 有多个 drafts 行（理论上 segment_id UNIQUE 保证不会）。  
   → segment_ai_drafts.segment_id 是 UNIQUE FK（spec §2.2.3），不会有重复。

3. **改 city / difficulty 会影响下游缓存**：改 segment.city → user.heatmap 缓存是否需要失效？  
   → v5 接受短期不一致（缓存 1h TTL 自动 expire）。未来 v6 可加 admin 改 segment 后批量失效相关 user 缓存。
