# 任务 1.A.3：segment router 扩展 + 即时反馈 endpoint

## 🎯 目标

`app/segment/router.py` 扩展现有 `GET /api/segments` + 新增 `GET /api/segments/{id}/efforts/me`：
- 列表 endpoint 加 search / city / difficulty Query 参数（保持公开访问，**不加 get_current_user**）
- 详情 endpoint 响应字段加 max_gradient / city / difficulty
- 新增即时反馈 endpoint

## ⛓ 前置依赖

task-1.A.2（service 函数实现完）。

## 📤 输出契约

| 接口 | 权限 | 说明 |
|---|---|---|
| GET /api/segments | **公开**（沿用现有匿名访问） | 加 search/city/difficulty Query |
| GET /api/segments/{id} | 沿用现有 | 响应加 3 字段 |
| GET /api/segments/{id}/efforts/me | current_user | 即时反馈 6 字段 + 404 segment 不存在 |

## 🧱 现状

`app/segment/router.py:103-111` `list_segments` 现状：**无 `Depends(get_current_user)`**（赛段目录公开）。本 task 保持公开。

## 🛠 完整代码

抄 spec §4.1（行 2286-2326）的 endpoint 设计 + service 调用：

```python
# 行 103-111 list_segments 改造
@router.get("", response_model=schemas.SegmentListResponse)
def list_segments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    near_lat: float | None = Query(None),
    near_lon: float | None = Query(None),
    radius: float = Query(50000),  # 沿用现有 default 50km，第二轮双审 B1-B2 已修
    search: str | None = Query(None, min_length=2, description="赛段名模糊搜索（≥ 2 字）"),
    city: str | None = Query(None, regex="^(beijing|shanghai|hangzhou|shenzhen|chengdu|taiyuan|unknown)$"),
    difficulty: str | None = Query(None, regex="^(easy|medium|hard|extreme)$"),
    db: Session = Depends(get_db),
    # 第二轮双审 B1-B3 + Tim 拍：保持公开，不加 get_current_user
):
    items, total = service.get_segment_list(
        db, page, page_size, near_lat, near_lon, radius,
        search=search, city=city, difficulty=difficulty,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# 新增 efforts/me endpoint
@router.get("/{segment_id}/efforts/me", response_model=schemas.EffortCompareResponse)
def get_my_effort_compare(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 第二轮双审 B1-B4 修复：router 显式查 segment 存在性抛 404
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, detail="赛段不存在")
    return service.get_my_effort_with_compare(db, segment_id, current_user.id)
```

### `app/segment/schemas.py` 加 response 模型

```python
class SegmentListItem(BaseModel):
    id: int
    name: str
    distance_km: float
    elevation_gain: float | None
    avg_gradient: float | None
    max_gradient: float | None  # v5 新增
    difficulty: str             # v5 新增
    city: str                   # v5 新增
    entries: int


class EffortCompareResponse(BaseModel):
    current_attempt_elapsed_time: int | None
    last_attempt_elapsed_time: int | None
    pr_elapsed_time: int | None
    current_attempt_diff_to_last: int | None
    current_attempt_is_pr: bool
    is_first_attempt: bool
```

## ✅ 测试

```python
# tests/test_segment_router_v5.py
def test_list_segments_anonymous_access():
    res = client.get("/api/segments?city=beijing&difficulty=hard")
    assert res.status_code == 200  # 公开访问
def test_list_segments_search_min_length(): 
    res = client.get("/api/segments?search=a")  # < 2 字
    assert res.status_code == 422  # FastAPI Query min_length 校验
def test_list_segments_invalid_city():
    res = client.get("/api/segments?city=unknown_city")
    assert res.status_code == 422
def test_get_my_effort_compare_segment_not_exist():
    res = client.get("/api/segments/99999/efforts/me", headers=auth)
    assert res.status_code == 404
def test_get_my_effort_compare_first_attempt(): ...
def test_get_my_effort_compare_pr_attempt(): ...
```

## 📝 commit

```
feat(segment): 任务 1.A.3 router 扩展 + 即时反馈 endpoint

- GET /api/segments 加 search/city/difficulty Query 参数（保持公开匿名）
- GET /api/segments/{id} 响应加 max_gradient/city/difficulty
- 新增 GET /api/segments/{id}/efforts/me（router 层显式 404 校验）
- schemas.py 加 EffortCompareResponse + SegmentListItem 字段扩展
```

## 🔍 自检三问

1. **公开访问确认**：现有匿名用户能继续访问 `GET /api/segments` 吗？  
   → 是，未加 Depends(get_current_user)。同时 PRD §B-P02 已拍"赛段目录公开发现性内容"。

2. **404 路径**：service `get_my_effort_with_compare` 不抛 404，由 router 层 db.get(Segment) 校验抛——subagent 实施别在 service 重抛。  
   → 已确认 spec §4.1 efforts/me 表注明"404 由 router 显式校验，service 不抛"。

3. **search min_length**：传 `search='a'` 走到 service 会被忽略（service 内 `if search and len(search) >= 2`），但 router 层 Query(min_length=2) 已 422 拦——双层守卫冗余 OK 吗？  
   → 是。router 层 422 给前端友好错误；service 层守卫防直接 service 调用（如 admin 工具）漏校验。
