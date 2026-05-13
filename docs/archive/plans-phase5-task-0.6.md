# 任务 0.6：v5 主迁移（新字段 + 新表）

## 🎯 目标

写 + 跑 v5 主 alembic revision，落地：
- `segments` 加 3 字段（difficulty / max_gradient / city）
- `users` 加 1 字段（city）
- `notifications` 加 payload JSONB 字段 + event_type CHECK 扩展
- 新建 2 张表（segment_ai_drafts / segment_curation_pool）
- 新建 1 个索引（idx_segments_city_difficulty）

## ⛓ 前置依赖

**task-0.1（tz-aware revision 必先做）**——本 revision down_revision 指向 phase5_tz_aware。

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| migrations/versions/phase5_v5_db_changes.py | 主迁移 revision |
| segments 3 新字段 | Sprint 1 segment 模块依赖 |
| users.city | Sprint 2 user 模块 + 5.A.1 热图依赖 |
| notifications.payload | Sprint 2 progress detector 写入 |
| 2 新表 | Sprint 1/3 agent + admin 模块依赖 |

## 🧱 现状

完整 alembic 脚本见 `docs/spec-v5.md §2.5`（行 308 起）—— spec 内已有完整 upgrade / downgrade 实现。本 task 只是**把 spec §2.5 抄成 migrations/versions/phase5_v5_db_changes.py**，不需要再设计 schema。

## 🛠 完整代码

### `migrations/versions/phase5_v5_db_changes.py`

```python
"""第 5 期主迁移：B/C/A/D 主轴的所有 schema 改动。

修改点：
1. segments 加 difficulty / max_gradient / city（防火墙破例 3 处）
2. users 加 city（防火墙破例 1 处）
3. notifications 加 payload JSONB（progress detector 写）
4. notifications.event_type CHECK 扩展（加 progress_segment_pb / progress_5min_power）
5. 新建 segment_ai_drafts 表（5.B.2 + 5.D.2）
6. 新建 segment_curation_pool 表（5.D.1）
7. 新建索引 idx_segments_city_difficulty

为什么 7 项合一份迁移：
    所有改动属同一期（v5）业务主题，原子性落地。
    分多份会增加版本管理成本且无隔离收益。

Revision ID: phase5_v5_db_changes
Revises: phase5_tz_aware
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "phase5_v5_db_changes"
down_revision = "phase5_tz_aware"
branch_labels = None
depends_on = None


# === 完整 upgrade / downgrade 实现见 docs/spec-v5.md §2.5 ===
# subagent 实施时直接抄 spec §2.5 行 308 起的代码块到本文件。
# 包括：
# - segments 3 字段 add_column + CheckConstraint + idx_segments_city_difficulty
# - users.city add_column + CheckConstraint
# - notifications 加 payload + event_type CHECK 扩展（drop 旧 add 新）
# - segment_ai_drafts create_table（含 FK ondelete CASCADE/SET NULL + UniqueConstraint segment_id + 5 字段 + status CheckConstraint + idx_ai_drafts_status）
# - segment_curation_pool create_table（含 FK + UniqueConstraint + 字段 + idx_curation_pool_*）

def upgrade() -> None:
    # 抄 spec §2.5 upgrade()
    pass


def downgrade() -> None:
    # 抄 spec §2.5 downgrade()
    pass
```

> **subagent 实施步骤**：
> 1. Read `docs/spec-v5.md` 行 308-460 （§2.5 完整实现）
> 2. 把 upgrade / downgrade 函数体抄进上面文件
> 3. 跑 `alembic upgrade head` + `alembic downgrade phase5_tz_aware` 双向验证

### 同步更新 `app/segment/models.py` / `app/user/models.py` / `app/notification/models.py`

完整 ORM 类定义见 `docs/spec-v5.md §2.2.3`（行 187 起 SegmentAiDraft + SegmentCurationPool 类）+ 各表 add_column 对应字段。

> 模型变更**必须与迁移同 commit**——alembic 跟 model 失步会触发 sqlalchemy 启动 schema 校验告警。

## ✅ 测试

### 迁移双向跑

```bash
sudo docker compose exec api python3 -m alembic upgrade head
sudo docker compose exec api python3 -m alembic downgrade phase5_tz_aware
sudo docker compose exec api python3 -m alembic upgrade head
```

预期：upgrade / downgrade 都跑通。downgrade 后 segments 表无 difficulty / max_gradient / city，2 新表消失。

### 模型字段加载验证

```bash
python3 -c "from app.segment.models import Segment, SegmentAiDraft, SegmentCurationPool; print(Segment.__table__.columns.keys())"
```

预期：包含 `difficulty / max_gradient / city`。

### 数据完整性

```sql
INSERT INTO segments(name, distance, reference_line, ...) VALUES (...);
SELECT difficulty, city FROM segments WHERE id = LASTVAL();
-- 期望：difficulty='medium' / city='unknown'（server_default）
```

## 📝 commit

```
feat(db): 任务 0.6 v5 主迁移（segments + users + notifications + 2 新表）

phase5_v5_db_changes revision：
- segments + difficulty/max_gradient/city（防火墙破例 3）
- users + city（防火墙破例 1）
- notifications + payload JSONB + event_type CHECK 扩展
- segment_ai_drafts / segment_curation_pool 2 新表
- idx_segments_city_difficulty / idx_ai_drafts_status / idx_curation_pool_*

down_revision = phase5_tz_aware（task 0.1）
对应 ORM 模型类同步更新（spec §2.2.3）
```

## 🔍 自检三问

1. **崩溃恢复**：upgrade 跑到 create_table 第 5 步崩 → 表 1-4 已建，表 5 没建。alembic 会怎样？  
   → alembic 单 revision 内 DDL 是单事务，PG 自动回滚整体——不会留中间态。

2. **陷阱核查**：notifications.event_type CHECK 扩展（drop 旧 add 新）有没有破坏现有数据？  
   → spec §2.3 用 DO $$ EXCEPTION 块 + drop_constraint('ck_...') if exists；现有数据值（pr/kom/kom_lost）都在新值集内不受影响。

3. **下游波及**：Sprint 1 启动前 task 0.7 老数据回填没跑，新字段 server_default 兜底吗？  
   → segments.difficulty default 'medium' / segments.city default 'unknown'：所有现有 220 条 segment 自动有合法值，Sprint 1 业务代码读到的是 default 不是 NULL。task 0.7 把 default 替换成更精确的算法值。
