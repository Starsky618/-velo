# Sprint 5 Task-4.3 — 新 endpoint：我在某赛段的所有成绩

> 所属：Sprint 5 task-4 系列（6 个 task）/ 第 3 个 / 前置：task-4.1 `f877844` + task-4.2 `9058ba3`

---

## ─────── 给 Tim 看 ───────

### 干啥用

加一个**新接口**——返回"我在某个赛段骑过的全部成绩"，是后面 task-4.5 那个"我的成绩列表"全屏页（图 1）的数据源。

### 用户故事

我在妙峰山骑过 5 次 → 后端开放 `GET /api/segments/42/my-efforts` →
返回 5 条记录（按时间倒序，最新的在前）：

```
[
  { activity_id: 99, elapsed_time: 1297, avg_speed: 26.5, avg_power: 107, created_at: 2025-05-11, is_pr: false },
  { activity_id: 87, elapsed_time: 1124, avg_speed: 30.6, avg_power: 160, created_at: 2024-07-03, is_pr: false },
  ...
  { activity_id: 12, elapsed_time:  256, avg_speed: 32.2, avg_power: 146, created_at: 2024-05-11, is_pr: true  },
  ...
]
```

`is_pr: true` 标记我的最快那条（图 1 那个黄色小圆点）。

### 怎么算做对了

- ✓ 必须登录访问（不像排行榜可以匿名 / 这是"我的数据"）
- ✓ 只返**当前登录用户**自己的 effort（不能看别人的 my-efforts）
- ✓ 按 created_at 倒序（最新在前 / 跟图 1 一致）
- ✓ 每条带：activity_id（跳转用）/ elapsed_time / avg_speed / avg_power / created_at / is_pr
- ✓ 只有"最快那条" is_pr=true，其他全 false
- ✓ 同赛段我有 5 条 effort → 接口返 5 条（不去重 / 跟主榜每人一行不同 / 这是我自己的成绩单）

### 这次**不做**

- 小程序前端调用 + 渲染（task-4.5 才做）
- 跳转 activity 详情（task-4.5）

### 估时

0.5 天

---

## ─────── 折叠：技术细节 ───────

<details>

### 现状 grep

- `app/segment/router.py` 现有 endpoint：list / detail / leaderboard / activity_segments
- `app/segment/service_query.py:get_user_efforts` 是"用户在**所有赛段**的成绩单"（不是某一个赛段）→ 新接口要的是按 segment_id 过滤的版本
- `app/segment/schemas.py` 已有 `LeaderboardEntry` / `EffortCompareResponse` / 无 `MyEffortItem`

### 新接口

`GET /api/segments/{segment_id}/my-efforts`
- 需登录（Depends(get_current_user)）
- 路径参数：segment_id
- 返回：`MySegmentEffortsResponse { items: list[MySegmentEffortItem] }`

### 新 schema

```python
class MySegmentEffortItem(BaseModel):
    activity_id: int
    elapsed_time: int
    avg_speed: Optional[float] = None
    avg_power: Optional[float] = None
    created_at: datetime
    is_pr: bool

class MySegmentEffortsResponse(BaseModel):
    items: list[MySegmentEffortItem]
```

### service 实现

`app/segment/service_query.py:get_my_efforts_on_segment(db, segment_id, user_id)`：

```python
def get_my_efforts_on_segment(db: Session, segment_id: int, user_id: int) -> list[dict]:
    # 校验赛段存在
    if db.query(Segment.id).filter_by(id=segment_id).first() is None:
        raise ValueError("赛段不存在")

    efforts = (
        db.query(SegmentEffort)
        .filter(
            SegmentEffort.segment_id == segment_id,
            SegmentEffort.user_id == user_id,
        )
        .order_by(SegmentEffort.created_at.desc(), SegmentEffort.id.desc())
        .all()
    )
    if not efforts:
        return []

    # is_pr：找出最快那条的 (elapsed_time, id) tuple，与 task-4.2 tiebreaker 一致
    pr_key = min((e.elapsed_time, e.id) for e in efforts)

    return [
        {
            "activity_id": e.activity_id,
            "elapsed_time": e.elapsed_time,
            "avg_speed": e.avg_speed,
            "avg_power": e.avg_power,
            "created_at": e.created_at,
            "is_pr": (e.elapsed_time, e.id) == pr_key,
        }
        for e in efforts
    ]
```

### router 实现

```python
@router.get("/{segment_id}/my-efforts", response_model=schemas.MySegmentEffortsResponse)
def get_my_efforts(
    segment_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前登录用户在该赛段的全部成绩（按时间倒序）。"""
    try:
        items = service.get_my_efforts_on_segment(db, segment_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return schemas.MySegmentEffortsResponse(items=items)
```

### 测试覆盖

- `test_my_efforts_returns_only_self` — 别人 3 条 + 我 2 条，接口只返我的 2 条
- `test_my_efforts_ordered_by_created_at_desc` — 时间倒序（最新在前）
- `test_my_efforts_is_pr_marks_fastest` — 3 条 elapsed_time [150/100/200]，is_pr=true 仅 100 那条
- `test_my_efforts_empty_when_no_effort` — 没骑过返 []
- `test_my_efforts_segment_not_found` — 不存在的赛段返 404
- `test_my_efforts_requires_auth` — 无 token 401
- `test_my_efforts_is_pr_tiebreaker` — 2 条都 100s（不同 id），is_pr 只标 id 最小那条（跟主榜 tiebreaker 一致）

### 红线

- 不动 get_user_efforts（"所有赛段的成绩单"是 task-4.5 也许会用 / 别破坏）
- 不动 leaderboard / activity_segments
- 不预写前端

### Codex 异源审重点

- is_pr tiebreaker 是否跟主榜 (elapsed_time, effort_id) 严格一致（防同秒并列时主榜显示某用户 rank=1 但 my-efforts 把另一条标 is_pr=true）
- 不存在的 segment → 404 / 不是 200 []
- 别人的 effort 是否真不返（grep filter）
- 需登录 401 / 不是 403

</details>
