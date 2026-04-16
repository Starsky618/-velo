# 事件通知系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全核心反馈环——用户破 PR、拿 KOM 时主动通知，KOM 被夺时提醒原持有者。附加用户荣誉表（KOM/前十）。

**Architecture:** 新增 notification 模块（4 文件），通过唯一函数 `detect_events()` 与 auto_match/import_scheduler 衔接。纯函数 `detector.classify()` 做事件判定，service 层做数据库读写，SAVEPOINT 隔离保证故障不扩散。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 同步 / PostgreSQL 16 / SQLite（测试）

**Spec:** `docs/spec-v3.md`

**严格约束：只做 spec 里写的，不加功能、不顺手优化、不独自发挥。**

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `app/notification/__init__.py` | 模块说明 |
| Create | `app/notification/models.py` | Notification ORM 模型 |
| Create | `app/notification/detector.py` | 纯函数：事件分类判定 |
| Create | `app/notification/service.py` | 业务逻辑：检测、查询、清理 |
| Create | `app/notification/router.py` | API 路由：通知列表 + 荣誉表 |
| Create | `migrations/versions/phase3_notifications.py` | Alembic 迁移脚本 |
| Create | `tests/test_notification.py` | 通知模块测试 |
| Modify | `app/segment/service.py` | 新增共享函数 `get_effort_rank()` |
| Modify | `app/segment/auto_match.py:135-206` | commit 后调用 detect_events |
| Modify | `app/strava/import_scheduler.py:348-357` | 匹配后调用 detect_events |
| Modify | `app/main.py:40-48` | 注册 notification 路由 |
| Modify | `tests/conftest.py` | 新增 notifications 测试表 |

---

### Task 1: Notification 数据模型 + Alembic 迁移

**对应 spec**: 第 1 章

**Files:**
- Create: `app/notification/__init__.py`
- Create: `app/notification/models.py`
- Create: `migrations/versions/phase3_notifications.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: 创建模块目录和 `__init__.py`**

```python
# app/notification/__init__.py
"""
通知模块——"广播室"。

这个模块负责在用户破 PR、拿 KOM 时生成通知，
在 KOM 被夺时提醒原持有者。

好比体育馆里的广播室：计时裁判（auto_match）登记完成绩后，
广播室拿到成绩单，判断有没有破纪录，然后广播给相关人。
广播室只读成绩单，不干预比赛。

操作注意事项：
- 这个模块和 segment 模块是单向依赖：notification 读 SegmentEffort，但 segment 不知道 notification 的存在
- detect_events() 是对外唯一写入接口，必须用 try/except + SAVEPOINT 隔离
- 不要在这个模块里 import segment/auto_match 或 segment/service（除了 get_effort_rank 共享函数）
"""
```

- [ ] **Step 2: 创建 `models.py`**

```python
# app/notification/models.py
"""
通知记录表——"广播室的公告栏"。

每条记录是一个原子事件：某用户在某赛段发生了某件事（破 PR / 拿 KOM / KOM 被夺）。
前端拿到列表后按 activity_id 分组聚合展示。

操作注意事项：
- elapsed_time 类型必须是 Integer（和 SegmentEffort 一致），不是 Float
- effort_id 用 ON DELETE SET NULL（不是 CASCADE），避免他人通知被级联删除
- 写入后不可变，没有"更新通知"的场景
"""
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey,
    UniqueConstraint, Index, CheckConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class Notification(Base):
    """
    通知记录——"公告栏上的一张便签"。

    可以把它想象成体育馆公告栏上的便签纸：
    "张三在滨河东路冲刺段跑出了 312 秒，排名第 1！（KOM）"
    便签贴上去后不会修改，60 天后自动撕掉。

    和 SegmentEffort（成绩单）的区别：
    成绩单是事实记录，永久保存；便签是通知，有过期时间。
    成绩变了排名会变，但便签记录的是"那一刻"的排名快照。
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)

    # 通知接收人
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 事件类型：pr（个人最佳）/ kom（赛段王）/ kom_lost（KOM 被夺）
    event_type = Column(String(20), nullable=False)

    # ---- 关联实体 ----
    # 哪条赛段
    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 触发这条通知的骑行（kom_lost 时存夺走者的活动）
    activity_id = Column(
        Integer,
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=True,
    )
    # 关联的成绩记录（删成绩后通知保留，只是看不到详情）
    effort_id = Column(
        Integer,
        ForeignKey("segment_efforts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- 事件快照数据 ----
    # 成绩用时（秒，整数，与 SegmentEffort.elapsed_time 类型一致）
    # kom_lost 时为 null
    elapsed_time = Column(Integer, nullable=True)
    # 排名快照。PR 且排名 > 10 时为 null（前端只显示"新 PR"）
    rank = Column(Integer, nullable=True)

    # ---- KOM 被夺时的对手信息 ----
    rival_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- 生命周期 ----
    # created_at + 60 天，过期后由定时任务清理
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        # 幂等防护：同一条成绩不重复生成同类型通知
        UniqueConstraint("effort_id", "event_type", name="uq_notif_effort_type"),
        # 通知列表查询：按用户 + 时间倒序
        Index("idx_notif_user_created", "user_id", "created_at"),
        # 过期清理
        Index("idx_notif_expires", "expires_at"),
        # 事件类型约束
        CheckConstraint(
            "event_type IN ('pr', 'kom', 'kom_lost')",
            name="ck_notif_event_type",
        ),
    )
```

- [ ] **Step 3: 创建 Alembic 迁移脚本**

```python
# migrations/versions/phase3_notifications.py
"""
第 3 期：新建 notifications 表。

纯新建表，不涉及已有表修改，迁移风险低。
"""
from alembic import op
import sqlalchemy as sa


revision = "phase3_notifications"
down_revision = "phase2_strava_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("effort_id", sa.Integer(), sa.ForeignKey("segment_efforts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("elapsed_time", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("rival_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_unique_constraint("uq_notif_effort_type", "notifications", ["effort_id", "event_type"])
    op.create_index("idx_notif_user_created", "notifications", ["user_id", "created_at"])
    op.create_index("idx_notif_expires", "notifications", ["expires_at"])

    # SQLite 不支持 CHECK 约束中的 IN 语法，PostgreSQL 专用
    # 测试环境用 SQLite，生产环境用 PostgreSQL
    try:
        op.create_check_constraint(
            "ck_notif_event_type", "notifications",
            "event_type IN ('pr', 'kom', 'kom_lost')",
        )
    except Exception:
        pass  # SQLite 跳过


def downgrade() -> None:
    op.drop_table("notifications")
```

- [ ] **Step 4: 更新 `tests/conftest.py` — 新增 notifications 测试表**

在 conftest.py 现有的测试表定义区域（`_activities_table`、`_segments_table`、`_segment_efforts_table` 附近），新增 notifications 表定义。

在 `_test_metadata` 创建位置，确保 notifications 表也被创建。

```python
# 在现有的 _segment_efforts_table 定义之后，添加：
_notifications_table = sa.Table(
    "notifications",
    _test_metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, nullable=False),
    sa.Column("event_type", sa.String(20), nullable=False),
    sa.Column("segment_id", sa.Integer, nullable=False),
    sa.Column("activity_id", sa.Integer, nullable=True),
    sa.Column("effort_id", sa.Integer, nullable=True),
    sa.Column("elapsed_time", sa.Integer, nullable=True),
    sa.Column("rank", sa.Integer, nullable=True),
    sa.Column("rival_user_id", sa.Integer, nullable=True),
    sa.Column("expires_at", sa.DateTime, nullable=False),
    sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
)
```

- [ ] **Step 5: 运行测试确认不破坏现有功能**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/ -v --tb=short`
Expected: 所有现有测试 PASS（conftest 新增表不影响已有测试）

- [ ] **Step 6: Commit**

```bash
git add app/notification/__init__.py app/notification/models.py migrations/versions/phase3_notifications.py tests/conftest.py
git commit -m "feat(notification): 任务7.1 Notification 数据模型 + Alembic 迁移"
```

---

### Task 2: detector.py — 纯函数事件分类

**对应 spec**: 第 2 章

**Files:**
- Create: `app/notification/detector.py`
- Create: `tests/test_notification.py`（前两部分：纯函数测试）

- [ ] **Step 1: 写测试文件骨架 + 纯函数测试**

```python
# tests/test_notification.py
"""
通知模块测试。

测试分三层：
1. 纯函数测试（detector.classify）—— 不需要数据库
2. Service 测试（detect_events、get_notifications 等）—— 需要数据库
3. API 测试（router）—— 需要 TestClient
"""
from app.notification.detector import classify, EventResult, KomLostResult


# ===================== 纯函数测试 =====================

def test_classify_first_effort_is_pr_and_kom():
    """赛段第一条成绩：既是 PR 又是 KOM，无被夺者"""
    event, lost = classify(
        elapsed_time=300,
        rank=1,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert event.rank == 1
    assert lost is None


def test_classify_new_kom_dethrones_previous():
    """夺走别人的 KOM：生成 KOM + KOM 被夺"""
    event, lost = classify(
        elapsed_time=280,
        rank=1,
        is_pr=True,
        previous_kom_user_id=5,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert event.rank == 1
    assert lost is not None
    assert lost.previous_holder_user_id == 5
    assert lost.new_rank == 2


def test_classify_self_dethrone_no_lost():
    """自己打破自己的 KOM：只生成 KOM，不生成被夺"""
    event, lost = classify(
        elapsed_time=250,
        rank=1,
        is_pr=True,
        previous_kom_user_id=1,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert lost is None


def test_classify_pr_top10():
    """破 PR 且进前 10：通知带排名"""
    event, lost = classify(
        elapsed_time=320,
        rank=5,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=2,
    )
    assert event is not None
    assert event.event_type == "pr"
    assert event.rank == 5
    assert lost is None


def test_classify_pr_outside_top10():
    """破 PR 但排名 > 10：通知不带排名"""
    event, lost = classify(
        elapsed_time=500,
        rank=15,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=3,
    )
    assert event is not None
    assert event.event_type == "pr"
    assert event.rank is None
    assert lost is None


def test_classify_not_pr():
    """不是 PR：不生成通知"""
    event, lost = classify(
        elapsed_time=600,
        rank=20,
        is_pr=False,
        previous_kom_user_id=None,
        current_user_id=4,
    )
    assert event is None
    assert lost is None


def test_classify_tied_first_but_not_pr():
    """并列情况下 rank=1 但不是 PR（理论上不会发生，但防御）"""
    event, lost = classify(
        elapsed_time=300,
        rank=1,
        is_pr=False,
        previous_kom_user_id=None,
        current_user_id=5,
    )
    # rank==1 但不是 PR 意味着这个用户之前有更好的成绩
    # 这种情况不应该生成通知
    assert event is None
    assert lost is None
```

- [ ] **Step 2: 运行测试确认全部 FAIL**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/test_notification.py -v`
Expected: FAIL，ImportError: cannot import name 'classify'

- [ ] **Step 3: 实现 `detector.py`**

```python
# app/notification/detector.py
"""
事件分类纯函数——"裁判的判定规则书"。

这个文件只做一件事：接收数字（排名、用时、是否 PR），返回判定结果。
不碰数据库，不碰文件系统，不碰网络。

好比裁判手里的规则手册：
- 排第 1 → 判定为 KOM
- 排第 1 且有前任 → 前任被夺
- 破了个人纪录 → 判定为 PR
- 其他情况 → 不播报

操作注意事项：
- 这是纯函数模块，绝对不能 import 任何项目模块（models、service 等）
- 修改判定逻辑后必须同步更新测试用例
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EventResult:
    """
    检测结果——"裁判的判定书"。

    event_type: 'pr'（个人最佳）或 'kom'（赛段王）
    rank: 排名快照。PR 且排名 > 10 时为 None（前端只显示"新 PR"）
    """
    event_type: str
    rank: int | None


@dataclass(frozen=True)
class KomLostResult:
    """
    KOM 被夺事件——"通知原冠军的罚单"。

    previous_holder_user_id: 被夺者的用户 ID
    new_rank: 被夺者现在排第几（通常为 2）
    """
    previous_holder_user_id: int
    new_rank: int


def classify(
    elapsed_time: int,
    rank: int,
    is_pr: bool,
    previous_kom_user_id: int | None,
    current_user_id: int,
) -> tuple[EventResult | None, KomLostResult | None]:
    """
    根据排名和 PR 状态，判定应生成哪些事件。

    参数：
        elapsed_time: 成绩用时（秒，整数）
        rank: 当前排名（1 = 最快）
        is_pr: 是否为该用户在该赛段的个人最佳
        previous_kom_user_id: 原 KOM 持有者 user_id（无人时为 None）
        current_user_id: 当前骑手 user_id

    返回：
        (EventResult | None, KomLostResult | None)
        - 第一个元素：当前骑手的事件（KOM 或 PR），不是 PR 时为 None
        - 第二个元素：被夺者的事件，仅在夺走别人 KOM 时非 None

    判定优先级：KOM > PR。拿了 KOM 就不再生成 PR 通知（KOM 本身就是最好的 PR）。
    不是 PR 的成绩不生成任何通知。
    """
    # 不是 PR → 不生成通知（即使排名靠前，旧成绩更好，不值得通知）
    if not is_pr:
        return None, None

    # ---- KOM（排第 1）----
    if rank == 1:
        event = EventResult(event_type="kom", rank=1)

        # 检查是否夺走了别人的 KOM
        if (previous_kom_user_id is not None
                and previous_kom_user_id != current_user_id):
            lost = KomLostResult(
                previous_holder_user_id=previous_kom_user_id,
                new_rank=2,
            )
            return event, lost

        # 无前任（第一条成绩）或自己打破自己的 KOM
        return event, None

    # ---- PR（排名 2+）----
    # 排名 ≤ 10 时返回具体排名，> 10 时返回 None
    display_rank = rank if rank <= 10 else None
    event = EventResult(event_type="pr", rank=display_rank)
    return event, None
```

- [ ] **Step 4: 运行测试确认全部 PASS**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/test_notification.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/notification/detector.py tests/test_notification.py
git commit -m "feat(notification): 任务7.2 detector 纯函数事件分类 + 7 个测试"
```

---

### Task 3: 共享排名函数 + service.py 核心逻辑

**对应 spec**: 第 3 章

**Files:**
- Modify: `app/segment/service.py` — 新增 `get_effort_rank()`
- Create: `app/notification/service.py`

- [ ] **Step 1: 在 `tests/test_notification.py` 末尾追加 service 层测试**

```python
# ===================== Service 层测试 =====================
# 追加到 tests/test_notification.py 末尾

import sqlalchemy as sa
from datetime import datetime, timedelta


def _insert_activity(db, user_id, data_source="gpx", started_at=None):
    """测试辅助：插入活动记录"""
    if started_at is None:
        started_at = datetime.utcnow()
    from tests.conftest import _activities_table
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            status="completed",
            data_source=data_source,
            started_at=started_at,
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _insert_segment(db):
    """测试辅助：插入赛段记录"""
    from tests.conftest import _segments_table
    result = db.execute(
        _segments_table.insert().values(
            name="测试赛段",
            distance=5000.0,
            start_lat=37.87, start_lon=112.55,
            end_lat=37.88, end_lon=112.56,
            reference_line="LINESTRING(112.55 37.87, 112.56 37.88)",
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _insert_effort(db, segment_id, activity_id, user_id, elapsed_time, created_at=None):
    """测试辅助：插入赛段成绩"""
    from tests.conftest import _segment_efforts_table
    if created_at is None:
        created_at = datetime.utcnow()
    result = db.execute(
        _segment_efforts_table.insert().values(
            segment_id=segment_id,
            activity_id=activity_id,
            user_id=user_id,
            elapsed_time=elapsed_time,
            start_index=0,
            end_index=100,
            created_at=created_at,
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def test_detect_events_pr(db, test_user):
    """上传骑行后破 PR → 生成 PR 通知"""
    seg_id = _insert_segment(db)
    act1_id = _insert_activity(db, test_user.id)
    act2_id = _insert_activity(db, test_user.id)

    # 第一条成绩：300 秒（这会是 KOM）
    _insert_effort(db, seg_id, act1_id, test_user.id, 300)

    # 第二条更好的成绩：280 秒（这会是新 KOM + PR）
    eff2_id = _insert_effort(db, seg_id, act2_id, test_user.id, 280)

    # 手动调用 detect_events
    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    effort = db.query(SegmentEffort).get(eff2_id)
    detect_events(db, effort)

    # 验证：应该生成 KOM 通知（因为自己就是 KOM，自己打破自己的）
    from app.notification.models import Notification
    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 1
    assert notifs[0].event_type == "kom"
    assert notifs[0].elapsed_time == 280
    assert notifs[0].rank == 1


def test_detect_events_idempotent(db, test_user):
    """重复调用 detect_events → 不产生重复通知"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification
    effort = db.query(SegmentEffort).get(eff_id)

    detect_events(db, effort)
    detect_events(db, effort)  # 重复调用

    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 1  # 只有一条，不重复


def test_detect_events_strava_history_skipped(db, test_user):
    """Strava 历史导入（超过 7 天）→ 不生成通知"""
    seg_id = _insert_segment(db)
    old_date = datetime.utcnow() - timedelta(days=30)
    act_id = _insert_activity(db, test_user.id, data_source="strava", started_at=old_date)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification
    effort = db.query(SegmentEffort).get(eff_id)

    detect_events(db, effort)

    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 0  # 历史导入不触发通知


def test_detect_events_gpx_old_activity_triggers(db, test_user):
    """手动上传的旧 GPX → 即使超过 7 天也生成通知"""
    seg_id = _insert_segment(db)
    old_date = datetime.utcnow() - timedelta(days=30)
    act_id = _insert_activity(db, test_user.id, data_source="gpx", started_at=old_date)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification
    effort = db.query(SegmentEffort).get(eff_id)

    detect_events(db, effort)

    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 1  # 手动上传永远触发
```

- [ ] **Step 2: 运行测试确认 FAIL**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/test_notification.py::test_detect_events_pr -v`
Expected: FAIL，ImportError

- [ ] **Step 3: 在 `segment/service.py` 新增共享排名函数**

在 `app/segment/service.py` 文件末尾追加：

```python
def get_effort_rank(db: Session, effort) -> int:
    """
    计算某条成绩在其赛段中的排名。

    共享函数——notification 模块和 segment 模块共用。
    排名规则：COUNT(同赛段中用时比我短的成绩) + 1。
    并列处理：同 elapsed_time 时按 created_at 先到先得。

    使用索引：idx_efforts_segment_time (segment_id, elapsed_time)
    """
    faster_count = (
        db.query(func.count(SegmentEffort.id))
        .filter(
            SegmentEffort.segment_id == effort.segment_id,
            sa.or_(
                SegmentEffort.elapsed_time < effort.elapsed_time,
                sa.and_(
                    SegmentEffort.elapsed_time == effort.elapsed_time,
                    SegmentEffort.created_at < effort.created_at,
                ),
            ),
        )
        .scalar()
    )
    return faster_count + 1
```

- [ ] **Step 4: 实现 `notification/service.py`**

```python
# app/notification/service.py
"""
通知业务逻辑——"广播室的工作人员"。

这个文件包含四个函数：
1. detect_events() — 检测事件并写通知（对外唯一写入接口）
2. get_notifications() — 查询通知列表
3. get_user_honors() — 查询用户荣誉表（KOM + 前十）
4. cleanup_expired() — 清理过期通知

操作注意事项：
- detect_events 必须用 try/except + SAVEPOINT 隔离，任何异常只记日志
- 不要在这里 import auto_match 或 import_scheduler（方向反了）
"""
import logging
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.notification.models import Notification
from app.notification.detector import classify
from app.segment.models import SegmentEffort, Segment
from app.segment.service import get_effort_rank
from app.activity.models import Activity
from app.user.models import User

logger = logging.getLogger(__name__)

# 通知保留天数
_NOTIFICATION_TTL_DAYS = 60
# Strava 历史导入跳过阈值
_STRAVA_HISTORY_DAYS = 7


def detect_events(db: Session, effort: SegmentEffort) -> None:
    """
    检测 PR/KOM 事件并写入通知表。

    这是 notification 模块暴露给外部的唯一写入接口。
    auto_match.py 和 import_scheduler.py 在赛段成绩 commit 后调用此函数。

    故障隔离：整个函数被 try/except 包裹，异常只记日志，不向上抛。
    幂等：UNIQUE(effort_id, event_type) 约束防重复，IntegrityError 静默跳过。
    """
    try:
        _detect_events_inner(db, effort)
    except Exception:
        logger.warning(
            "通知检测失败 effort_id=%s segment_id=%s",
            effort.id, effort.segment_id, exc_info=True,
        )
        # 回滚通知事务，不影响已 commit 的成绩
        db.rollback()


def _detect_events_inner(db: Session, effort: SegmentEffort) -> None:
    """detect_events 的内部实现，异常向上抛由外层捕获。"""
    # ---- 前置过滤：跳过 Strava 历史导入 ----
    activity = db.get(Activity, effort.activity_id)
    if activity is None:
        return

    if (activity.data_source == "strava"
            and activity.started_at is not None
            and activity.started_at < datetime.utcnow() - timedelta(days=_STRAVA_HISTORY_DAYS)):
        logger.debug(
            "跳过 Strava 历史活动通知 effort_id=%s activity_id=%s",
            effort.id, effort.activity_id,
        )
        return

    # ---- 查排名（共享函数）----
    rank = get_effort_rank(db, effort)

    # ---- 查 PR ----
    # 当前 effort 已 commit 入库，MIN 结果包含 effort 自身
    # 所以用 <=：best_time == effort.elapsed_time 时就是 PR
    best_time = (
        db.query(sa.func.min(SegmentEffort.elapsed_time))
        .filter(
            SegmentEffort.segment_id == effort.segment_id,
            SegmentEffort.user_id == effort.user_id,
        )
        .scalar()
    )
    is_pr = (effort.elapsed_time <= best_time) if best_time is not None else True

    # ---- 查原 KOM 持有者（仅 rank==1 时需要）----
    previous_kom_user_id = None
    if rank == 1:
        # 当前用户是第一名，第二名就是原来的 KOM 持有者
        second_place = (
            db.query(SegmentEffort.user_id)
            .filter(SegmentEffort.segment_id == effort.segment_id)
            .order_by(SegmentEffort.elapsed_time, SegmentEffort.created_at)
            .offset(1)
            .limit(1)
            .first()
        )
        if second_place is not None:
            previous_kom_user_id = second_place[0]

    # ---- 纯函数判定 ----
    event_result, kom_lost_result = classify(
        elapsed_time=effort.elapsed_time,
        rank=rank,
        is_pr=is_pr,
        previous_kom_user_id=previous_kom_user_id,
        current_user_id=effort.user_id,
    )

    if event_result is None:
        return  # 不是 PR，不生成通知

    # ---- 写入通知（SAVEPOINT 隔离）----
    expires_at = datetime.utcnow() + timedelta(days=_NOTIFICATION_TTL_DAYS)

    with db.begin_nested():
        # 当前用户的通知（PR 或 KOM）
        notif = Notification(
            user_id=effort.user_id,
            event_type=event_result.event_type,
            segment_id=effort.segment_id,
            activity_id=effort.activity_id,
            effort_id=effort.id,
            elapsed_time=effort.elapsed_time,
            rank=event_result.rank,
            expires_at=expires_at,
        )
        db.add(notif)

        try:
            db.flush()
        except IntegrityError:
            # 幂等：重复通知被 UNIQUE 约束拦住，静默跳过
            db.rollback()
            return

    db.commit()

    # KOM 被夺通知（独立 SAVEPOINT，一条失败不影响另一条）
    if kom_lost_result is not None:
        with db.begin_nested():
            lost_notif = Notification(
                user_id=kom_lost_result.previous_holder_user_id,
                event_type="kom_lost",
                segment_id=effort.segment_id,
                activity_id=effort.activity_id,
                effort_id=effort.id,
                elapsed_time=None,
                rank=kom_lost_result.new_rank,
                rival_user_id=effort.user_id,
                expires_at=expires_at,
            )
            db.add(lost_notif)

            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return

        db.commit()


def get_notifications(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询用户的通知列表，按时间倒序分页。"""
    now = datetime.utcnow()

    # 基础查询：JOIN 赛段名和对手昵称
    query = (
        db.query(
            Notification,
            Segment.name.label("segment_name"),
            User.nickname.label("rival_nickname"),
        )
        .join(Segment, Segment.id == Notification.segment_id)
        .outerjoin(User, User.id == Notification.rival_user_id)
        .filter(
            Notification.user_id == user_id,
            Notification.expires_at > now,
        )
        .order_by(Notification.created_at.desc())
    )

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for notif, segment_name, rival_nickname in rows:
        items.append({
            "id": notif.id,
            "event_type": notif.event_type,
            "segment_id": notif.segment_id,
            "segment_name": segment_name,
            "activity_id": notif.activity_id,
            "elapsed_time": notif.elapsed_time,
            "rank": notif.rank,
            "rival_user_id": notif.rival_user_id,
            "rival_nickname": rival_nickname,
            "created_at": notif.created_at.isoformat() + "Z" if notif.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_user_honors(db: Session, user_id: int) -> dict:
    """
    查询用户的 KOM 和前十名成绩。

    实时查询（不走 notifications 表），直接从 segment_efforts 用窗口函数算排名。
    一次查出所有赛段排名，零 N+1。
    """
    # 子查询：该用户有成绩的赛段 ID 列表
    user_segments = (
        db.query(SegmentEffort.segment_id)
        .filter(SegmentEffort.user_id == user_id)
        .distinct()
        .subquery()
    )

    # 窗口函数：所有成绩 + 排名
    rank_col = (
        sa.func.rank().over(
            partition_by=SegmentEffort.segment_id,
            order_by=[SegmentEffort.elapsed_time, SegmentEffort.created_at],
        )
    ).label("rank")

    ranked_query = (
        db.query(
            SegmentEffort.segment_id,
            Segment.name.label("segment_name"),
            SegmentEffort.user_id,
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.created_at,
            rank_col,
        )
        .join(Segment, Segment.id == SegmentEffort.segment_id)
        .filter(SegmentEffort.segment_id.in_(sa.select(user_segments.c.segment_id)))
        .subquery()
    )

    # 筛选：该用户 + 排名 ≤ 10
    results = (
        db.query(ranked_query)
        .filter(
            ranked_query.c.user_id == user_id,
            ranked_query.c.rank <= 10,
        )
        .order_by(ranked_query.c.rank, ranked_query.c.segment_name)
        .all()
    )

    koms = []
    top10s = []
    for row in results:
        entry = {
            "segment_id": row.segment_id,
            "segment_name": row.segment_name,
            "elapsed_time": row.elapsed_time,
            "avg_speed": row.avg_speed,
            "rank": row.rank,
            "achieved_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        }
        if row.rank == 1:
            koms.append(entry)
        else:
            top10s.append(entry)

    return {
        "koms": koms,
        "top10s": top10s,
        "kom_count": len(koms),
        "top10_count": len(top10s),
    }


def cleanup_expired(db: Session) -> int:
    """
    删除过期通知。由定时任务每天调用一次。
    返回删除的条数，供日志记录。
    """
    now = datetime.utcnow()
    count = (
        db.query(Notification)
        .filter(Notification.expires_at < now)
        .delete(synchronize_session=False)
    )
    db.commit()
    logger.info("清理过期通知 %d 条", count)
    return count
```

- [ ] **Step 5: 运行测试**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/test_notification.py -v`
Expected: 11 passed（7 纯函数 + 4 service）

- [ ] **Step 6: Commit**

```bash
git add app/notification/service.py app/segment/service.py tests/test_notification.py
git commit -m "feat(notification): 任务7.3 service 层 + 共享排名函数 + 11 个测试"
```

---

### Task 4: router.py — API 路由

**对应 spec**: 第 4 章

**Files:**
- Create: `app/notification/router.py`
- Modify: `app/main.py`

- [ ] **Step 1: 在 `tests/test_notification.py` 末尾追加 API 测试**

```python
# ===================== API 测试 =====================
# 追加到 tests/test_notification.py 末尾

def test_api_notifications_empty(client, auth_header):
    """通知列表为空时返回空数组"""
    resp = client.get("/api/notifications", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_api_notifications_with_data(client, db, test_user, auth_header):
    """通知列表包含数据时正确返回"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    effort = db.query(SegmentEffort).get(eff_id)
    detect_events(db, effort)

    resp = client.get("/api/notifications", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["event_type"] in ("pr", "kom")
    assert item["segment_name"] == "测试赛段"
    assert isinstance(item["elapsed_time"], int)


def test_api_honors_empty(client, auth_header):
    """荣誉表为空时返回空数组"""
    resp = client.get("/api/user/honors", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["koms"] == []
    assert data["top10s"] == []
    assert data["kom_count"] == 0
```

- [ ] **Step 2: 运行测试确认 FAIL**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/test_notification.py::test_api_notifications_empty -v`
Expected: FAIL（路由不存在，404）

- [ ] **Step 3: 实现 `router.py`**

```python
# app/notification/router.py
"""
通知模块 API 路由——"广播室的服务窗口"。

两个窗口：
1. /api/notifications — 通知列表（"最近有什么消息？"）
2. /api/user/honors — 荣誉表（"我有哪些 KOM 和前十？"）

操作注意事项：
- 两个路由前缀不同（/api/notifications 和 /api/user），所以需要两个 router 实例
- 和 segment 模块的 /api/user/efforts 是同一个挂载模式
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.user.models import User
from app.notification import service

# 通知列表路由
notification_router = APIRouter(prefix="/api/notifications", tags=["notification"])

# 荣誉表路由（挂在 /api/user 下）
honor_router = APIRouter(prefix="/api/user", tags=["notification"])


@notification_router.get("")
def get_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询当前用户的通知列表，按时间倒序分页。"""
    return service.get_notifications(db, user.id, page, page_size)


@honor_router.get("/honors")
def get_user_honors(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询当前用户的 KOM 和前十名荣誉表。"""
    return service.get_user_honors(db, user.id)
```

- [ ] **Step 4: 修改 `app/main.py` 注册路由**

在 `app/main.py` 现有的 `app.include_router(strava_router)` 之后，追加：

```python
from app.notification.router import notification_router, honor_router
app.include_router(notification_router)
app.include_router(honor_router)
```

- [ ] **Step 5: 运行全部测试**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/test_notification.py -v`
Expected: 14 passed

- [ ] **Step 6: 运行所有测试确认不破坏现有功能**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/ -v --tb=short`
Expected: 所有测试 PASS

- [ ] **Step 7: Commit**

```bash
git add app/notification/router.py app/main.py tests/test_notification.py
git commit -m "feat(notification): 任务7.4 API 路由(通知列表+荣誉表) + 3 个 API 测试"
```

---

### Task 5: auto_match + import_scheduler 衔接

**对应 spec**: 第 5 章

**Files:**
- Modify: `app/segment/auto_match.py:135-206`
- Modify: `app/strava/import_scheduler.py:348-357`

- [ ] **Step 1: 修改 `auto_match.py`**

在 `app/segment/auto_match.py` 中做两处改动：

**改动 1**：文件顶部 import 区域，添加：
```python
from app.notification.service import detect_events
```

**改动 2**：在 `match_activity_against_segments()` 函数中，循环开始前初始化列表，循环内收集 effort，commit 后逐个检测。

找到循环 `for segment, ref_wkt in candidates:` 之前，添加：
```python
    new_efforts = []  # 收集成功写入的 effort，commit 后逐个检测通知
```

找到循环内 `db.flush()` 之后，添加：
```python
            new_efforts.append(effort)
```

找到循环外 `db.commit()` 之后，添加：
```python
    # ---- 成绩已全部 commit，逐个检测 PR/KOM 事件 ----
    for effort in new_efforts:
        detect_events(db, effort)
```

- [ ] **Step 2: 修改 `import_scheduler.py`**

在 `app/strava/import_scheduler.py` 中做两处改动：

**改动 1**：在文件内已有的 `from app.segment.auto_match import match_activity_against_segments` 附近（约第 348 行），添加：
```python
from app.notification.service import detect_events
```

**改动 2**：在 `match_activity_against_segments(activity.id, db)` 调用之后（约第 350 行），追加通知检测。由于 import_scheduler 是逐活动处理的，匹配完成后查询该活动新增的 effort：

```python
            # 赛段匹配完成后，检测通知事件
            new_efforts = (
                db.query(SegmentEffort)
                .filter_by(activity_id=activity.id)
                .all()
            )
            for eff in new_efforts:
                detect_events(db, eff)
```

注意：需要在 import 区域添加 `from app.segment.models import SegmentEffort`（如果尚未导入）。

- [ ] **Step 3: 运行全部测试确认不破坏现有功能**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/ -v --tb=short`
Expected: 所有测试 PASS

- [ ] **Step 4: Commit**

```bash
git add app/segment/auto_match.py app/strava/import_scheduler.py
git commit -m "feat(notification): 任务7.5 auto_match + import_scheduler 衔接 detect_events"
```

---

### Task 6: 定时清理 + 集成测试

**对应 spec**: 第 3.6 节 + 第 6 章

**Files:**
- Modify: `tests/test_notification.py` — 追加清理和集成测试

- [ ] **Step 1: 追加清理和集成测试**

```python
# ===================== 清理 + 集成测试 =====================
# 追加到 tests/test_notification.py 末尾

def test_cleanup_expired(db, test_user):
    """过期通知被正确删除"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events, cleanup_expired
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification

    effort = db.query(SegmentEffort).get(eff_id)
    detect_events(db, effort)

    # 确认生成了通知
    assert db.query(Notification).count() >= 1

    # 手动把 expires_at 改到过去
    db.query(Notification).update(
        {"expires_at": datetime.utcnow() - timedelta(days=1)},
        synchronize_session=False,
    )
    db.commit()

    # 清理
    count = cleanup_expired(db)
    assert count >= 1
    assert db.query(Notification).count() == 0


def test_full_flow_pr_and_kom(db, test_user):
    """完整流程：两个用户，第二个拿 KOM，第一个收到被夺通知"""
    seg_id = _insert_segment(db)

    # 用户 1 先骑，成绩 300 秒（KOM）
    act1_id = _insert_activity(db, test_user.id)
    eff1_id = _insert_effort(db, seg_id, act1_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification

    effort1 = db.query(SegmentEffort).get(eff1_id)
    detect_events(db, effort1)

    # 用户 1 应收到 KOM 通知
    notifs1 = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs1) == 1
    assert notifs1[0].event_type == "kom"

    # 创建用户 2
    from app.user.models import User
    user2 = User(openid="test_user_2", nickname="对手")
    db.add(user2)
    db.commit()

    # 用户 2 骑更快，成绩 250 秒（夺 KOM）
    act2_id = _insert_activity(db, user2.id)
    eff2_id = _insert_effort(db, seg_id, act2_id, user2.id, 250)

    effort2 = db.query(SegmentEffort).get(eff2_id)
    detect_events(db, effort2)

    # 用户 2 应收到 KOM 通知
    user2_notifs = db.query(Notification).filter_by(user_id=user2.id).all()
    assert any(n.event_type == "kom" for n in user2_notifs)

    # 用户 1 应收到 KOM 被夺通知
    user1_notifs = db.query(Notification).filter_by(
        user_id=test_user.id, event_type="kom_lost"
    ).all()
    assert len(user1_notifs) == 1
    assert user1_notifs[0].rank == 2
    assert user1_notifs[0].rival_user_id == user2.id
```

- [ ] **Step 2: 运行全部通知测试**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/test_notification.py -v`
Expected: 16 passed

- [ ] **Step 3: 运行全部项目测试**

Run: `cd /Users/macbookair/Desktop/ridemap && python -m pytest tests/ -v --tb=short`
Expected: 所有测试 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_notification.py
git commit -m "feat(notification): 任务7.6 集成测试(完整流程+过期清理) 共 16 个测试"
```

---

## 完工检查清单

- [ ] 所有 6 个任务完成并 commit
- [ ] `python -m pytest tests/ -v` 全部 PASS
- [ ] 代码健康度检查：`wc -l app/notification/*.py`
- [ ] spec-v3.md 中的每个章节都有对应的任务覆盖
- [ ] 没有做 spec 以外的功能
