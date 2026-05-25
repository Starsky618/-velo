# Sprint 11 Task-3 — 训练分布 API

> 所属：Sprint 11（训练分布分析）/ 第 3 个 task / 后端接口层。
> 前置：Task 2 纯函数和单测通过。
> 范围：新增 `/api/training/distribution?range=6w`，只读当前用户活动，不改表结构。
> 文案门：Tim 已确认 spec §4.1 的 5 类型文案表先作为 v1 上线；接口只返回文案表内容，不现场改写。

---

## ─────── 给 Tim 看 ───────

### 干啥用

小程序打开“训练结构”页时，不自己去翻活动列表，也不自己算训练学判断；它只请求一次后端，拿到页面要展示的完整结果。

这个 task 就像在后端开一个“训练结构窗口”：用户报自己的 token，窗口只查他的最近 6 周骑行，然后把判断、原因、行动建议和图表数据一次性打包返回。

### 用户故事

张三点进训练结构页，页面拿到一句判断、两张对比卡、三组时间分布、下周 3 件事和一周安排。张三不用懂 Z1-Z6，也不会看到别人的数据。

### 怎么算做对了

- ✓ 登录用户请求 `/api/training/distribution?range=6w` 返回 200。
- ✓ 未登录返回 401。
- ✓ `range=30d` 返回 422。
- ✓ 不串到其他用户数据。
- ✓ 跳过 duplicate、非 cycling、failed、无 power_zones、started_at 为空的活动。
- ✓ `raw_zones` 不含 `min_w/max_w`。
- ✓ `/api/training/load` 继续通过回归测试。

### 这次不做

- 不做小程序页面。
- 不新增数据库字段或迁移。
- 不改 worker hook。
- 不支持看他人训练结构。
- 不接 LLM，不写每日推荐。

### 估时

0.5-1 天，含 API 单测和回归。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md | sed -n '47,137p'
nl -ba app/training/schemas.py | sed -n '1,90p'
nl -ba app/training/router.py | sed -n '1,50p'
nl -ba app/training/service.py | sed -n '35,80p;100,130p'
nl -ba app/activity/models.py | sed -n '50,130p;155,165p'
nl -ba tests/test_training_load_api.py | sed -n '94,190p'
```

已验证事实：
- `TrainingLoadResponse` 用 `ConfigDict(extra="forbid")`，[✓ grep] `app/training/schemas.py:56-63`，Sprint 11 schema 同样使用。
- training router 现有前缀是 `/api/training`，[✓ grep] `app/training/router.py:16`。
- 现有 `/api/training/load` route 在同一文件，[✓ grep] `app/training/router.py:19-26`，本 task 不能破坏。
- 北京时间 helper 已存在 `_today_bj` / `_bj_day_start_utc`，[✓ grep] `app/training/service.py:56-75`，Sprint 11 直接 import，不复制。
- 现有覆盖率查询用了 start/end 双边界，[✓ grep] `app/training/service.py:107-123`。
- SQLite 测试 fixture 把 `power_zones` 当 Text，[✓ grep] `tests/conftest.py:118-120`，service 必须兼容 JSON string。

## 2. 文件改动清单

硬门：先创建 API 测试并确认失败，再写 service/router/schema；禁止先写实现后补测试。

- Create `app/training/distribution_service.py`：查询 Activity，调用 Task 2 纯函数，组装响应。
- Modify `app/training/schemas.py`：新增 Sprint 11 响应 schema。
- Modify `app/training/router.py`：新增 `GET /distribution`。
- Create `tests/test_training_distribution_api.py`：API 行为测试。
- Modify nothing under `migrations/`。
- Modify nothing under `miniprogram/`。

## 3. schema 合同

在 `app/training/schemas.py` 新增：

```python
TrainingDistributionRange = Literal["6w"]
TrainingDistributionType = Literal["polarized", "pyramidal", "sweet_spot", "threshold", "mixed"]


class TrainingDistributionZone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone: Literal["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]
    name: str
    seconds: int
    percent: int


class TrainingDistributionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Literal["endurance", "tempo_threshold", "high_intensity"]
    label: str
    zones: list[str]
    seconds: int
    percent: int
    role: str


class TrainingDistributionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    body: str


class TrainingDistributionWeekItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: str
    title: str
    focus: str


class TrainingDistributionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    range: TrainingDistributionRange
    window_days: int
    activity_count: int
    total_power_seconds: int
    total_power_hours: float
    data_complete: bool
    insufficient_power_data: bool
    current_type: TrainingDistributionType | None
    current_label: str
    current_description: str
    target_label: str
    target_description: str
    headline: str
    explanation: str
    groups: list[TrainingDistributionGroup]
    raw_zones: list[TrainingDistributionZone]
    actions: list[TrainingDistributionAction]
    week_plan: list[TrainingDistributionWeekItem]
```

## 4. service 查询合同

`app/training/distribution_service.py`：

```python
from datetime import timedelta

from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.training.distribution import aggregate_power_zones, build_training_distribution_payload, normalize_power_zones
from app.training.service import _bj_day_start_utc, _today_bj
```

函数签名固定为：

```python
get_training_distribution_response(db: Session, user_id: int, range: str = "6w") -> dict
```

查询必须同时满足：

```python
Activity.user_id == user_id
Activity.status == "completed"
Activity.activity_type == "cycling"
Activity.duplicate_of.is_(None)
Activity.started_at.isnot(None)
Activity.started_at >= start_utc
Activity.started_at < end_utc
Activity.power_zones.isnot(None)
```

调用顺序必须写死：
1. 查询 Activity 行。
2. 对每条 `activity.power_zones` 调 `normalize_power_zones(...)`。
3. 把所有 zone list 传给 `aggregate_power_zones(...)`。
4. 把聚合结果传给 `build_training_distribution_payload(...)`。
5. 合并 `range/window_days/activity_count` 等 service 字段后返回 schema 所需完整 dict。

时间窗口：

```python
today = _today_bj()
start_day = today - timedelta(days=41)
end_day = today + timedelta(days=1)
start_utc = _bj_day_start_utc(start_day)
end_utc = _bj_day_start_utc(end_day)
```

注意：
- service 不 `commit()`。
- service 不读取 `snapshot_ftp`。
- service 不返回 `min_w/max_w`。
- `range` 只支持 `"6w"`；router 的 Literal 会让其他值走 422。

## 5. router 合同

在 `app/training/router.py` 新增 route：

```python
@router.get("/distribution", response_model=schemas.TrainingDistributionResponse)
def get_training_distribution(
    range: schemas.TrainingDistributionRange = Query("6w"),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户最近 6 周训练结构。"""
    return distribution_service.get_training_distribution_response(db, user_id, range)
```

import 规则：
- 保留现有 `from app.training import schemas, service`，不要改坏 `/load`。
- 新增 `from app.training import distribution_service`。

## 6. API 单测清单

新增 `tests/test_training_distribution_api.py`，至少 10 个 case：

1. `test_training_distribution_returns_complete_payload`
2. `test_training_distribution_requires_login`
3. `test_training_distribution_invalid_range_returns_422`
4. `test_training_distribution_does_not_leak_other_user_data`
5. `test_training_distribution_filters_duplicate_activities`
6. `test_training_distribution_filters_non_cycling_and_failed`
7. `test_training_distribution_filters_missing_started_at`
8. `test_training_distribution_filters_missing_power_zones`
9. `test_training_distribution_raw_zones_are_privacy_safe`
10. `test_training_distribution_accepts_sqlite_json_string_power_zones`
11. `test_training_distribution_incomplete_flags_match`
12. `test_training_load_endpoint_still_works_after_distribution_route_added`
13. `test_training_distribution_filters_outside_42_day_window`
14. `test_training_distribution_current_and_target_descriptions_present`
15. `test_training_distribution_groups_have_fixed_label_and_role`
16. `test_training_distribution_week_plan_is_structured`

测试 helper 示例：

```python
import json
from datetime import datetime, timedelta, timezone

from app.activity.models import Activity
from app.training.service import _today_bj

_BJ_TZ = timezone(timedelta(hours=8))


def _utc_for_bj_day(day_offset: int, hour: int = 12) -> datetime:
    today = _today_bj()
    target = today + timedelta(days=day_offset)
    return datetime(target.year, target.month, target.day, hour, 0, 0, tzinfo=_BJ_TZ).astimezone(timezone.utc)


def _zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900, z6=0):
    return [
        {"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 129, "seconds": z1, "percent": 9},
        {"zone": "Z2", "name": "耐力", "min_w": 130, "max_w": 176, "seconds": z2, "percent": 40},
        {"zone": "Z3", "name": "节奏", "min_w": 177, "max_w": 211, "seconds": z3, "percent": 27},
        {"zone": "Z4", "name": "阈值", "min_w": 212, "max_w": 247, "seconds": z4, "percent": 15},
        {"zone": "Z5", "name": "VO2max", "min_w": 248, "max_w": 282, "seconds": z5, "percent": 8},
        {"zone": "Z6", "name": "无氧", "min_w": 283, "max_w": None, "seconds": z6, "percent": 0},
    ]


_USE_DEFAULT_STARTED_AT = object()
_USE_DEFAULT_POWER_ZONES = object()


def _insert_activity(
    db,
    user_id: int,
    *,
    power_zones=_USE_DEFAULT_POWER_ZONES,
    status="completed",
    activity_type="cycling",
    duplicate_of=None,
    started_at=_USE_DEFAULT_STARTED_AT,
):
    actual_started_at = _utc_for_bj_day(-1) if started_at is _USE_DEFAULT_STARTED_AT else started_at
    actual_power_zones = _zones() if power_zones is _USE_DEFAULT_POWER_ZONES else power_zones
    activity = Activity(
        user_id=user_id,
        title="训练结构测试骑行",
        status=status,
        activity_type=activity_type,
        duration=3600,
        started_at=actual_started_at,
        power_zones=actual_power_zones,
        duplicate_of=duplicate_of,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity
```

## 7. 验收命令

```bash
python3 -m pytest tests/test_training_distribution.py tests/test_training_distribution_api.py -q
python3 -m pytest tests/test_training_load_api.py -q
python3 -m pytest tests/test_training_daily_load_hook.py -q
python3 -c "from app.training.router import router; print(router.prefix)"
git diff --check
```

## 8. 5 字段 issue 草稿

背景：Task 2 已经能把 `power_zones` 翻译成训练结构；Task 3 要把它接成当前用户自己的后端接口。目标：新增 `distribution_service.py`、schema、`GET /api/training/distribution?range=6w` 和 API 测试。验收命令：`python3 -m pytest tests/test_training_distribution.py tests/test_training_distribution_api.py tests/test_training_load_api.py -q`。不要碰：DB schema、migration、小程序页面、worker、`/api/training/load` 行为。失败处理：如果 `/load` 回归红，先撤回 Sprint 11 route/schema 改动定位，不改 Sprint 10 service 来迁就 Sprint 11。

## 9. commit message 模板

`feat(training): sprint11 task-3 distribution api`

正文：`Add current-user training distribution endpoint, schemas, service, and API tests. Keep raw_zones privacy-safe, reuse BJ date helpers, filter duplicates/non-cycling/incomplete activities, and preserve /api/training/load.`

</details>
