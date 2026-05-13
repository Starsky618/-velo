# 任务 7.1：Alembic 迁移 + 模型改动

> 根任务——所有其他任务的地基。**必须先完成**。

---

## 🎯 目标（一句话）

把第 4 期需要的 5 项数据库改动合并成**一个 Alembic 迁移文件**，同步更新对应的 SQLAlchemy 模型字段。

具体 5 项：
1. `notifications` 表加 `is_read` 字段（通知已读状态）+ 部分索引
2. `activities` 表加 `activity_type` 字段（多运动扩展种子）
3. `users` 表加 `mute_notifications` 字段（免打扰种子）
4. `strava_imports.updated_at`：改为带时区（`DateTime(timezone=True)`）
5. `notifications` 外键（`segment_id`、`activity_id`）：`CASCADE` → `SET NULL`

---

## ⛓ 前置依赖

**无**。这是根任务。

## 📥 输入契约

**无**。

## 📤 输出契约（其他任务会依赖的东西）

| 产出 | 用途 | 被谁依赖 |
|------|------|---------|
| `notifications.is_read` 字段 | 标记已读用 | task-7.8（mark_all_read）|
| `idx_notifications_user_unread` 部分索引 | unread_count 查询加速 | task-7.8 |
| `activities.activity_type` 字段 | 分流解析器 | task-7.7 |
| `users.mute_notifications` 字段 | 种子字段，本期前端不读写 | 未来扩展 |
| `strava_imports.updated_at` tz-aware | stalled 判定 | task-7.5 |
| `notifications` 外键 SET NULL | 活动/赛段删除后通知不跟着删 | task-7.10（前端兜底）|

---

## 🛠 完整代码

### 1. 新建 Alembic 迁移脚本

**路径**：`migrations/versions/phase4_frontend_consume.py`

```python
"""第 4 期迁移：前端反馈环闭合所需的 5 项 DB 改动。

修改点：
1. notifications 表加 is_read 字段 + 部分索引
2. activities 表加 activity_type 字段（多运动种子）
3. users 表加 mute_notifications 字段（免打扰种子）
4. strava_imports.updated_at 改成 TIMESTAMP WITH TIME ZONE
5. notifications 外键（segment_id/activity_id）改为 ON DELETE SET NULL

为什么 5 项合一个文件：
    这些改动互不干扰、属于同一业务主题，一次迁移可以原子性完成。
    若分成 5 个迁移文件会增加版本管理成本且没有隔离收益。

Revision ID: phase4_frontend_consume
Revises: phase3_notifications
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "phase4_frontend_consume"
down_revision = "phase3_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ========================================================
    # 改动 1：notifications 加 is_read 字段
    # ========================================================
    # 为什么 NOT NULL + 默认 FALSE：
    #   老通知（第 3 期产生的）要视为未读，让用户进通知页后一次性 mark-all-read
    op.add_column(
        "notifications",
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )

    # 部分索引：只索引未读 + 未过期的通知
    # 这是 unread_count 高频查询的支撑（task-7.8 用）
    # 部分索引的空间占用比全表索引小 10 倍以上（假设只有 5% 未读）
    op.create_index(
        "idx_notifications_user_unread",
        "notifications",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("is_read = FALSE"),
    )

    # ========================================================
    # 改动 2：activities 加 activity_type 字段（种子 1）
    # ========================================================
    # PostgreSQL 11+ 加列带 server_default 不会重写全表，
    # 老数据（33 条）自动获得默认值 'cycling'
    op.add_column(
        "activities",
        sa.Column(
            "activity_type",
            sa.String(20),
            nullable=False,
            server_default="cycling",
            comment="活动类型：cycling / running（预留）/ hiking（预留）",
        ),
    )

    # ========================================================
    # 改动 3：users 加 mute_notifications 字段（种子）
    # ========================================================
    # nullable：NULL 表示"未设置"，区别于 False（"已设置为不静音"）
    # 本期前端不读写这字段，仅作为未来跨设备同步留位
    op.add_column(
        "users",
        sa.Column(
            "mute_notifications",
            sa.Boolean(),
            nullable=True,
            comment="免打扰开关预留字段。本期仅字段存在，实际开关存前端本地",
        ),
    )

    # ========================================================
    # 改动 4：strava_imports.updated_at 改成 timezone-aware
    # ========================================================
    # 为什么必改：task-7.5 stalled 判定用 datetime.now(UTC) - imp.updated_at
    # 当前 updated_at 是 naive datetime，与 aware datetime 相减会抛 TypeError
    # 迁移策略：用 AT TIME ZONE 'UTC' 把现有值解释为 UTC
    op.alter_column(
        "strava_imports",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
    )

    # ========================================================
    # 改动 5：notifications 外键改成 ON DELETE SET NULL
    # ========================================================
    # 当前：segment_id NOT NULL + CASCADE，activity_id NULLABLE + CASCADE
    # 期望：两个都 NULLABLE + SET NULL
    # 业务动机：赛段或活动被删时，通知记录保留（可显示"该记录已失效"），不连带删除
    #
    # PostgreSQL 外键自动命名规则：<table>_<column>_fkey
    # 现有约束名：notifications_segment_id_fkey / notifications_activity_id_fkey

    # Step 5.1：先 drop 现有外键
    op.drop_constraint("notifications_segment_id_fkey", "notifications", type_="foreignkey")
    op.drop_constraint("notifications_activity_id_fkey", "notifications", type_="foreignkey")

    # Step 5.2：segment_id 改成 nullable（activity_id 本来就是 nullable，不动）
    op.alter_column("notifications", "segment_id", nullable=True)

    # Step 5.3：重建外键 with ON DELETE SET NULL
    op.create_foreign_key(
        "notifications_segment_id_fkey",
        "notifications", "segments",
        ["segment_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "notifications_activity_id_fkey",
        "notifications", "activities",
        ["activity_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # ---- 改动 5 回滚 ----
    op.drop_constraint("notifications_segment_id_fkey", "notifications", type_="foreignkey")
    op.drop_constraint("notifications_activity_id_fkey", "notifications", type_="foreignkey")
    op.alter_column("notifications", "segment_id", nullable=False)
    op.create_foreign_key(
        "notifications_segment_id_fkey",
        "notifications", "segments",
        ["segment_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "notifications_activity_id_fkey",
        "notifications", "activities",
        ["activity_id"], ["id"],
        ondelete="CASCADE",
    )

    # ---- 改动 4 回滚 ----
    op.alter_column(
        "strava_imports",
        "updated_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
    )

    # ---- 改动 3 回滚 ----
    op.drop_column("users", "mute_notifications")

    # ---- 改动 2 回滚 ----
    op.drop_column("activities", "activity_type")

    # ---- 改动 1 回滚 ----
    op.drop_index("idx_notifications_user_unread", table_name="notifications")
    op.drop_column("notifications", "is_read")
```

### 2. 改 `app/notification/models.py`

找到 `Notification` 类的字段定义末尾，**加一行** `is_read`：

```python
# 在现有字段 expires_at / created_at 附近添加
is_read = Column(
    Boolean,
    nullable=False,
    server_default="false",
    comment="是否已读。用户进通知列表页后由 mark-all-read 接口置 true",
)
```

### 3. 改 `app/activity/models.py`

找到 `Activity` 类字段定义末尾，**加一行** `activity_type`：

```python
# 在 data_source 字段附近添加
activity_type = Column(
    String(20),
    nullable=False,
    server_default="cycling",
    comment="活动类型：cycling（骑行）/ running（预留）/ hiking（预留）",
)
```

### 4. 改 `app/user/models.py`

找到 `User` 类字段定义末尾（`updated_at` 之前），**加一行** `mute_notifications`：

```python
# 在 strava_token_expires_at 字段之后，created_at 之前
mute_notifications = Column(
    Boolean,
    nullable=True,
    comment="免打扰开关预留字段。本期仅字段存在，实际开关存前端本地",
)
```

### 5. 改 `app/strava/models.py`

找到 `StravaImport` 类的 `updated_at` 定义，**改为带时区**：

```python
# 原：updated_at = Column(DateTime, ...)
# 改为：
updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
)
```

---

## 🧪 测试

### 测试 1：迁移可正向、反向、再正向执行（本地）

```bash
# 假设已在开发环境
cd ~/velo

# 正向
sudo docker compose exec api python3 -m alembic upgrade head
# 应看到：INFO ... Running upgrade phase3_notifications -> phase4_frontend_consume

# 反向
sudo docker compose exec api python3 -m alembic downgrade phase3_notifications
# 应看到：INFO ... Running downgrade phase4_frontend_consume -> phase3_notifications

# 再正向（验证幂等）
sudo docker compose exec api python3 -m alembic upgrade head
```

### 测试 2：老数据自动回填验证

```bash
# 进 DB 检查 33 条老活动都自动获得 activity_type='cycling'
sudo docker compose exec db psql -U velo -d velo -c \
  "SELECT COUNT(*) FROM activities WHERE activity_type='cycling';"
# 应返回 33（或更多，看 Strava 导入）
```

### 测试 3：部分索引验证

```bash
sudo docker compose exec db psql -U velo -d velo -c "\d notifications"
# 应看到 idx_notifications_user_unread 这一行
```

### 测试 4：外键 SET NULL 行为验证

```bash
# 手动造数据：插一条通知、删对应赛段、看通知是否还在（segment_id 变 NULL）
sudo docker compose exec db psql -U velo -d velo <<EOF
-- 假设已有测试赛段 id=999
INSERT INTO notifications (user_id, event_type, segment_id, effort_id, elapsed_time, rank, expires_at, is_read)
VALUES (1, 'pr', 999, 1, 100, 5, NOW() + INTERVAL '7 days', false)
RETURNING id;
-- 删赛段
DELETE FROM segments WHERE id=999;
-- 查通知是否还在、segment_id 是否变 NULL
SELECT id, segment_id FROM notifications WHERE user_id=1 ORDER BY id DESC LIMIT 1;
EOF
# 应看到通知记录还在，segment_id 为 NULL
```

---

## 📦 Commit 指令

```bash
git add migrations/versions/phase4_frontend_consume.py \
        app/notification/models.py \
        app/activity/models.py \
        app/user/models.py \
        app/strava/models.py

git commit -m "$(cat <<'EOF'
feat(db): 任务 7.1 第4期迁移 — notifications.is_read + activity_type + mute_notifications + updated_at tz + 外键 SET NULL

五项改动合一个迁移：
- notifications.is_read（BOOL NOT NULL DEFAULT false）+ 部分索引
- activities.activity_type（VARCHAR(20) NOT NULL DEFAULT 'cycling'，多运动种子）
- users.mute_notifications（BOOL NULL，免打扰种子字段）
- strava_imports.updated_at: naive → timezone=True（配合 task-7.5 stalled 判定）
- notifications 外键 segment_id/activity_id: CASCADE → SET NULL

老数据自动回填：33 条 activity 的 activity_type 自动为 'cycling'。
upgrade/downgrade 本地验证通过。
EOF
)"
```

---

## ✅ 自检三问（完工前必答）

**1. 10 分钟挑战**：我能不能用 10 分钟给陌生人讲清这次迁移做了什么？

> 能。"给 notification 加已读标记字段 + 给 activity 加运动类型字段 + 给 user 加免打扰字段 + 让 strava_imports 的 updated_at 带时区 + 让通知外键不跟着删"——五件事，每件一句话讲清楚。

**2. 崩溃场景审视**：如果迁移跑到一半崩了，系统处于什么状态？

> Alembic 自动把整个 upgrade() 包在一个事务里，中途任何一步失败会 ROLLBACK，回到 phase3 状态。**唯一例外**：PostgreSQL DDL 在事务中基本都能回滚，但如果 server 崩溃（硬件级）可能留下 alembic_version 表错位。应对：生产部署前本地验证一次 upgrade/downgrade/upgrade。

**3. 边界纪律检查**：我有没有做 spec 没要求的"顺手优化"？

> 没有。严格限定在 spec §1.1~§1.5 的 5 项改动。没有顺手给其他表加索引、没有改字段名、没有修改任何老数据（除了 server_default 自动回填）。
