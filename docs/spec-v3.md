# RIDEMAP v3 技术规格文档 — 事件通知系统

> 本文档为第 3 期开发参考。前置条件：第 0~2 期已完成并部署。
> 设计目标：补全核心反馈环中"推"的能力——用户破 PR、拿 KOM 时主动通知，
> KOM 被夺时提醒原持有者，让用户不用主动翻排行榜就能感知自己的进步和竞争。
>
> **设计决策记录（2026-04-16，Starsky 确认）：**
> - 事件类型：PR（个人最佳）+ KOM（赛段王）+ KOM 被夺，共 3 种
> - 通知渠道：App 内通知中心（微信推送未来加，数据模型已预留）
> - 聚合策略：后端存原子事件，前端按 activity_id 分组展示
> - 检测时机：写入 SegmentEffort 后实时检测（方案 B：事件层分离）
> - 生命周期：保存 60 天自动清理，无已读/未读状态
> - PR 排名规则：rank ≤ 10 时返回具体排名，rank > 10 时返回 null（前端只显示"新 PR"）
> - 附加功能：用户个人 KOM/前十 荣誉表（实时查询，非通知快照）
> - Strava 历史导入不触发通知：data_source='strava' 且 started_at 超过 7 天的活动静默处理

---

## 0. 架构总览

### 设计原则

1. **最小接口衔接**：notification 模块通过一个函数 `detect_events()` 与 auto_match 衔接，模块内部完全自治
2. **单向依赖**：notification 读 SegmentEffort 数据，但 segment 模块不知道 notification 的存在
3. **成绩优先**：SegmentEffort 先 commit，通知后 commit——通知写入失败不影响成绩记录
4. **故障隔离**：detect_events 用 SAVEPOINT + try/except 包裹，任何异常只记日志，不向上抛
5. **幂等安全**：同一条 effort 重复调用 detect_events，不会产生重复通知

### 数据流全景

```
赛段匹配完成（现有系统）              通知层（新增）                    前端（新增）
========================          ================              ================

auto_match.py
  写入 SegmentEffort ──→ commit
                          │
                          ▼
               detect_events(db, effort)
                          │
                     ┌────┴────┐
                     ▼         ▼
                查排名      查 PR
              (COUNT SQL) (MIN SQL)
                     │         │
                     └────┬────┘
                          ▼
              detector.classify()  ← 纯函数
                (rank, is_pr, ...)
                          │
                     ┌────┼────┐
                     ▼    ▼    ▼
                   [PR] [KOM] [KOM被夺]
                     │    │    │
                     ▼    ▼    ▼
              写入 notifications 表 ──→ commit
                                          │
                                          ▼
                                GET /api/notifications ──→ 通知中心页面
                                GET /api/user/honors   ──→ 个人荣誉表
```

### 新增项目结构

```
app/
├── notification/                   # 通知模块（新增）
│   ├── __init__.py                 # 模块说明
│   ├── models.py                   # ORM：Notification 表
│   ├── detector.py                 # 纯函数：事件分类判定
│   ├── service.py                  # 业务逻辑：检测、查询、清理
│   └── router.py                   # API 路由：通知列表、荣誉表
│
├── segment/
│   └── auto_match.py               # 小改：匹配完成后调用 detect_events
│
└── main.py                         # 小改：注册 notification router
```

### 模块依赖方向（单向，禁止反向 import）

```
notification/detector.py    ← 纯函数，不 import 任何项目模块
notification/models.py      ← import database.Base（同其他模块）
notification/service.py     ← import notification/detector, notification/models
                            ← import segment/models.SegmentEffort（只读查询）
                            ← import segment/service.get_effort_rank（共享排名计算）
                            ← import activity/models.Activity（前置过滤查 data_source）
                            ← import user/models.User（JOIN 查昵称）
notification/router.py      ← import notification/service

segment/auto_match.py       ← import notification/service.detect_events（衔接点）
strava/import_scheduler.py  ← import notification/service.detect_events（衔接点）
```

**禁止的方向**：notification 不 import segment/auto_match，segment 不 import notification 的任何东西。
**共享逻辑**：排名计算 `get_effort_rank()` 放在 segment/service.py，notification 和 segment 共用，避免重复。

---

## 1. 数据模型（models.py）

### 1.1 Notification 表

```python
class Notification(Base):
    """
    通知记录表——"广播室的公告栏"。
    
    每条记录是一个原子事件：某用户在某赛段发生了某件事（破 PR / 拿 KOM / KOM 被夺）。
    前端拿到列表后按 activity_id 分组聚合展示。
    
    这是历史快照——记录的是事件发生那一刻的状态（排名、用时），
    不会因为后续排名变化而更新。
    """
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # 事件类型：pr / kom / kom_lost
    event_type = Column(String(20), nullable=False)
    
    # 关联实体
    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="CASCADE"), nullable=False)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=True)
    effort_id = Column(Integer, ForeignKey("segment_efforts.id", ondelete="SET NULL"), nullable=True)
    
    # 事件快照数据（类型与 SegmentEffort.elapsed_time 一致，均为 Integer 秒）
    elapsed_time = Column(Integer, nullable=True)       # 成绩用时（秒）。kom_lost 时为 null
    rank = Column(Integer, nullable=True)               # 排名。PR 且 rank>10 时为 null
    
    # KOM 被夺时的对手信息
    rival_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # 生命周期
    expires_at = Column(DateTime, nullable=False)       # created_at + 60 天
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    __table_args__ = (
        # 防重复通知：同一条成绩不重复生成同类型通知
        UniqueConstraint("effort_id", "event_type", name="uq_notif_effort_type"),
        # 通知列表查询：按用户 + 时间倒序
        Index("idx_notif_user_created", "user_id", "created_at"),
        # 过期清理
        Index("idx_notif_expires", "expires_at"),
        # 事件类型约束
        CheckConstraint("event_type IN ('pr', 'kom', 'kom_lost')", name="ck_notif_event_type"),
    )
```

### 1.2 设计决策说明

| 决策 | 理由 |
|------|------|
| `effort_id` 用 `ON DELETE SET NULL` | 成绩被删后通知保留（但看不到详情），60 天后自然过期。避免 CASCADE 导致他人通知意外消失 |
| `rival_user_id` 用 `ON DELETE SET NULL` | 对手注销后通知保留，只是不显示对手名字 |
| `activity_id` 用 `ON DELETE CASCADE` | 活动删除 → 该活动产生的所有通知一起删（合理：活动都没了，通知也没意义） |
| 冗余存 `elapsed_time` 和 `rank` | 通知是历史快照，不应随后续排名变化而改变 |
| `UniqueConstraint("effort_id", "event_type")` | 幂等防护：Worker 重试时 detect_events 被重复调用也不会产生重复通知。注意：SQL 标准中 NULL 不等于 NULL，effort_id 被 SET NULL 后约束失效，但此时不会再有重复调用场景，安全 |
| `Notification` 无状态字段 | 写入后不可变，60 天后清理。如果未来需要已读/未读，加列即可（第 9 章已预留） |

### 1.3 Alembic 迁移要点

- 新建 `notifications` 表（纯新建，不涉及已有表修改，迁移风险低）
- 4 个外键 + 3 个索引 + 1 个 UNIQUE + 1 个 CHECK
- 现有索引已满足新查询需求（排名查 `idx_efforts_segment_time`，PR 查 `idx_efforts_segment_user_time`），无需新增赛段成绩表索引
- 无历史数据需要迁移

---

## 2. 事件检测逻辑（detector.py）

### 2.1 纯函数：classify()

```python
@dataclass(frozen=True)
class EventResult:
    """
    检测结果——"裁判的判定书"。
    
    一次成绩最多产生两个事件：自己的（PR 或 KOM）+ 被夺者的（kom_lost）。
    """
    event_type: str             # 'pr' | 'kom'
    rank: int | None            # ≤10 时填值，>10 时 None
    
@dataclass(frozen=True)
class KomLostResult:
    """KOM 被夺事件。"""
    previous_holder_user_id: int
    new_rank: int               # 原 KOM 持有者现在排第几


def classify(
    elapsed_time: int,
    rank: int,
    is_pr: bool,
    previous_kom_user_id: int | None,
    current_user_id: int,
) -> tuple[EventResult | None, KomLostResult | None]:
    """
    根据排名和 PR 状态，判定应生成哪些事件。
    
    纯函数：不碰数据库，不碰网络，只做数字比较。
    
    返回值：
    - (EventResult, KomLostResult)：拿了 KOM 且夺了别人的
    - (EventResult, None)：拿了 KOM 但之前没人（第一条成绩）或 PR
    - (None, None)：不是 PR，不生成通知
    """
```

**判定逻辑：**

```
rank == 1 且 previous_kom_user_id 存在 且 != current_user_id:
    → EventResult(event_type='kom', rank=1)
    → KomLostResult(previous_holder_user_id, new_rank=2)

rank == 1 且 (无前任 或 前任是自己):
    → EventResult(event_type='kom', rank=1)
    → None

rank > 1 且 is_pr:
    → EventResult(event_type='pr', rank=rank if rank<=10 else None)
    → None

不是 PR:
    → None, None
```

### 2.2 关键边界情况

| 场景 | 预期行为 |
|------|---------|
| 用户在赛段的第一条成绩 | 必定是 PR。如果也是赛段第一条成绩，还是 KOM |
| 用户自己打破自己的 KOM | 生成 KOM 通知，不生成 KOM 被夺通知（`previous_kom_user_id == current_user_id`） |
| 用户打破 PR 但没进前 10 | 生成 PR 通知，rank=None |
| 用户打破 PR 且进前 10 | 生成 PR 通知，rank=具体值 |
| elapsed_time 为 0 | 理论上不可能（赛段有最小距离），但 detector 不做校验——由上游保证 |
| 同一 activity 匹配同一赛段两次 | UNIQUE(segment_id, activity_id) 在 SegmentEffort 层已防护，不会到达 detector |
| 并列第一（两人成绩完全相同） | 按 `ORDER BY elapsed_time, created_at` 先到先得。后来者 rank=2，不算 KOM |

---

## 3. 业务逻辑（service.py）

### 3.1 detect_events() — 对外唯一衔接点

```python
def detect_events(db: Session, effort: SegmentEffort) -> None:
    """
    检测 PR/KOM 事件并写入通知表。
    
    这是 notification 模块暴露给外部的唯一写入接口。
    auto_match.py 在所有赛段匹配 commit 后，对每条新 effort 调用此函数。
    import_scheduler.py 同理。
    
    故障隔离策略：
    - 整个函数用 try/except 包裹，任何异常只记日志，不向上抛
    - 数据库写入用 db.begin_nested()（SAVEPOINT）上下文管理器隔离
    - 异常时 SAVEPOINT 自动回滚，不污染调用方的 session 状态
    - 幂等：effort_id + event_type 的 UNIQUE 约束防重复，IntegrityError 静默跳过
    
    前置过滤：
    - 查 activity.data_source 和 activity.started_at
    - Strava 历史导入（data_source='strava' 且 started_at < 7天前）跳过
    - started_at 为 None 时不跳过（理论上 completed 状态都有值，但加防御）
    """
```

**内部流程：**

```
detect_events(db, effort)
  │
  ├─ try: （整个函数被 try/except 包裹）
  │
  ├─ 前置过滤：查 activity，判断是否跳过
  │    activity = db.get(Activity, effort.activity_id)
  │    如果 data_source=='strava' 且 started_at 不为 None 且 started_at < 7天前 → return
  │
  ├─ 查排名（复用共享函数）：
  │    rank = get_effort_rank(db, effort)
  │    使用索引：idx_efforts_segment_time
  │    排名规则：COUNT(同赛段 elapsed_time < effort.elapsed_time) + 1
  │    并列处理：同 elapsed_time 时按 created_at 先到先得（tiebreaker）
  │
  ├─ 查 PR：MIN(同赛段同用户 elapsed_time) → best_time
  │    is_pr = (effort.elapsed_time <= best_time)
  │    使用索引：idx_efforts_segment_user_time
  │    注意：当前 effort 已 commit 入库，MIN 结果包含 effort 自身。
  │    所以用 <=（不是 <）：best_time == effort.elapsed_time 时就是 PR
  │    （要么是第一条成绩，要么打平了历史最佳，两者都算 PR）
  │
  ├─ 如果 rank == 1：查原 KOM 持有者
  │    SELECT user_id FROM segment_efforts
  │    WHERE segment_id = ? ORDER BY elapsed_time, created_at LIMIT 1 OFFSET 1
  │    → previous_kom_user_id（第二名就是原来的第一名）
  │
  ├─ 调用 detector.classify() → event_result, kom_lost_result
  │
  ├─ 写入通知（SAVEPOINT 隔离）：
  │    with db.begin_nested():  # ← 正确用法：上下文管理器，正常退出自动 release
  │        如果有 event_result → INSERT notification（给当前用户）
  │        如果有 kom_lost_result → INSERT notification（给原 KOM 持有者）
  │             event_type='kom_lost'
  │             activity_id=effort.activity_id（夺走者的活动 ID）
  │             rival_user_id=effort.user_id（夺走者的用户 ID）
  │             rank=kom_lost_result.new_rank（被夺者掉到第几）
  │    db.commit()  # ← commit 通知写入（独立于赛段匹配的事务）
  │
  └─ except Exception:
       logger.warning("通知检测失败 effort_id=%s", effort.id, exc_info=True)
       db.rollback()  # ← 回滚通知事务，不影响已 commit 的成绩
```

### 3.2 共享排名计算函数

> **为什么抽共享函数？**
>
> 现有代码 `segment/service.py` 中已有排名计算逻辑（get_user_efforts、get_activity_segments 中的 COUNT SQL）。
> detect_events 的排名查询与之完全相同。如果各写一份，未来排名规则变了（比如加 tiebreaker）要改两个地方。
>
> 共享函数 `get_effort_rank(db, effort) -> int` 放在 `segment/service.py` 中，
> notification/service.py 和 segment/service.py 共用。

### 3.3 查原 KOM 持有者的逻辑说明

> **为什么查"第二名"而不是"之前的第一名"？**
>
> 因为当前用户的 effort 已经 commit 了，此时查排行榜，当前用户就是第一名。
> 原来的 KOM 持有者现在排第二。所以查 OFFSET 1 就是原 KOM 持有者。
>
> 但有一个边界：如果当前用户之前就是 KOM（自己打破自己的记录），
> 那第二名是自己的旧成绩，user_id 和当前用户相同 → classify() 会判定为
> "前任是自己"，不生成 KOM 被夺通知。这是正确的行为。
>
> **排序 tiebreaker**：`ORDER BY elapsed_time, created_at`——成绩相同时先到先得。
> 这避免了"并列第一"场景导致互发 KOM 被夺通知的问题。

### 3.4 get_notifications() — 通知列表查询

```python
def get_notifications(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    查询用户的通知列表，按时间倒序分页。
    
    JOIN 查出 segment_name 和 rival_nickname，前端无需二次请求。
    过滤掉已过期的通知（expires_at < now()）。
    """
```

**SQL 核心：**

```sql
SELECT n.*, s.name AS segment_name, rival.nickname AS rival_nickname
FROM notifications n
JOIN segments s ON n.segment_id = s.id
LEFT JOIN users rival ON n.rival_user_id = rival.id
WHERE n.user_id = :user_id AND n.expires_at > now()
ORDER BY n.created_at DESC
OFFSET :offset LIMIT :page_size
```

使用索引：`idx_notif_user_created`

### 3.5 get_user_honors() — 用户荣誉表

```python
def get_user_honors(db: Session, user_id: int) -> dict:
    """
    查询用户的 KOM 和前十名成绩。
    
    这是实时查询（不走 notifications 表），直接从 segment_efforts 算排名。
    使用窗口函数一次查出所有赛段排名，避免 N+1。
    """
```

**SQL 核心（窗口函数）：**

```sql
WITH ranked AS (
    SELECT 
        se.segment_id,
        s.name AS segment_name,
        se.user_id,
        se.elapsed_time,
        se.avg_speed,
        se.created_at,
        RANK() OVER (PARTITION BY se.segment_id ORDER BY se.elapsed_time ASC) AS rank
    FROM segment_efforts se
    JOIN segments s ON se.segment_id = s.id
    WHERE se.segment_id IN (
        SELECT DISTINCT segment_id FROM segment_efforts WHERE user_id = :user_id
    )
)
SELECT * FROM ranked
WHERE user_id = :user_id AND rank <= 10
ORDER BY rank ASC, segment_name ASC
```

**返回结构：**
- `koms`：rank == 1 的赛段列表
- `top10s`：2 ≤ rank ≤ 10 的赛段列表（不含 KOM，避免重复）
- `kom_count`、`top10_count`：计数

### 3.6 cleanup_expired() — 过期清理

```python
def cleanup_expired(db: Session) -> int:
    """
    删除过期通知。由定时任务每天调用一次。
    返回删除的条数，供日志记录。
    """
```

```sql
DELETE FROM notifications WHERE expires_at < now()
```

使用索引：`idx_notif_expires`

---

## 4. API 路由（router.py）

### 4.1 通知列表

```
GET /api/notifications?page=1&page_size=20
Authorization: Bearer <jwt>
```

**Response 200：**

```json
{
  "items": [
    {
      "id": 42,
      "event_type": "kom",
      "segment_id": 7,
      "segment_name": "滨河东路冲刺段",
      "activity_id": 156,
      "elapsed_time": 312,
      "rank": 1,
      "rival_user_id": null,
      "rival_nickname": null,
      "created_at": "2026-04-16T08:30:00Z"
    },
    {
      "id": 41,
      "event_type": "kom_lost",
      "segment_id": 3,
      "segment_name": "长风街爬坡",
      "activity_id": 155,
      "elapsed_time": null,
      "rank": 2,
      "rival_user_id": 8,
      "rival_nickname": "老王",
      "created_at": "2026-04-15T19:00:00Z"
    },
    {
      "id": 40,
      "event_type": "pr",
      "segment_id": 12,
      "segment_name": "汾河景区直道",
      "activity_id": 156,
      "elapsed_time": 485,
      "rank": null,
      "created_at": "2026-04-16T08:30:00Z"
    }
  ],
  "total": 38,
  "page": 1,
  "page_size": 20
}
```

**字段说明：**

| 字段 | PR 时 | KOM 时 | KOM 被夺时 |
|------|-------|--------|-----------|
| `elapsed_time` | 新 PR 用时 | KOM 用时 | null |
| `rank` | ≤10 时有值，>10 时 null | 1 | 当前掉到第几 |
| `rival_user_id` | null | null | 夺走者 ID |
| `rival_nickname` | null | null | 夺走者昵称 |
| `activity_id` | 触发 PR 的活动 | 触发 KOM 的活动 | 夺走者的活动 |

### 4.2 用户荣誉表

> **路由挂载说明**：`/api/user/honors` 前缀是 `/api/user`，需要独立的 router 实例
> （与 segment 模块的 `/api/user/efforts` 同模式）。notification 模块需两个 router：
> - `notification_router = APIRouter(prefix="/api/notifications", tags=["notification"])`
> - `honor_router = APIRouter(prefix="/api/user", tags=["notification"])`
> 两者都在 main.py 中注册。

```
GET /api/user/honors
Authorization: Bearer <jwt>
```

**Response 200：**

```json
{
  "koms": [
    {
      "segment_id": 7,
      "segment_name": "滨河东路冲刺段",
      "elapsed_time": 312,
      "avg_speed": 38.2,
      "achieved_at": "2026-04-16T08:30:00Z"
    }
  ],
  "top10s": [
    {
      "segment_id": 3,
      "segment_name": "长风街爬坡",
      "elapsed_time": 445,
      "avg_speed": 22.1,
      "rank": 4,
      "achieved_at": "2026-04-10T07:15:00Z"
    }
  ],
  "kom_count": 1,
  "top10_count": 1
}
```

---

## 5. 衔接改造（现有代码改动）

### 5.1 auto_match.py 改动

> **关键背景：实际代码的事务结构**
>
> auto_match.py 的 `match_activity_against_segments()` 使用"循环内 flush + 循环外统一 commit"模式：
> - 循环内：每条赛段匹配成功后 `db.add(effort)` + `db.flush()`（SAVEPOINT 隔离）
> - 循环外：所有赛段匹配完成后一次性 `db.commit()`
>
> **这意味着不能在循环内调用 detect_events**——此时 effort 只是 flush 了（未 commit），
> detect_events 的排名查询会看到未提交的数据，且 SAVEPOINT 嵌套会产生复杂的回滚行为。

**改动方案**：在循环中收集新创建的 effort 列表，统一 commit 后逐个检测。

```python
from app.notification.service import detect_events

# ---- 现有代码（循环内）----
new_efforts = []              # ← 新增：收集成功写入的 effort
for segment, ref_wkt in candidates:
    with db.begin_nested():   # SAVEPOINT 隔离（现有逻辑不变）
        # ... 匹配逻辑 ...
        effort = SegmentEffort(...)
        db.add(effort)
        db.flush()
        new_efforts.append(effort)  # ← 新增：记录成功的 effort

# ---- 现有代码（循环外）----
db.commit()

# ---- 新增：成绩已全部 commit，逐个检测事件 ----
for effort in new_efforts:
    detect_events(db, effort)
```

**为什么 commit 后 effort 对象还能用？**
SQLAlchemy 的 expire_on_commit=True（默认）会在 commit 后标记对象为"过期"，
下次访问属性时自动从数据库重新加载。effort.id、effort.segment_id 等字段仍可正常访问。

### 5.2 import_scheduler.py 改动

> **为什么这里也要改？**
>
> Strava 导入路径也会调用 `match_activity_against_segments()`（import_scheduler.py 第 349 行）。
> 如果不在这里也接入 detect_events，Strava **新活动**（Webhook 推送的最近骑行）
> 的 PR/KOM 事件就不会被检测到。
>
> 前置过滤在 detect_events 内部做（data_source + started_at 检查），
> 所以 import_scheduler 不需要额外判断——历史活动会被 detect_events 自动跳过。

**改动方案**：与 auto_match 同理，在赛段匹配完成后对新 effort 调用 detect_events。
由于 import_scheduler 是逐活动处理的（不是批量），改动更简单：
在 `match_activity_against_segments()` 返回后，查询该活动新增的 effort，逐个检测。

### 5.3 main.py 改动

```python
# 注册 notification 路由（两个 router）
from app.notification.router import notification_router, honor_router
app.include_router(notification_router)
app.include_router(honor_router)
```

### 5.4 定时清理任务

**挂载方式**：复用现有的 RQ scheduler 机制。在 Worker 启动脚本中注册一个每日任务：

```python
scheduler.schedule(
    scheduled_time=datetime.utcnow(),
    func=cleanup_expired_notifications,
    interval=86400,  # 每 24 小时
)
```

---

## 6. 已知风险与防护

| # | 风险 | 严重度 | 防护方案 |
|---|------|--------|---------|
| 1 | **Strava 批量导入通知风暴** — 首次绑定导入 200 条历史骑行，瞬间生成大量过时通知 | 高 | `data_source='strava' AND started_at < 7天前` 跳过通知生成 |
| 2 | **detect_events 异常污染 session** — SQL 出错导致 PostgreSQL 事务 abort，后续赛段匹配全炸 | 高 | try/except 包裹 + SAVEPOINT 隔离，异常只记日志 |
| 3 | **Worker 崩溃通知丢失** — effort 已 commit 但 detect_events 没跑完 | 低 | UNIQUE(effort_id, event_type) 幂等防护，补跑安全 |
| 4 | **KOM 竞态双通知** — 两人同时上传都超过原 KOM | 极低 | UNIQUE 约束去重，IntegrityError 静默跳过 |
| 5 | **7 天阈值误伤手动上传** — 用户手动上传一周前的 GPX | 中 | 阈值仅对 data_source='strava' 生效，手动上传永远触发通知 |
| 6 | **删活动级联影响他人通知** — A 的 KOM 活动删除后 B 的"被夺"通知丢失 | 低 | effort_id 用 ON DELETE SET NULL，通知保留但无详情 |
| 7 | **荣誉表 N+1 查询** — 逐赛段算排名 | 中 | 窗口函数一次查出，零 N+1 |

### 已知限制（不在本期修复）

- 删活动后排名恢复不触发通知：A 拿 KOM → B 收到被夺通知 → A 删活动 → B 实际恢复 KOM 但无通知
- KOM 被夺只通知原 KOM 持有者，不通知排名下降的其他人
- 通知不支持批量标记已读/删除（无此需求，60 天自动清理）
- Worker 崩溃导致的通知丢失无自动补发机制。未来可加定期扫描：查 segment_efforts 中没有对应通知的记录，补跑 detect_events
- kom_lost 通知的 activity_id 存的是**夺走者**的活动 ID。被夺者点击通知看到的是别人的活动详情——前端展示时需注意措辞，避免用户困惑

---

## 7. 任务拆分

> 章节号（设计文档结构）和任务号（编码顺序）分离。
> 任务号 7.X 对应编码实施步骤，章节号 1~6 对应设计文档各节。

### 任务 7.1：Notification 数据模型 + Alembic 迁移

**对应设计**：第 1 章
**交付物**：
- `app/notification/__init__.py`
- `app/notification/models.py` — Notification ORM 模型
- `migrations/versions/phase3_notifications.py` — 新建表 + 索引 + 约束
**验证**：`alembic upgrade head` 成功，表结构与 spec 一致

### 任务 7.2：detector.py — 纯函数事件分类

**对应设计**：第 2 章
**交付物**：
- `app/notification/detector.py` — classify() 纯函数 + EventResult/KomLostResult 数据类
**验证**：单元测试覆盖第 2.2 节全部边界情况（6 个场景）
**纯函数规则**：不碰数据库，不碰文件系统

### 任务 7.3：service.py — detect_events + 查询 + 清理

**对应设计**：第 3 章
**交付物**：
- `app/notification/service.py` — detect_events()、get_notifications()、get_user_honors()、cleanup_expired()
- `app/segment/service.py` — 新增共享函数 `get_effort_rank(db, effort) -> int`
**验证**：
- detect_events 的 SAVEPOINT 隔离测试（故意让通知写入失败，确认不污染 session）
- 幂等测试：重复调用不产生重复通知（IntegrityError 被静默跳过）
- 荣誉表窗口函数正确返回 KOM + 前十
- 并列成绩按 created_at 先到先得

### 任务 7.4：router.py — API 路由

**对应设计**：第 4 章
**交付物**：
- `app/notification/router.py` — 两个 router 实例：notification_router + honor_router
- `app/main.py` 注册两个路由
**验证**：API 返回格式与第 4 章 JSON 示例一致（elapsed_time 为整数）

### 任务 7.5：auto_match + import_scheduler 衔接

**对应设计**：第 5 章
**交付物**：
- `app/segment/auto_match.py` — 循环中收集 new_efforts 列表，commit 后逐个调用 detect_events
- `app/strava/import_scheduler.py` — 赛段匹配后对新 effort 调用 detect_events
- detect_events 内部的 Strava 历史过滤逻辑
**验证**：
- GPX 上传 → 解析 → 匹配 → 自动生成 PR 通知
- Strava 新活动（Webhook 推送）也能触发通知
- Strava 历史活动（>7天前）不生成通知
- detect_events 抛异常时 auto_match 和 import_scheduler 不受影响

### 任务 7.6：定时清理 + 集成测试

**对应设计**：第 3.6 节 + 第 6 章
**交付物**：
- cleanup_expired() 注册到 RQ scheduler
- 集成测试：完整流程（上传 → 匹配 → 通知生成 → 查询 → 过期清理）
**验证**：
- 过期通知被正确删除
- GPX 上传端到端跑通
- Strava 导入端到端跑通（含历史过滤验证）

---

## 8. 测试策略

| 层 | 测试内容 | 方法 |
|----|---------|------|
| **纯函数** | detector.classify() 的 7 个边界场景（含并列第一） | 单元测试，直接调用 |
| **Service** | detect_events 的 SAVEPOINT 隔离（故意失败不污染 session） | 数据库集成测试 |
| **Service** | detect_events 幂等性（重复调用不产生重复通知） | 数据库集成测试 |
| **Service** | detect_events Strava 历史过滤（data_source='strava' 且 >7天跳过） | 数据库集成测试 |
| **Service** | get_user_honors 窗口函数正确返回 KOM + 前十 | 数据库集成测试 |
| **Service** | get_effort_rank 共享函数（并列 tiebreaker 验证） | 数据库集成测试 |
| **API** | 返回格式（elapsed_time 为整数）、分页、过期过滤 | TestClient HTTP 测试 |
| **端到端** | GPX 上传 → 匹配赛段 → 生成通知 → 查询列表 | 全链路集成测试 |
| **端到端** | Strava 新活动导入 → 匹配 → 通知生成 | 全链路集成测试 |

---

## 9. 未来扩展预留

本期不实现，但数据模型和架构已预留接口：

| 扩展 | 预留点 | 改动量 |
|------|--------|--------|
| 微信服务消息推送 | detect_events 写完 DB 后，加一步发微信模板消息 | notification/service.py 加函数 |
| 新事件类型（如"被关注"） | event_type CHECK 约束加值 + detector 加分支 | 2 处改动 |
| 通知已读/未读 | notifications 表加 `is_read` 列 | 1 列 + 1 个 API |
| 通知偏好设置 | users 表加 `notification_prefs` JSONB 列 | detect_events 前查偏好 |
