# 任务 7.7：解析器入口分流（多运动种子 3）

> 本期**不做**跑步/徒步等多运动支持——只埋一颗"种子"：解析器入口先看 `activity_type`，不是 cycling 的直接置 failed。
> 未来第 5/6 期真正做多运动时，只需在这里加 `elif activity_type == 'running': _parse_running(...)`，不用大改结构。

---

## 🎯 目标（一句话）

给 `parse_activity`（解析 Worker 的总入口）加一个岔路口：读 `activity.activity_type`，只有 `cycling` 继续走现有解析流程，其他一律置 failed——**本期不新增功能，只建岔路口**。

---

## ⛓ 前置依赖

- **task-7.1**（`activities.activity_type` 字段已存在，值默认 'cycling'）

## 📥 输入契约

**现有代码事实核对**：

| 项目 | 位置 | 现状 |
|------|------|------|
| 解析入口 | `app/activity/worker.py:49-69` | `parse_activity(activity_id)` — 总入口 |
| 核心流程 | `app/activity/worker.py:72-149` | `_do_parse(db, activity_id)` — 实际解析逻辑 |
| 失败标记 | `app/activity/worker.py:251-267` | `_mark_failed(db, activity_id, error_message)` |

## 📤 输出契约

| 产出 | 签名 | 说明 |
|------|------|------|
| `parse_activity` 入口加分流 | `(activity_id)` 不变 | 读完 Activity 后按 activity_type 分流 |
| 未来扩展位置 | 同函数内 `if activity_type == 'cycling':` 分支 | 新增运动类型加 elif 即可 |

---

## 🛠 完整代码

### `app/activity/worker.py` 改造 `_do_parse`

**关键设计**：`parse_activity` 本身不改（保留 try/except 外壳），改 `_do_parse` 内部——在**抢锁之后、下载文件之前**做分流判断。

**为什么放在这个位置**：
- 抢锁后：保证这个 activity 确实归我处理（避免多 Worker 竞争）
- 下载之前：非 cycling 的根本不需要下载文件（省 I/O）

**改造前**（`_do_parse` 开头）：

```python
def _do_parse(db, activity_id: int) -> None:
    # ===== 步骤 1：原子抢锁 =====
    result = db.execute(update(Activity).where(...).values(status="processing")...)
    ...
    db.commit()
    if locked_row is None:
        return

    # ===== 步骤 2：取完整记录 =====
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        return
    ...

    # ===== 步骤 3：下载文件 =====
    file_content = _storage.download(activity.file_url)
```

**改造后**：

```python
def _do_parse(db, activity_id: int) -> None:
    # ===== 步骤 1：原子抢锁 =====（保持不变）
    result = db.execute(
        update(Activity)
        .where(Activity.id == activity_id, Activity.status == "pending")
        .values(status="processing", updated_at=func.now())
        .returning(Activity.id)
    )
    locked_row = result.fetchone()
    db.commit()

    if locked_row is None:
        return

    # ===== 步骤 2：取完整记录 =====（保持不变）
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        return

    # ===== 步骤 2.5：🌱 运动类型分流（种子 3）=====
    # 本期只支持 cycling。未来加运动类型时，在这里加 elif 分支：
    #   elif activity.activity_type == 'running':
    #       _parse_running(db, activity)
    #       return
    # 结构设计理由：
    #   - 分流点在"锁后、文件下载前"：节省非 cycling 活动的文件下载 I/O
    #   - 每种运动的解析分到独立函数（_parse_cycling / _parse_running 等），
    #     彼此互不干扰，方便独立测试和维护
    #   - 主入口 parse_activity 的 try/except 外壳不变，异常处理统一
    if activity.activity_type != "cycling":
        activity.status = "failed"
        activity.error_message = f"暂不支持的运动类型: {activity.activity_type}"
        db.commit()
        logger.warning(
            "活动 %d 运动类型 %s 暂不支持，置 failed",
            activity_id, activity.activity_type,
        )
        return

    # ===== 步骤 3：下载文件（以下保持原样）=====
    user = db.query(User).filter_by(id=activity.user_id).first()
    if user is None:
        raise ValueError(f"User {activity.user_id} 不存在")

    file_content = _storage.download(activity.file_url)

    # ... 原有步骤 4~11 完全不变
```

> **不新增 `_parse_cycling` 函数**：spec §2.4 建议把现有解析逻辑抽成 `_parse_cycling`。但审视现状——`_do_parse` 已经是"解析骑行"的完整函数，抽出 `_parse_cycling` 再把 `_do_parse` 变成壳层 = 纯粹改名不增价值。本期不动。未来真正加第二种运动（running）时，再把 cycling 分支抽出也不迟——那时候才有"两种并列"的真实收益。符合 CLAUDE.md 第 5 条："不做 spec 里没有的功能"——spec 只要求"分流"，没要求"重构"。

### logger 补充

确认 `worker.py` 顶部已有：

```python
import logging
logger = logging.getLogger(__name__)
```

没有的话加上（预读文件确认）。

---

## 🧪 测试

**文件**：`tests/activity/test_parse_activity_type.py`（新建）

```python
from unittest.mock import patch, MagicMock

from app.activity.models import Activity
from app.activity.worker import parse_activity


def test_cycling_activity_goes_full_path(db, user_factory):
    """activity_type='cycling' 应走完整解析流程。"""
    user = user_factory()
    activity = Activity(
        user_id=user.id,
        title="Test Ride",
        status="pending",
        file_url="test.gpx",
        activity_type="cycling",
    )
    db.add(activity)
    db.commit()

    # mock 文件下载 + 解析器（让它走通整个流程）
    with patch("app.activity.worker._storage") as mock_storage, \
         patch("app.activity.worker.GPXParser") as MockParser:
        mock_storage.download.return_value = b"<gpx>...</gpx>"

        mock_result = MagicMock()
        mock_result.summary.distance = 10000
        mock_result.summary.duration = 1800
        mock_result.summary.avg_speed = 5.5
        mock_result.summary.max_speed = 10.0
        mock_result.summary.avg_power = None
        mock_result.summary.max_power = None
        mock_result.summary.avg_hr = None
        mock_result.summary.max_hr = None
        mock_result.summary.avg_cadence = None
        mock_result.summary.calories = 300
        mock_result.summary.normalized_power = None
        mock_result.summary.started_at = None
        mock_result.summary.finished_at = None
        mock_result.summary.elevation_gain = 100
        mock_result.summary.splits = []
        mock_result.metadata.title = "Test"
        mock_result.metadata.source.value = "gpx"
        mock_result.simplified_track = []
        mock_result.power_zones = {}
        mock_result.trackpoints = []
        MockParser.return_value.parse.return_value = mock_result

        with patch("app.activity.worker.normalize", return_value=mock_result):
            parse_activity(activity.id)

    db.refresh(activity)
    assert activity.status == "completed"


def test_non_cycling_activity_marked_failed(db, user_factory):
    """activity_type='running' 应直接置 failed，不下载文件。"""
    user = user_factory()
    activity = Activity(
        user_id=user.id,
        title="Test Run",
        status="pending",
        file_url="test.gpx",
        activity_type="running",
    )
    db.add(activity)
    db.commit()

    with patch("app.activity.worker._storage") as mock_storage:
        parse_activity(activity.id)

        # 关键：文件 I/O 不应被触发（分流点在下载前）
        mock_storage.download.assert_not_called()

    db.refresh(activity)
    assert activity.status == "failed"
    assert "running" in activity.error_message
    assert "不支持" in activity.error_message


def test_unknown_activity_type_marked_failed(db, user_factory):
    """未来扩展前，未知运动类型也置 failed。"""
    user = user_factory()
    activity = Activity(
        user_id=user.id,
        title="Test",
        status="pending",
        file_url="test.gpx",
        activity_type="skydiving",  # 乱写
    )
    db.add(activity)
    db.commit()

    parse_activity(activity.id)

    db.refresh(activity)
    assert activity.status == "failed"
    assert "skydiving" in activity.error_message
```

---

## 📦 Commit 指令

```bash
git add app/activity/worker.py tests/activity/test_parse_activity_type.py

git commit -m "$(cat <<'EOF'
feat(activity): 任务 7.7 解析器入口按 activity_type 分流（种子 3）

_do_parse 加岔路口：
- 抢锁后、下载文件前读 activity.activity_type
- 'cycling' 继续走完整解析流程
- 非 'cycling' 直接置 failed，不下载文件（省 I/O）

未来扩展：
- 新增 running/hiking 等运动类型时，在分流点加 elif + _parse_running 等
- 本期不抽出 _parse_cycling 函数（仅一个分支，抽出是纯粹改名不增价值）

测试：
- cycling 活动走完整流程
- running 活动置 failed 且不触发文件下载
- 未知类型兜底置 failed
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清这次改动在系统里加了什么？

> 在解析入口加了一个"只放骑行过"的岔路口——抢到任务后先看 activity_type 字段：cycling 放行走完整流程，其他一律标失败。未来想加跑步、徒步，只需在这里多写一个分支，不用动任何已有逻辑。

**2. 崩溃场景**：如果 activity_type 字段为 NULL 会怎样？

> 不会——task-7.1 的 migration 里 `activity_type` 是 `NOT NULL DEFAULT 'cycling'`，DB 层保证不会 NULL。即使 ORM 模型层某天漏了默认值，`!= "cycling"` 遇到 NULL 的结果是 True（NULL 和任何值不等），会走 failed 分支——安全兜底。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格按 spec §2.4 + §9.1 种子 3 做事：
> - 只加分流，**不抽函数**（spec 提的 `_parse_cycling` 被我独立判断不做——一个分支不值得抽）
> - 不改 `parse_activity` 外壳的 try/except 结构
> - 不改下游任何函数（`save_parse_result` / `_mark_failed` / `_get_file_extension` 都不动）
> - 不顺手加 activity_type 的 CHECK 约束（那是未来活动类型稳定后该做的）
