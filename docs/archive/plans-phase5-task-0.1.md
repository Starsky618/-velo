# 任务 0.1：datetime 全局 tz-aware

> **Sprint 0 根任务**——Sprint 1+ 所有业务代码（§3.3 / §3.4 / §3.6）假设 DB DateTime 列已 tz-aware，未先跑这个 task **直接跑业务代码会触发陷阱 #2 TypeError**（naive vs aware 比较）。

---

## 🎯 目标（一句话）

把项目里**所有 DateTime 字段**从 naive 改为 tz-aware（timezone=True），**所有 Python 端 `datetime.utcnow()`** 改为 `datetime.now(timezone.utc)`，写一份独立 alembic revision 落地。

---

## ⛓ 前置依赖

**无**。Sprint 0 内最先做。

## 📥 输入契约

无。

## 📤 输出契约（其他任务依赖什么）

| 产出 | 用途 | 被谁依赖 |
|------|------|---------|
| 5 张表 7 列 DateTime 改 `timezone=True` | DB 层 tz-aware | task-0.6 v5 主迁移依赖此 revision |
| Python 端 `datetime.now(timezone.utc)` 统一 | 防陷阱 #2 | Sprint 1+ 所有业务（§3.3 / §3.4 / §3.6） |
| migrations/versions/phase5_tz_aware.py | 数据库迁移 | task-0.6 down_revision 指向它 |

---

## 🧱 现状清单（subagent 必先 Read 验证后再动手）

### 数据库列（5 张表 7 列待迁，已 grep 验证）

| 表 | 列 | 现状 file:line |
|----|----|--------------|
| activities | started_at | `app/activity/models.py:85` `Column(DateTime, nullable=True)` |
| activities | finished_at | `app/activity/models.py:86` `Column(DateTime, nullable=True)` |
| activities | created_at | `app/activity/models.py:126` `Column(DateTime, server_default=func.now())` |
| activities | updated_at | `app/activity/models.py:127` `Column(DateTime, server_default=func.now(), onupdate=func.now())` |
| trackpoints | timestamp | `app/activity/models.py:176` `Column(DateTime, nullable=True)` |
| segments | created_at | `app/segment/models.py:69` `Column(DateTime, server_default=func.now())` |
| segment_efforts | created_at | `app/segment/models.py:113` `Column(DateTime, server_default=func.now())` |
| notifications | expires_at | `app/notification/models.py:85` `Column(DateTime, nullable=False)` |
| notifications | created_at | `app/notification/models.py:86` `Column(DateTime, server_default=func.now())` |
| users | created_at | `app/user/models.py:92` `Column(DateTime, server_default=func.now())` |
| users | updated_at | `app/user/models.py:93` `Column(DateTime, server_default=func.now(), onupdate=func.now())` |
| strava_imports | created_at | `app/strava/models.py:76` `Column(DateTime, server_default=func.now())` |

> **不动的列**（已经是 tz-aware，跳过）：
> - `app/strava/models.py:67` `cursor_before = Column(DateTime(timezone=True), nullable=True)` ✅
> - `app/strava/models.py` `updated_at` 已 tz-aware（v4 task-7.1 改过）✅
> - `app/user/models.py:79` `strava_token_expires_at = Column(DateTime(timezone=True), nullable=True)` ✅

合计 **12 列待迁**（5 张表）。

### Python 端 `datetime.utcnow()` 用法（4 文件待改）

| 文件 | 位置 | 用法 |
|------|------|------|
| `app/notification/service.py:71` | `activity.started_at < datetime.utcnow() - timedelta(days=...)` | 比较 |
| `app/notification/service.py:124` | `expires_at = datetime.utcnow() + timedelta(days=...)` | 计算 |
| `app/notification/service.py:202` | `now = datetime.utcnow()` | 取当前 |
| `app/notification/service.py:353` | `now = datetime.utcnow()` | 取当前 |
| `tests/test_mark_all_read.py` | grep 出多处 | 测试 |
| `tests/test_notification.py` | grep 出多处 | 测试 |

> `app/activity/service.py:310` 已是 `datetime.now(timezone.utc)`（注释明写"替代已弃用"）✅

---

## 🛠 完整代码

### 1. 新建 Alembic 迁移

**路径**：`migrations/versions/phase5_tz_aware.py`

```python
"""第 5 期 Sprint 0 task 0.1：12 列 DateTime → timezone=True。

为什么 12 列合一份迁移：
    所有列都属同一性质改动（naive → tz-aware UTC），合并迁移降低版本管理成本。
    不影响业务逻辑（值域不变，只加时区元数据）。

陷阱 #7（Alembic alter_column 类型转换）：
    naive 改 tz-aware 必须 postgresql_using="<col> AT TIME ZONE 'UTC'"
    否则 PG 会报 "column cannot be cast automatically"。
    含义：把现有 naive 值视为 UTC，加上 +00 时区标记。

Revision ID: phase5_tz_aware
Revises: phase4_frontend_consume
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa


revision = "phase5_tz_aware"
down_revision = "phase4_frontend_consume"
branch_labels = None
depends_on = None


# 待迁列清单（5 表 12 列）
COLUMNS_TO_TZ_AWARE = [
    ("activities", "started_at"),
    ("activities", "finished_at"),
    ("activities", "created_at"),
    ("activities", "updated_at"),
    ("trackpoints", "timestamp"),
    ("segments", "created_at"),
    ("segment_efforts", "created_at"),
    ("notifications", "expires_at"),
    ("notifications", "created_at"),
    ("users", "created_at"),
    ("users", "updated_at"),
    ("strava_imports", "created_at"),
]


def upgrade() -> None:
    """naive → tz-aware：把现有值当 UTC 处理，加 +00 时区标记。"""
    for table, col in COLUMNS_TO_TZ_AWARE:
        op.alter_column(
            table,
            col,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{col} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """tz-aware → naive：丢弃时区元数据，保留值（按 UTC 解读）。"""
    for table, col in COLUMNS_TO_TZ_AWARE:
        op.alter_column(
            table,
            col,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{col} AT TIME ZONE 'UTC'",
        )
```

### 2. 改 SQLAlchemy 模型（5 文件）

#### `app/activity/models.py`

```diff
- started_at = Column(DateTime, nullable=True)      # 骑行开始时间
- finished_at = Column(DateTime, nullable=True)     # 骑行结束时间
+ started_at = Column(DateTime(timezone=True), nullable=True)   # 骑行开始时间（UTC）
+ finished_at = Column(DateTime(timezone=True), nullable=True)  # 骑行结束时间（UTC）

  # ...

- created_at = Column(DateTime, server_default=func.now())
- updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
+ created_at = Column(DateTime(timezone=True), server_default=func.now())
+ updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

  # ...（Trackpoint 类）

- timestamp = Column(DateTime, nullable=True)
+ timestamp = Column(DateTime(timezone=True), nullable=True)
```

#### `app/segment/models.py`

```diff
  # Segment 类
- created_at = Column(DateTime, server_default=func.now())
+ created_at = Column(DateTime(timezone=True), server_default=func.now())

  # SegmentEffort 类
- created_at = Column(DateTime, server_default=func.now())
+ created_at = Column(DateTime(timezone=True), server_default=func.now())
```

#### `app/notification/models.py`

```diff
- expires_at = Column(DateTime, nullable=False)
- created_at = Column(DateTime, server_default=func.now(), nullable=False)
+ expires_at = Column(DateTime(timezone=True), nullable=False)
+ created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

#### `app/user/models.py`

```diff
- created_at = Column(DateTime, server_default=func.now())
- updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
+ created_at = Column(DateTime(timezone=True), server_default=func.now())
+ updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

#### `app/strava/models.py`

```diff
- created_at = Column(DateTime, server_default=func.now())
+ created_at = Column(DateTime(timezone=True), server_default=func.now())
```

### 3. 改 Python 端 `datetime.utcnow()`（4 处全替换）

#### `app/notification/service.py`

```diff
- from datetime import datetime, timedelta
+ from datetime import datetime, timedelta, timezone

  # 行 71
- and activity.started_at < datetime.utcnow() - timedelta(days=_STRAVA_HISTORY_DAYS)):
+ and activity.started_at < datetime.now(timezone.utc) - timedelta(days=_STRAVA_HISTORY_DAYS)):

  # 行 124
- expires_at = datetime.utcnow() + timedelta(days=_NOTIFICATION_TTL_DAYS)
+ expires_at = datetime.now(timezone.utc) + timedelta(days=_NOTIFICATION_TTL_DAYS)

  # 行 202
- now = datetime.utcnow()
+ now = datetime.now(timezone.utc)

  # 行 353
- now = datetime.utcnow()
+ now = datetime.now(timezone.utc)
```

#### 测试文件改动

`tests/test_mark_all_read.py` / `tests/test_notification.py`：把所有 `datetime.utcnow()` 改 `datetime.now(timezone.utc)`，import 加 `timezone`。**测试断言里的时间比较跟着 aware 化**——SQLite 在测试里也支持 tz-aware DateTime（pytest fixture 已配置）。

---

## ✅ 测试

### 单元测试（必跑）

```bash
cd /Users/macbookair/Desktop/velo
python3 -m pytest tests/ -x -q
```

预期：所有现有测试 passed。**陷阱**：测试里若有"naive 跟 aware 比较"立刻 TypeError——这就是本 task 要修的目标。

### 迁移验证（必跑）

```bash
# 本地 docker 起 PG（按项目 docker-compose.yml）
sudo docker compose up -d db
sudo docker compose exec api python3 -m alembic upgrade head
sudo docker compose exec api python3 -m alembic downgrade phase4_frontend_consume
sudo docker compose exec api python3 -m alembic upgrade head
```

预期：upgrade / downgrade 双向跑通无错。

### 数据完整性验证

```sql
-- 在 PG 里验证迁移后值不变（按 UTC 解读应一致）
SELECT id, started_at FROM activities ORDER BY id LIMIT 5;
-- 期望：原本 '2026-04-15 03:00:00' → '2026-04-15 03:00:00+00'
```

---

## 📝 commit 指令

```bash
git add app/activity/models.py app/segment/models.py app/notification/models.py \
        app/user/models.py app/strava/models.py app/notification/service.py \
        tests/test_mark_all_read.py tests/test_notification.py \
        migrations/versions/phase5_tz_aware.py
git commit -m "$(cat <<'EOF'
chore(db): 任务 0.1 datetime 全局 tz-aware

- 12 列 DateTime → timezone=True (5 表)：activities × 4 / trackpoints × 1 /
  segments × 1 / segment_efforts × 1 / notifications × 2 / users × 2 / strava_imports × 1
- 4 处 datetime.utcnow() → datetime.now(timezone.utc) (notification.service + 测试)
- 新建 migrations/versions/phase5_tz_aware.py (postgresql_using="col AT TIME ZONE 'UTC'")

为什么必须先做：
Sprint 1+ 业务代码 (§3.3 power_curve / §3.4 progress detector / §3.6 看他人主页)
假设 DB DateTime 列已 tz-aware，未迁前直接跑会触发陷阱 #2 naive vs aware TypeError。

测试：pytest 全 passed / alembic upgrade+downgrade 双向跑通 / 数据值无变化（UTC 解读一致）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 🔍 自检三问（不答满意不交付）

1. **崩溃恢复**：迁移跑到一半进程被 kill → 数据处于什么状态？能 `alembic current` 看到中间态吗？能 downgrade 回干净 phase4 状态吗？  
   → 答：alembic 单 revision 内 op.alter_column 是单事务，DDL 失败整体回滚。**已验证**：本地 docker 跑 upgrade / downgrade 双向。

2. **陷阱核查**：Python 代码里还有 `datetime.utcnow()` / `datetime.now()`（无 tz）残留吗？  
   → 用 `grep -rn "datetime\.utcnow\|datetime\.now()" app/ tests/` 验证应**全为 0 hits**。

3. **下游波及**：本 task 改完后，Sprint 0 内其他 task（0.2-0.8）会被影响吗？Sprint 1+ 业务代码假设的字段是否都迁了（特别是 §3.3 用的 `Activity.started_at` / §3.4 用的 `Activity.created_at` / §3.6 用的 `Notification.created_at`）？  
   → 答：本 task 列出的 12 列覆盖 spec §0.1 事实表所有引用点。Sprint 0 其他 task（迁移 / queue 等）不读 DateTime 字段，不受影响。
