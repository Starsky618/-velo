# 任务 3.A.5：5.D.4 from-activity endpoint

## 🎯 目标

`app/admin/router.py` 追加 `POST /api/admin/segments/from-activity`：从指定 activity 的 trackpoints 子序列创建赛段，自动算所有指标。

## ⛓ 前置依赖

- task-3.A.4（admin 框架）
- task-1.A.2（service 已实现 `create_segment_from_activity` + advisory lock）

## 📤 输出契约

| 接口 | 用途 |
|---|---|
| POST /api/admin/segments/from-activity | admin 选 activity + start/end index → 自动建赛段 |

## 🛠 完整代码

抄 spec §4.3 POST /api/admin/segments/from-activity（行 2424-2445）。

```python
# app/admin/router.py 追加
from app.segment.exceptions import SegmentOverlapError, InvalidSegmentRangeError


@router.post("/segments/from-activity", response_model=schemas.SegmentResponse, status_code=201)
def create_segment_from_activity_admin(
    body: schemas.FromActivityRequest,  # activity_id, name, start_index, end_index, city?, difficulty?
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """从 activity 轨迹子序列创建赛段。
    
    advisory lock 串行化整个创建路径（task-1.A.2 service 已实现）。
    """
    try:
        seg = segment_service.create_segment_from_activity(
            db,
            activity_id=body.activity_id,
            name=body.name,
            start_index=body.start_index,
            end_index=body.end_index,
            city=body.city,
            difficulty=body.difficulty,
        )
        return seg
    except InvalidSegmentRangeError as e:
        raise HTTPException(400, str(e))
    except SegmentOverlapError as e:
        raise HTTPException(409, str(e))
```

### `app/segment/schemas.py` 加（或 admin schemas 新建）

```python
class FromActivityRequest(BaseModel):
    activity_id: int
    name: str = Field(..., min_length=2, max_length=128)
    start_index: int = Field(..., ge=0)
    end_index: int = Field(..., gt=0)
    city: str | None = Field(None, regex="^(beijing|...|unknown)$")
    difficulty: str | None = Field(None, regex="^(easy|medium|hard|extreme)$")
    
    @validator('end_index')
    def end_must_gt_start(cls, v, values):
        if 'start_index' in values and v <= values['start_index']:
            raise ValueError('end_index must > start_index')
        return v
```

## ✅ 测试

```python
def test_from_activity_basic_create_201(): ...
def test_from_activity_invalid_range_400():
    # start_index >= end_index → InvalidSegmentRangeError → 400
def test_from_activity_too_short_400():
    # distance < 1km → 400
def test_from_activity_overlap_409():
    # 已存在重叠赛段 → SegmentOverlapError → 409
def test_from_activity_normal_user_403():
def test_from_activity_concurrent_advisory_lock():
    # 关键：2 admin 并发调同一段轨迹，advisory lock 串行化
    # 期望：1 个 201，1 个 409
def test_from_activity_auto_difficulty_inferred():
def test_from_activity_auto_city_inferred():
```

## 📝 commit

```
feat(admin): 任务 3.A.5 from-activity endpoint (5.D.4)

- POST /api/admin/segments/from-activity（201 / 400 / 409）
- 调 segment.service.create_segment_from_activity（advisory lock + Hausdorff 重复检测）
- schemas.FromActivityRequest（含 start < end validator）

异常翻译：
- InvalidSegmentRangeError → 400
- SegmentOverlapError → 409
```

## 🔍 自检三问

1. **advisory lock 行为**：service 层已加 `pg_advisory_xact_lock`，本 endpoint 不需要再加。  
   → 是。lock 在 service 函数最开头（task-1.A.2 实现），事务结束自动释放。endpoint 只调用 service 即可。

2. **重复检测算法**：service 用 ST_HausdorffDistance < 0.0005°（≈ 55m）—— spec 实施时若发现误判可调阈值。  
   → 是。第二轮双审 B1-B7 修复（不用 ST_Intersection + ST_Length）。

3. **start/end 校验**：validator 在 schema 层 + service 层都校验（双层）。schema 422 / service 400 路径区别？  
   → schema validator 失败 → FastAPI 自动 422；service raise InvalidSegmentRangeError → router catch 翻 400。两个状态码语义不同（422 = 输入格式不符 / 400 = 业务规则违反），可接受。
