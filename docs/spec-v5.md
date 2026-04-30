# VELO v5 期技术规格文档

> v5 期 4 主轴并列推进 + 1 跨主轴软目标。承接 v0-v4 基础设施，让 velo 从工具演进到内容平台 + 个人成长记录。
>
> **写作约束**：
> - 严格按 PRD v0.4 拍过的产品决策不偏离
> - §0.1 代码事实表所有引用先 grep / Read 核对（信条 14）
> - 任何函数名三选一：现有函数（file:line）/ 新增函数（完整签名+body）/ 内部抽取（视为新增）
>
> **本期工期**：8-10 周（三人并行折算）。Sprint 0 5-8 天清 P1 tech-debt + Sprint 1-3 主体实施 + Sprint 4 收尾。

---

## §0 决策记录

### §0.1 代码侧事实表

⚠ 信条 14 硬规定：spec 引用所有"现有代码"必先 grep / Read 核对。

**5.B.1 坡度+难度+城市**：
- [查询] segments 表字段全清单：id PK / name VARCHAR(128) / description Text / distance Float（米）/ elevation_gain Float / elevation_loss Float / avg_gradient Float / elevation_profile Text(JSON 80 点采样) / start_lat / start_lon / end_lat / end_lon / reference_line PostGIS LINESTRING / match_tolerance / min_match_ratio / created_at | app/segment/models.py:40-69
- [查询] DELETE /api/segments/{segment_id} 已存 | app/segment/router.py:84
- [查询] service.create_segment(db, user_id, name, reference_points, description, match_tolerance, min_match_ratio, coordinate_system) | app/segment/service.py:37-46
- [推断] segments 表**无 difficulty / max_gradient / city 字段**——v5 防火墙破例 3 处

**5.B.2 AI 介绍**：
- [查询] segments.description Text NULL 已存 | app/segment/models.py:44
- [查询] app/agent/ 目录**不存在**
- [推断] segment_ai_drafts 表不存——v5 新建

**5.B.3 搜索**：
- [查询] GET /api/segments 现有签名 list_segments(page, page_size, near_lat, near_lon, radius) | app/segment/router.py:103-111

**5.C.1 即时反馈**：
- [查询] segment_efforts 字段：id PK / segment_id FK NOT NULL / activity_id FK CASCADE NOT NULL / user_id FK NOT NULL / elapsed_time NOT NULL / avg_speed / avg_power / start_index NOT NULL / end_index NOT NULL | app/segment/models.py:90-111
- [查询] idx_efforts_segment_user_time(segment_id, user_id, elapsed_time) 已存 | app/segment/models.py:124
- [查询] GET /api/user/efforts 已存 | app/segment/router.py:187

**5.C.2 功率曲线**：
- [查询] trackpoints.power Integer NULL（W）| app/activity/models.py:181
- [查询] users.ftp Integer NULL | app/user/models.py:46

**5.C.3 进步推送**：
- [查询] notifications.event_type VARCHAR(20) CheckConstraint IN('pr','kom','kom_lost')| app/notification/models.py:45 + 105-107
- [查询] detector.py classify() 返 EventResult / KomLostResult | app/notification/detector.py:45-94

**5.A.1 热图**：
- [查询] users **无 city 字段**（防火墙破例 1 处）
- [查询] activities.simplified_track JSONB NULL | app/activity/models.py:113
- [查询] trackpoints.geom PostGIS POINT srid=4326 | app/activity/models.py:189

**5.A.2 看他人主页**：
- [查询] users 字段：id / openid / nickname / avatar_url / ftp / weight / bike_type / weekly_goal / is_admin / strava_athlete_id / strava_access_token / strava_refresh_token / strava_token_expires_at / mute_notifications / created_at / updated_at | app/user/models.py:32-93
- [推断] 当前无 GET /api/users/{user_id}——v5 新建

**5.D.1-5 admin**：
- [查询] users.is_admin Boolean server_default='false' | app/user/models.py:62
- [推断] 当前**无 /api/admin/* endpoint**——v5 新建路由前缀

**5.7.1 worker**：
- [查询] `_PROCESSING_TIMEOUT = 10 * 60` | app/activity/service.py:43
- [查询] activities.status String(20) server_default='pending' | app/activity/models.py:55
- [查询] 状态机：pending / processing / completed / failed | app/activity/models.py:53-55

**RQ 基础设施 + 部署事实（第二轮双审 B3A-I1 + B3B-1 修复）**：
- [查询] rq==2.7.0 / httpx==0.28.1 已装 | requirements.txt:11/15；**openai / requests 未装**（v5 用 DeepSeek 兼容 OpenAI SDK，Tim 2026-04-29 拍）
- [查询] Redis 连接散在 3 处：worker.py:24（`Redis.from_url(...)`）/ app/activity/service.py:31（`_redis_conn`/`_queue`）/ scripts/cleanup_zombies.py —— **`app/queue.py` 不存在**
- [查询] 真实 SessionLocal 路径是 `app.database`（**不是 `app.db`**）| app/database.py
- [查询] alembic 真实路径是 `migrations/versions/`（**不是 `alembic/versions/`**）| alembic.ini → script_location = migrations
- [查询] worker.py:31 硬编码 `Worker([queue], connection=redis_conn).work()` —— 单 'velo' 队列订阅
- [查询] settings 单一来源：`from app.config import settings` + `settings.XXX`（项目 30+ 处使用），**禁止顶层常量 import**
- [查询] 现有 cron 模式：`scripts/cleanup_zombies.py` + docker-compose 内 `while true; sleep 300` 容器包装 | docker-compose.yml:83
- [查询] User.is_admin Boolean server_default='false' | app/user/models.py:62
- [查询] Activity.started_at = `Column(DateTime, nullable=True)` —— **naive，无 timezone=True**（Sprint 0 task 0.1 必迁，第二轮双审 B2B-2）| app/activity/models.py:85
- [查询] Trackpoint.geom = `Column(Geometry("POINT", srid=4326), nullable=True)` —— 老数据可能 NULL | app/activity/models.py:189
- [推断] v5 必新建：`app/queue.py`（task 0.8）+ `app/common/__init__.py` + `app/common/geo.py`（B2A-2）+ `app/agent/__init__.py` + `app/agent/segment_writer.py` + `app/agent/tasks.py` + `app/admin/*`（4 文件）+ `app/monitor/*`（2 文件）

### §0.2 决策汇总

#### PRD v0.4 产品决策

- 4 主轴并列全做（B 内容 + C 数据 + A 个人页 + D 工具）
- 难度评级 4 档（极难 / 难 / 中 / 易）+ 各档定性偏好
- 城市 6 枚举（北 / 上 / 杭 / 深 / 成 / 太）+ unknown
- AI 介绍 30-50 精选 / 单条 50-100 字 / 元素稀疏
- 候选池：脚本筛 100 + 团队人工拍 30-50 / 每城 5-8 条
- 进步阈值：5W（5min 最大平均功率涨 ≥ 5W）
- worker 软目标：90% < 5min + 10 分钟 timeout 沿用 v4 不改
- 看他人主页**默认公开** + settings 隐私开关
- H5 admin 复用主站微信登录态
- RAG **留接口不实现**（建 app/agent/ 目录架构，无向量检索）
- 防火墙破例 4 处：segments 加 difficulty + max_gradient + city / users 加 city

#### Spec 层工程决策

- 时长分桶 buckets：**6 档**（1s / 5s / 30s / 1min / 5min / 20min，Strava 行业标准）
- AI 草稿审核状态机：pending / human_edited / approved / rejected
- segments.difficulty 枚举：'easy' / 'medium' / 'hard' / 'extreme'
- segments.city / users.city 枚举：'beijing' / 'shanghai' / 'hangzhou' / 'shenzhen' / 'chengdu' / 'taiyuan' / 'unknown'
- 候选池脚本：每周一次定时跑
- 通知推送：沿用 v3/v4 通知中心 + 红点
- 新增表：segment_ai_drafts（5.B.2）/ segment_curation_pool（5.D.1）
- progress 类通知沿用 notifications 表 + event_type 扩展（详 §3）

---

## §1 架构总览

### §1.1 模块边界（v5 14 子任务 × 现有 6 模块 + 2 新模块）

| 子任务 | 影响模块 | 改动类型 |
|---|---|---|
| 5.B.1 坡度+难度+城市 | segment | 表加字段（破例 3）+ service/router 扩展 |
| 5.B.2 AI 介绍 | segment + **agent**（新）| 新表 segment_ai_drafts + 新建 app/agent/ |
| 5.B.3 搜索 | segment | router 加 search 参数 |
| 5.C.1 即时反馈 | segment | service/router 扩展 |
| 5.C.2 功率曲线 | user + activity | router + 算法 |
| 5.C.3 进步推送 | notification | progress_detector 扩展 + event_type 加值 |
| 5.A.1 热图 | user | users 加 city（破例 1）+ router 加 heatmap |
| 5.A.2 看他人主页 | user | router 加 GET /api/users/{user_id} |
| 5.D.1 候选池 | segment + **admin**（新）| 新表 segment_curation_pool + admin 路由 |
| 5.D.2 AI 草稿审核 | segment + agent + admin | 沿用 segment_ai_drafts + admin endpoint |
| 5.D.3 批量管理 | segment + admin | admin endpoint 扩展 |
| 5.D.4 from-activity | segment + activity + admin | 新 admin endpoint + 算法 |
| 5.D.5 H5 admin | **新前端项目** | 独立 H5 域名 + 项目 |
| 5.7.1 worker 软目标 | activity | 监控告警 + 容器扩容 |

### §1.2 防火墙破例 4 处

按 CLAUDE.md "防火墙式扩展"：核心表默认不动。**v5 破例 4 处**：

| 表 | 加字段 | 类型 | 默认 | 理由 |
|---|---|---|---|---|
| segments | difficulty | VARCHAR(16) | 'medium' | 赛段内在属性 |
| segments | max_gradient | FLOAT | NULL | 赛段内在属性（百分比）|
| segments | city | VARCHAR(32) | 'unknown' | 赛段地理位置内在属性 |
| users | city | VARCHAR(32) | NULL | 用户地理身份内在属性 |

新模块全部新建表：segment_ai_drafts / segment_curation_pool。

### §1.3 数据流概要（7 条新增 / 改动链路）

1. **5.B.1 + 5.D.4 赛段创建**：trackpoints 提坐标 → 算 max_gradient + difficulty + city → 写 segments
2. **5.B.2 + 5.D.1 + 5.D.2 AI 介绍**：候选池脚本 → 团队勾选 → AI 调 DeepSeek API → 草稿入 segment_ai_drafts → 审核改写 → status=approved → 同步到 segments.description
3. **5.C.1 即时反馈**：用户访问赛段页 → service 查 last/PR + 计算 diff → API 返回
4. **5.C.2 功率曲线**：访问个人页 → 算 max_avg_power per bucket per period → Redis 缓存 → 返回多曲线
5. **5.C.3 进步推送**：activity processing 完成 → progress_detector → 阈值检测 → 写 notification → 通知中心
6. **5.A.1 热图**：访问个人页 → service 按 user.city 查 activities.simplified_track（JSONB list of [lon, lat]）→ Python 端聚合点列表 + Redis 缓存 1h → 返回 points 数组（**第二轮双审 B2A-3 修复：实际是 JSONB 聚合，不是 PostGIS 聚合，与 §3.5 实现保持一致**）
7. **5.A.2 他人主页**：跳转 → GET /api/users/{user_id} → 严格字段过滤 → 返回

---

## §2 数据模型

### §2.1 防火墙破例 4 字段

| 表 | 字段 | 类型 | 默认 | NULL | CHECK |
|---|---|---|---|---|---|
| segments | difficulty | VARCHAR(16) | 'medium' | NOT NULL | IN ('easy','medium','hard','extreme') |
| segments | max_gradient | FLOAT | NULL | NULL | — |
| segments | city | VARCHAR(32) | 'unknown' | NOT NULL | IN (6 城 + 'unknown') |
| users | city | VARCHAR(32) | NULL | NULL | NULL OR IN (6 城 + 'unknown') |

复合索引：`idx_segments_city_difficulty(city, difficulty)`（5.B.1 列表筛选 + 5.B.3 搜索组合用）。

### §2.2 新建表 2 个

#### segment_ai_drafts（5.B.2）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK autoincrement |
| segment_id | Integer | FK segments.id ondelete=CASCADE NOT NULL **UNIQUE** |
| ai_draft_text | Text | NOT NULL |
| human_edited_text | Text | NULL |
| status | VARCHAR(16) | NOT NULL DEFAULT 'pending' / CHECK IN ('pending','human_edited','approved','rejected') |
| editor_user_id | Integer | FK users.id ondelete=SET NULL NULL |
| created_at | DateTime(timezone=True) | server_default now() NOT NULL |
| updated_at | DateTime(timezone=True) | server_default now() onupdate now() NOT NULL |

索引：`idx_ai_drafts_status(status)` —— 5.D.2 按状态筛 pending 草稿。
UNIQUE 约束：`uq_segment_ai_drafts_segment_id(segment_id)` —— 一条赛段一份草稿。

#### segment_curation_pool（5.D.1）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK autoincrement |
| segment_id | Integer | FK segments.id ondelete=CASCADE NOT NULL **UNIQUE** |
| pool_score | Float | NOT NULL |
| pool_reason | VARCHAR(64) | NULL（取值参考：'high_attempts' / 'frequent_kom' / 'difficulty_balance' / 'manual_added'）|
| selected_for_v5 | Boolean | NOT NULL DEFAULT false |
| selected_by_user_id | Integer | FK users.id ondelete=SET NULL NULL |
| selected_at | DateTime(timezone=True) | NULL |
| created_at | DateTime(timezone=True) | server_default now() NOT NULL |

索引：`idx_curation_pool_selected(selected_for_v5)` —— 5.D.1 列表显示已选/未选。
UNIQUE 约束：`uq_curation_pool_segment_id(segment_id)` —— 候选池脚本幂等保证。

#### §2.2.3 ORM 模型类完整定义（追加到 `app/segment/models.py`）

按 Step 6 函数完整实现规则，新表 ORM 类必须给完整定义（**禁止推给 subagent 自定义**）：

```python
# app/segment/models.py 追加（在现有 Segment / SegmentEffort 类之后）
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, CheckConstraint, Index, UniqueConstraint, false, func,
)
# 注：app/database.py Base 已存（v0 init），下面 ORM 类继承现有 Base


class SegmentAiDraft(Base):
    """
    AI 赛段介绍草稿（5.B.2）。
    一条赛段一份草稿（UNIQUE segment_id），状态机 pending → human_edited → approved / rejected。
    approved 触发同步到 Segment.description（admin/service.py 编排，不在此处）。
    """
    __tablename__ = 'segment_ai_drafts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(
        Integer,
        ForeignKey('segments.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )
    ai_draft_text = Column(Text, nullable=False)
    human_edited_text = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, server_default='pending')
    editor_user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'human_edited', 'approved', 'rejected')",
            name='ck_segment_ai_drafts_status',
        ),
        UniqueConstraint('segment_id', name='uq_segment_ai_drafts_segment_id'),
        Index('idx_ai_drafts_status', 'status'),
    )


class SegmentCurationPool(Base):
    """
    候选池表（5.D.1）。
    脚本周期性生成 top 100 候选 + 团队人工勾选 30-50 入精选。
    """
    __tablename__ = 'segment_curation_pool'

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(
        Integer,
        ForeignKey('segments.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )
    pool_score = Column(Float, nullable=False)
    pool_reason = Column(String(64), nullable=True)
    selected_for_v5 = Column(Boolean, server_default=false(), nullable=False)
    selected_by_user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    selected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint('segment_id', name='uq_curation_pool_segment_id'),
        Index('idx_curation_pool_selected', 'selected_for_v5'),
    )
```

### §2.3 现有表字段值域扩展

#### notifications.event_type CHECK 扩展（5.C.3）

现有：`CheckConstraint("event_type IN ('pr', 'kom', 'kom_lost')")` | app/notification/models.py:105-107

扩展加 3 值（progress 推送）：
- `'progress_5min_power'`（5min 最大平均功率涨 ≥ 5W）
- `'progress_segment_pb'`（赛段 PB 异步通知，跟 5.C.1 即时反馈同源不重复）
- `'progress_monthly_summary'`（每月 1 日推上月对比）

新值域 = 6 个值。

⚠ 陷阱 #6（PG 外键 / CHECK 自动命名）：CHECK 约束实际名 **`ck_notif_event_type`**（grep `app/notification/models.py:107` + `migrations/versions/phase3_notifications.py:40` 验证为显式命名，**非 PG 默认**）。spec §2.5 已用此精确名。

#### activities 表：无变化

5.7.1 worker 软目标只改逻辑（监控告警 + 容器扩容），不改 activities 结构。

### §2.4 索引清单总览

| 索引名 | 表 | 字段 | 用途 | 状态 |
|---|---|---|---|---|
| idx_segments_city_difficulty | segments | (city, difficulty) | 5.B.1 / 5.B.3 筛选 | 新增 |
| idx_ai_drafts_status | segment_ai_drafts | (status) | 5.D.2 按状态筛 | 新增（伴随建表）|
| idx_curation_pool_selected | segment_curation_pool | (selected_for_v5) | 5.D.1 选中状态查询 | 新增（伴随建表）|
| idx_efforts_segment_user_time | segment_efforts | (segment_id, user_id, elapsed_time) | 5.C.1 即时反馈 | 已存（v0/v1）|

### §2.5 Alembic 迁移脚本（完整实现）

> **路径修正（第二轮双审 B3B-3）**：本项目实际目录是 `migrations/versions/` 而非 `alembic/versions/`。下文所有 file path 均按真实路径理解。

**文件**：`migrations/versions/<rev_id>_phase5_v5_db_changes.py`

**前置 grep**（实施时必做）：
- 当前 alembic head：`alembic current` 取 prev_revision
- notifications CHECK 约束实际名：PG inspector 查（陷阱 #6）

```python
"""phase5 v5 db changes

Revision ID: <new_rev_id>
Revises: <prev_head_rev>
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = '<new_rev_id>'
down_revision = '<prev_head_rev>'
branch_labels = None
depends_on = None


def upgrade():
    # === 1. segments 加 3 字段（防火墙破例 3 处）===
    op.add_column(
        'segments',
        sa.Column('difficulty', sa.String(length=16), nullable=False, server_default='medium')
    )
    op.add_column(
        'segments',
        sa.Column('max_gradient', sa.Float(), nullable=True)
    )
    op.add_column(
        'segments',
        sa.Column('city', sa.String(length=32), nullable=False, server_default='unknown')
    )
    op.create_check_constraint(
        'ck_segments_difficulty',
        'segments',
        "difficulty IN ('easy', 'medium', 'hard', 'extreme')"
    )
    op.create_check_constraint(
        'ck_segments_city',
        'segments',
        "city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')"
    )
    op.create_index('idx_segments_city_difficulty', 'segments', ['city', 'difficulty'])

    # === 2. users 加 city 字段（防火墙破例 1 处）===
    op.add_column(
        'users',
        sa.Column('city', sa.String(length=32), nullable=True)
    )
    op.create_check_constraint(
        'ck_users_city',
        'users',
        "city IS NULL OR city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')"
    )

    # === 3. 新建 segment_ai_drafts 表（5.B.2）===
    op.create_table(
        'segment_ai_drafts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('segment_id', sa.Integer(),
                  sa.ForeignKey('segments.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('ai_draft_text', sa.Text(), nullable=False),
        sa.Column('human_edited_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16),
                  nullable=False, server_default='pending'),
        sa.Column('editor_user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('segment_id', name='uq_segment_ai_drafts_segment_id'),
    )
    op.create_check_constraint(
        'ck_segment_ai_drafts_status',
        'segment_ai_drafts',
        "status IN ('pending', 'human_edited', 'approved', 'rejected')"
    )
    op.create_index('idx_ai_drafts_status', 'segment_ai_drafts', ['status'])

    # === 4. 新建 segment_curation_pool 表（5.D.1）===
    op.create_table(
        'segment_curation_pool',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('segment_id', sa.Integer(),
                  sa.ForeignKey('segments.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('pool_score', sa.Float(), nullable=False),
        sa.Column('pool_reason', sa.String(length=64), nullable=True),
        sa.Column('selected_for_v5', sa.Boolean(),
                  server_default=sa.false(), nullable=False),
        sa.Column('selected_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('selected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('segment_id', name='uq_curation_pool_segment_id'),
    )
    op.create_index('idx_curation_pool_selected', 'segment_curation_pool', ['selected_for_v5'])

    # === 5. notifications.event_type CHECK 扩展（5.C.3）===
    # 实际约束名通过 inspector 查（见 §2.3 陷阱 #6 说明）
    op.drop_constraint('ck_notif_event_type', 'notifications', type_='check')
    op.create_check_constraint(
        'ck_notif_event_type',
        'notifications',
        "event_type IN ('pr', 'kom', 'kom_lost', "
        "'progress_5min_power', 'progress_segment_pb', 'progress_monthly_summary')"
    )

    # 老数据回填不在迁移脚本里 —— 见 §2.6 + scripts/backfill_phase5.py


def downgrade():
    # === 5. 还原 notifications CHECK ===
    op.drop_constraint('ck_notif_event_type', 'notifications', type_='check')
    op.create_check_constraint(
        'ck_notif_event_type',
        'notifications',
        "event_type IN ('pr', 'kom', 'kom_lost')"
    )
    # === 4. 删 segment_curation_pool ===
    op.drop_index('idx_curation_pool_selected', 'segment_curation_pool')
    op.drop_table('segment_curation_pool')
    # === 3. 删 segment_ai_drafts ===
    op.drop_index('idx_ai_drafts_status', 'segment_ai_drafts')
    op.drop_constraint('ck_segment_ai_drafts_status', 'segment_ai_drafts', type_='check')
    op.drop_table('segment_ai_drafts')
    # === 2. 删 users.city ===
    op.drop_constraint('ck_users_city', 'users', type_='check')
    op.drop_column('users', 'city')
    # === 1. 删 segments.city / max_gradient / difficulty ===
    op.drop_index('idx_segments_city_difficulty', 'segments')
    op.drop_constraint('ck_segments_city', 'segments', type_='check')
    op.drop_constraint('ck_segments_difficulty', 'segments', type_='check')
    op.drop_column('segments', 'city')
    op.drop_column('segments', 'max_gradient')
    op.drop_column('segments', 'difficulty')
```

**陷阱清单扫描**（CLAUDE.md "技术栈陷阱清单" 10 条）：
- 陷阱 #6（PG CHECK / FK 自动命名）：notifications CHECK 实际名 `ck_notif_event_type` ✓ 已 grep 验证（非默认命名）
- 陷阱 #7（Alembic alter_column 类型转换）：本期无类型转换，N/A
- 陷阱 #8（SAVEPOINT 隔离）：本迁移单事务无循环，N/A
- ADD COLUMN with NOT NULL DEFAULT：避免锁表 ✓ 已用（segments.difficulty / segments.city）

### §2.6 老数据回填策略（独立脚本，不阻塞迁移）

> **simplified_track 结构假设（第二轮双审 B1-A4 / B1-B5 修复）**：activities.simplified_track JSONB 是 list of dict `[{'lat': float, 'lon': float, 'distance': float, ...}, ...]`（v3 既定，参 `app/activity/simplify.py`）。本节代码 `pt.get('lat') / pt.get('lon')` 默认此结构。subagent 实施前 grep `simplify.py` 验证字段名；未来若改 simplified 字段结构需同步本脚本。

**文件**：`scripts/backfill_phase5.py`
**触发顺序**：alembic upgrade → backfill segments → backfill users.city → 验证

#### segments 回填（difficulty / max_gradient / city）

```python
# scripts/backfill_phase5.py
import argparse
import logging
from app.database import SessionLocal
from app.segment.models import Segment
from app.activity.models import Trackpoint
from app.segment.service import calculate_max_gradient, calculate_difficulty
from app.common.geo import infer_city_from_coords  # 第二轮双审 B2A-2 修复：抽到 common 避免反向依赖

logger = logging.getLogger(__name__)


def backfill_segments(db):
    """
    给 segments 表所有现有记录回填 difficulty / max_gradient / city。
    单条 try/except 隔离，失败记 logger 不阻塞整体。
    用 db.begin_nested() SAVEPOINT 隔离循环（陷阱 #8）。
    """
    segments = db.query(Segment).all()
    success, failed = 0, []
    for seg in segments:
        try:
            with db.begin_nested():  # SAVEPOINT 隔离单条失败
                # max_gradient: PostGIS ST_DWithin 查 reference_line buffer 50m 内 trackpoints
                # ⚠️ ST_DWithin 单位陷阱（CLAUDE.md §关键技术约定）：必须 ::geography 转换，
                # 否则单位是经纬度（度），50 ≈ 5500km buffer 完全失效。
                # 第二轮双审 B1-B6 修复：Trackpoint.geom nullable=True，老数据可能 NULL，必须过滤
                from sqlalchemy import cast
                from geoalchemy2 import Geography  # 与现有 service.py:24 风格一致（顶层 import）
                tps = db.query(Trackpoint).filter(
                    Trackpoint.geom.isnot(None),
                    func.ST_DWithin(
                        cast(Trackpoint.geom, Geography),
                        cast(seg.reference_line, Geography),
                        50,  # 米
                    )
                ).order_by(Trackpoint.activity_id, Trackpoint.seq).all()
                seg.max_gradient = calculate_max_gradient(tps) if tps else None

                # difficulty 规则推算
                seg.difficulty = calculate_difficulty(
                    seg.distance,
                    seg.elevation_gain or 0.0,
                    seg.max_gradient or 0.0,
                )

                # city 从起点推断
                seg.city = infer_city_from_coords(seg.start_lat, seg.start_lon)

            success += 1
        except Exception as e:
            logger.error(f"backfill segment id={seg.id} failed: {e}")
            failed.append(seg.id)

    db.commit()
    logger.info(f"backfill segments: success={success}, failed={len(failed)}: {failed}")
    return failed
```

#### users.city 回填（fallback 链）

```python
def backfill_users_city(db):
    """
    fallback 链：
    1. 近 30 天 activities most-frequent 城市
    2. 全部 activities most-frequent 城市
    3. NULL（无 activity 用户）
    
    使用 datetime.now(timezone.utc) 而非 datetime.utcnow()（避免 naive vs aware 陷阱 #2）
    """
    from datetime import datetime, timedelta, timezone
    from collections import Counter
    from app.user.models import User
    from app.activity.models import Activity

    users = db.query(User).filter(User.city.is_(None)).all()
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

    for user in users:
        try:
            with db.begin_nested():
                # Step 1: 近 30 天
                recent = (
                    db.query(Activity)
                    .filter(
                        Activity.user_id == user.id,
                        Activity.started_at >= cutoff_30d,
                        Activity.status == 'completed',
                    )
                    .all()
                )
                cities = [
                    infer_city_from_coords(
                        a.simplified_track[0].get('lat'),
                        a.simplified_track[0].get('lon'),
                    )
                    for a in recent
                    if a.simplified_track and len(a.simplified_track) > 0
                ]
                cities = [c for c in cities if c != 'unknown']
                if cities:
                    user.city = Counter(cities).most_common(1)[0][0]
                    continue

                # Step 2: 全部 activities
                all_acts = (
                    db.query(Activity)
                    .filter(
                        Activity.user_id == user.id,
                        Activity.status == 'completed',
                    )
                    .all()
                )
                cities = [
                    infer_city_from_coords(
                        a.simplified_track[0].get('lat'),
                        a.simplified_track[0].get('lon'),
                    )
                    for a in all_acts
                    if a.simplified_track and len(a.simplified_track) > 0
                ]
                cities = [c for c in cities if c != 'unknown']
                if cities:
                    user.city = Counter(cities).most_common(1)[0][0]
                    continue

                # Step 3: 保持 NULL（默认即 NULL，不动）
        except Exception as e:
            logger.error(f"backfill user.city user_id={user.id} failed: {e}")
            continue

    db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--segments', action='store_true')
    parser.add_argument('--users', action='store_true')
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.segments:
            backfill_segments(db)
        if args.users:
            backfill_users_city(db)
    finally:
        db.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
```

**验收**：
- segments 回填后 `SELECT COUNT(*) FROM segments WHERE city='unknown'` < 30%（PRD 5.B.1 验收）
- 失败赛段记到 `scripts/backfill_phase5_failed.txt`，事后用 5.D.3 批量管理人工修
- users.city 回填后 NULL 占比 = 无任何 activity 的新用户比例（合理）

### §2.7 数据流图（7 条新增 / 改动链路）

```
1. 赛段创建（5.B.1 + 5.D.4）
   Activity trackpoints (PostGIS POINT) → admin 选起终点
       → 坐标子序列提取
       → calculate_max_gradient + calculate_difficulty + infer_city_from_coords
       → segments 表写入（含 difficulty / max_gradient / city）

2. AI 介绍（5.B.2 + 5.D.1 + 5.D.2）
   segments 全表 → 候选池脚本（pool_score 排序）
       → segment_curation_pool top 100
       → 团队 H5 admin 勾选 selected_for_v5=true
       → 触发 AI 调 DeepSeek API（OpenAI 兼容 SDK）
       → segment_ai_drafts.ai_draft_text 写入（status=pending）
       → 团队 H5/小程序 admin tab 审核改写
       → human_edited_text + status=approved
       → 同步 segments.description

3. 即时反馈（5.C.1）
   用户访问赛段详情页
       → GET /api/segments/{id}/efforts/me
       → service 查 segment_efforts WHERE user_id+segment_id ORDER BY created_at DESC LIMIT 2 + MIN(elapsed_time) AS pr
       → API 响应（current / last / pr / diff）

4. 功率曲线（5.C.2）
   用户访问个人页 → 点功率曲线卡片
       → GET /api/users/me/power-curve?period=this_month
       → Redis cache lookup
       → cache miss → calculate_power_curve(trackpoints, [1,5,30,60,300,1200])
       → Redis SET TTL 1h
       → API 响应（6 buckets × period）

5. 进步推送（5.C.3）
   activity processing 完成（worker）
       → progress_detector.detect_5min_power_progress
       → 阈值检测（≥ 5W）
       → notifications 写入（event_type='progress_5min_power'）
       → 通知中心展示（沿用 v3/v4 列表 + 红点）

6. 个人热图（5.A.1）
   用户访问个人页 → 默认 user.city 热图
       → GET /api/users/me/heatmap?city=<city>
       → Redis cache lookup
       → cache miss → 查 activities WHERE user_id 且 simplified_track 起点在 <city> 范围
       → PostGIS multipoint 聚合
       → Redis SET TTL 1h
       → API 响应（GeoJSON multipoint）

7. 看他人主页（5.A.2）
   用户从排行榜/通知/群聊昵称跳转
       → GET /api/users/{user_id}/profile
       → service.get_user_profile_for_others（严格字段过滤 + 用户隐私设置 mask）
       → API 响应（不含 efforts / activities / heatmap）
```

---

## §3 核心逻辑（前半：segment 算法 + 即时反馈 + 功率曲线）

按信条 14 + Step 6 函数完整实现规则：所有新增函数给完整签名 + body + 异常处理。引用现有函数标 file:line。技术栈陷阱按 CLAUDE.md "技术栈陷阱清单"扫描。

**前置依赖（Sprint 0 task-0.1 必先完成）**：本节代码假设 datetime 栈内统一 aware UTC + 所有 DateTime 字段已迁 `timezone=True`（参 §8.1）。Sprint 0 未完成前直接跑本节 `datetime.now(timezone.utc)` 跟 DB 字段（如 `Activity.started_at`、`Notification.created_at` v0-v4 仍是 naive）比较会触发**陷阱 #2 naive vs aware TypeError**。

### §3.1 segment 模块新算法（5.B.1 / 5.B.3 / 5.D.4）

#### 3.1.1 calculate_max_gradient（新增纯函数）

**位置**：`app/segment/service.py` 新增（与现有 service.create_segment 同模块）

**契约**：纯函数，不碰 DB / 不碰文件系统（参 CLAUDE.md "纯函数规则"）。

```python
import math

def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    两点 GPS 直线距离（米）。haversine 公式。
    
    参数：lat / lon 度数。
    返回：距离米。
    """
    R = 6371000.0  # 地球半径 m
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calculate_max_gradient(trackpoints: list) -> float:
    """
    从 trackpoints 序列计算最大坡度（百分比）。
    
    算法：100m 距离窗口滑动 → 每个窗口算坡度 = |海拔差| / 距离 * 100，取最大。
    
    参数：
        trackpoints: list[Trackpoint] 按 seq 升序，含 lat / lon / elevation 字段
    返回：
        float 最大坡度百分比（0 到 ~30）；空列表 / 单点 / 全无海拔 → 0.0
    
    陷阱 #1：elevation 可能 None，必须 `is not None` 检查（不用 `if ele`，0 海拔合法）
    """
    if len(trackpoints) < 2:
        return 0.0
    
    WINDOW_M = 100.0
    
    # 累计距离
    cumulative_dist = [0.0]
    for i in range(1, len(trackpoints)):
        d = _haversine_distance(
            trackpoints[i - 1].latitude, trackpoints[i - 1].longitude,
            trackpoints[i].latitude, trackpoints[i].longitude,
        )
        cumulative_dist.append(cumulative_dist[-1] + d)
    
    max_grad = 0.0
    j = 0
    for i in range(len(trackpoints)):
        # j 前进到 cumulative_dist[j] - cumulative_dist[i] >= WINDOW_M
        while j < len(trackpoints) and cumulative_dist[j] - cumulative_dist[i] < WINDOW_M:
            j += 1
        if j >= len(trackpoints):
            break
        
        ele_start = trackpoints[i].elevation
        ele_end = trackpoints[j].elevation
        if ele_start is None or ele_end is None:
            continue
        
        actual_dist = cumulative_dist[j] - cumulative_dist[i]
        if actual_dist <= 0:
            continue
        
        gradient = abs(ele_end - ele_start) / actual_dist * 100
        if gradient > max_grad:
            max_grad = gradient
    
    return max_grad
```

**单元测试要求**（≥ 5 case）：
- 空列表 → 0.0
- 单点 → 0.0
- 全水平（海拔不变）→ 0.0
- 全 None elevation → 0.0
- 标准 5% 坡度 → ~5.0（误差 < 0.5）
- 极陡 20% 局部 → ~20.0

#### 3.1.2 calculate_difficulty（新增纯函数）

**位置**：`app/segment/service.py` 新增

```python
def calculate_difficulty(
    distance_m: float,
    elevation_gain_m: float,
    max_gradient_pct: float,
) -> str:
    """
    规则推算赛段难度评级。
    
    PRD §3.1 定性偏好：
    - extreme: max_gradient > 15% OR elevation_gain > 1500m（"90% 普通骑手走着上山"）
    - hard:    max_gradient > 10% OR elevation_gain > 800m（"FTP 200W 以下会被拉爆"）
    - medium:  max_gradient > 5%  OR elevation_gain > 300m（"中级骑手能完成但有挑战"）
    - easy:    其他（"新手友好，热身用"）
    
    返回值：'easy' / 'medium' / 'hard' / 'extreme'（CHECK 约束 §2.1）
    """
    if max_gradient_pct > 15 or elevation_gain_m > 1500:
        return 'extreme'
    if max_gradient_pct > 10 or elevation_gain_m > 800:
        return 'hard'
    if max_gradient_pct > 5 or elevation_gain_m > 300:
        return 'medium'
    return 'easy'
```

**单元测试要求**（≥ 5 case）：4 档边界值 / 极陡短赛段（distance 短但 max_gradient 高）/ 长平赛段。

#### 3.1.3 infer_city_from_coords（新增纯函数）

**位置**：**`app/common/geo.py` 新建**（第二轮双审 B2A-2 + Tim 拍：抽到 common 模块避免 user.service → segment.service 反向依赖。`app/common/__init__.py` 同步建空文件，作为"无业务逻辑、可被任意模块依赖的工具层"）。
segment / user 两个模块都从 `app.common.geo` 导入，符合 CLAUDE.md "User ← Activity ← Segment" 单向依赖（common 在所有模块下方）。

```python
# 6 城 GPS 边界 box（经验值，spec 实施时可调，5.D.3 批量管理工具人工修正）
_CITY_BOUNDS = {
    'beijing':  {'lat_min': 39.4, 'lat_max': 41.1, 'lon_min': 115.4, 'lon_max': 117.5},
    'shanghai': {'lat_min': 30.7, 'lat_max': 31.9, 'lon_min': 120.9, 'lon_max': 122.0},
    'hangzhou': {'lat_min': 29.8, 'lat_max': 30.6, 'lon_min': 119.8, 'lon_max': 120.7},
    'shenzhen': {'lat_min': 22.4, 'lat_max': 22.9, 'lon_min': 113.7, 'lon_max': 114.7},
    'chengdu':  {'lat_min': 30.3, 'lat_max': 31.0, 'lon_min': 103.7, 'lon_max': 104.4},
    'taiyuan':  {'lat_min': 37.5, 'lat_max': 38.1, 'lon_min': 112.3, 'lon_max': 113.0},
}


def infer_city_from_coords(lat: float | None, lon: float | None) -> str:
    """
    根据 GPS 起点坐标判断所属城市。
    
    返回：6 城枚举之一 或 'unknown'。
    
    陷阱 #1：lat/lon 可能 None → 必须 `is not None` 检查。
    """
    if lat is None or lon is None:
        return 'unknown'
    for city, bounds in _CITY_BOUNDS.items():
        if (bounds['lat_min'] <= lat <= bounds['lat_max']
                and bounds['lon_min'] <= lon <= bounds['lon_max']):
            return city
    return 'unknown'
```

**单元测试要求**：6 城代表点 + (None, None) → 'unknown' + 跨城边界点 + 海外坐标 → 'unknown'。

#### 3.1.4 get_segment_list 扩展（5.B.3 搜索）

**位置**：`app/segment/service.py:123-125` 现有 `get_segment_list` 扩展（视为新增——按 Step 6 硬规定 2，内部抽取仍要给完整实现）

```python
from sqlalchemy.orm import Session
from sqlalchemy import func, cast
from geoalchemy2 import Geography
from app.segment.models import Segment, SegmentEffort  # 第二轮双审 B1-B1 修复：保留 entries_count outerjoin


def get_segment_list(
    db: Session,
    page: int,
    page_size: int,
    near_lat: float | None = None,
    near_lon: float | None = None,
    radius: float = 50000,  # 第二轮双审 B1-B2 修复：保留现有 default 50km，避免"传 lat/lon 不传 radius"行为静默回退
    search: str | None = None,
    city: str | None = None,
    difficulty: str | None = None,
) -> tuple[list[dict], int]:
    """
    赛段列表查询。支持搜索 + city + difficulty + 地理位置 多参数组合（AND 关系）。
    
    返回 (赛段列表, 总条数)，每条赛段带 entries（成绩记录数）—— 沿用现有 router.py:123 解构契约。
    第二轮双审 B1-B1 修复：必须保留 tuple + entries_count outerjoin，禁止改 → dict 破坏 router 契约。
    
    陷阱 #5（SQL 注入）：用 SQLAlchemy ORM ilike 参数化，**禁止 f-string 拼 SQL**。
    陷阱 #1（truthiness）：search='' 不应触发搜索 → `if search and len(search) >= 2`
    """
    # 构造 filter 列表（与现有 service.py:170-184 同模式）
    filters = []
    
    # 搜索（中文 ILIKE 不区分大小写）
    if search and len(search) >= 2:
        filters.append(Segment.name.ilike(f'%{search}%'))  # ORM 参数化，安全
    
    # 城市筛
    if city:
        filters.append(Segment.city == city)
    
    # 难度筛
    if difficulty:
        filters.append(Segment.difficulty == difficulty)
    
    # 地理位置筛（沿用现有逻辑：lat/lon 给了就启用，radius 用 default 50km）
    if near_lat is not None and near_lon is not None:
        filters.append(
            func.ST_DWithin(
                cast(Segment.reference_line, Geography),
                cast(
                    func.ST_SetSRID(func.ST_MakePoint(near_lon, near_lat), 4326),
                    Geography,
                ),
                radius,
            )
        )
    
    # 总条数（独立 count 查询，避免 GROUP BY 计数偏差，与现有 service.py:187-190 同模式）
    count_query = db.query(func.count(Segment.id))
    for f in filters:
        count_query = count_query.filter(f)
    total = count_query.scalar()
    
    # 分页查询：赛段 + 每个赛段成绩记录数（entries）
    entries_count = func.count(SegmentEffort.id).label("entries")
    query = (
        db.query(Segment, entries_count)
        .outerjoin(SegmentEffort, SegmentEffort.segment_id == Segment.id)
        .group_by(Segment.id)
    )
    for f in filters:
        query = query.filter(f)
    
    results = (
        query.order_by(Segment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    # 组装返回（沿用现有 service.py:211+ 风格：距离米→公里，附 entries）
    items = []
    for seg, entries in results:
        items.append({
            'id': seg.id,
            'name': seg.name,
            'distance_km': round((seg.distance or 0) / 1000, 2),
            'elevation_gain': seg.elevation_gain,
            'avg_gradient': seg.avg_gradient,
            'max_gradient': seg.max_gradient,  # v5 新增
            'difficulty': seg.difficulty,      # v5 新增
            'city': seg.city,                  # v5 新增
            'entries': entries,
            # ... 其他现有字段沿用
        })
    return items, total
```

**Router 改动**（`app/segment/router.py:103-111` `list_segments` 加 search / city / difficulty 参数）：

```python
from fastapi import Query

@router.get("", response_model=...)  # response_model 沿用现有
def list_segments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    near_lat: float | None = Query(None),
    near_lon: float | None = Query(None),
    radius: float | None = Query(None),
    search: str | None = Query(None, description="赛段名模糊搜索"),
    city: str | None = Query(None, description="按城市筛"),
    difficulty: str | None = Query(None, description="按难度筛"),
    db: Session = Depends(get_db),
    # 第二轮双审 B1-B3 修复 + Tim 拍：GET /api/segments **保持公开**（赛段目录是发现性内容，匿名可看），
    # 不加 Depends(get_current_user)，与现有 router.py:104-111 一致
):
    items, total = service.get_segment_list(
        db, page, page_size, near_lat, near_lon, radius,
        search=search, city=city, difficulty=difficulty,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}
```

#### 3.1.5 create_segment_from_activity（5.D.4 新增 service）

**位置**：`app/segment/service.py` 新增（admin 专用）

```python
from sqlalchemy import cast, func, text  # 第二轮双审 B1-B7 修复：cast 用于 ST_Intersection geography
from geoalchemy2 import Geography  # 第二轮双审 B1-B7 修复：与现有 service.py:24 风格一致（顶层 import 而非 .types）
from app.activity.models import Trackpoint


def create_segment_from_activity(
    db: Session,
    activity_id: int,
    name: str,
    start_index: int,
    end_index: int,
    city: str | None = None,
    difficulty: str | None = None,
    # 第三轮双审 R3-C2 修复：删 creator_user_id 参数 —— v5 segments 表无 created_by 列，
    # 参数无处可存。未来追溯创建者走 audit log（v6+），不在 segments 表落字段。
) -> Segment:
    """
    从 activity 的 trackpoints 提取子序列创建赛段（5.D.4 admin 专用）。
    
    步骤：
    1. 校验 start_index < end_index
    2. 取 trackpoints WHERE activity_id AND seq BETWEEN start_index AND end_index ORDER BY seq
    3. 算 distance / elevation_gain / elevation_loss / avg_gradient / max_gradient
    4. difficulty 推算（如未提供）
    5. city 推断（如未提供）
    6. 重复检测（reference_line 重叠 > 80% → ValueError）
    7. 写入 segments
    
    异常：
    - ValueError("起点必须在终点之前") if start >= end
    - ValueError("子序列点数不足") if len < 2
    - ValueError("赛段太短（< 1 公里）") if distance < 1000
    - ValueError("赛段已存在 id={existing.id}") if 重叠 > 80%
    
    ⚠️ 并发原子性（codex E1 I28 修复）：
    PostGIS 几何重叠不能用 UNIQUE 约束。两个 admin 同时调本函数同一段轨迹 →
    两次重复检测都没命中 → 两条重叠赛段同时入库。
    解法：进函数立即取 **PostgreSQL advisory transaction lock**（hashtext-based key），
    把整个 from-activity 创建路径串行化。admin 低频操作（< 50 次/天），串行无性能问题。
    锁会随事务结束自动释放。
    """
    if start_index >= end_index:
        raise ValueError("起点必须在终点之前")
    
    # codex E1 I28 修复：advisory lock 串行化 from-activity 创建路径
    # 把"重复检测 + 写入"作为一个原子段。任何并发请求都串行排队，避免重叠赛段同时入库。
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('segment-create-from-activity'))"))
    
    tps = (
        db.query(Trackpoint)
        .filter(
            Trackpoint.activity_id == activity_id,
            Trackpoint.seq >= start_index,
            Trackpoint.seq <= end_index,
        )
        .order_by(Trackpoint.seq)
        .all()
    )
    
    if len(tps) < 2:
        raise ValueError("子序列点数不足")
    
    # 算指标
    cumulative_dist = 0.0
    elevation_gain = 0.0
    elevation_loss = 0.0
    for i in range(1, len(tps)):
        d = _haversine_distance(
            tps[i - 1].latitude, tps[i - 1].longitude, tps[i].latitude, tps[i].longitude
        )
        cumulative_dist += d
        if tps[i].elevation is not None and tps[i - 1].elevation is not None:
            ele_diff = tps[i].elevation - tps[i - 1].elevation
            if ele_diff > 0:
                elevation_gain += ele_diff
            else:
                elevation_loss += abs(ele_diff)
    
    distance = cumulative_dist
    if distance < 1000:
        raise ValueError("赛段太短（< 1 公里）")
    
    avg_gradient = (
        (elevation_gain - elevation_loss) / distance * 100
        if distance > 0 else 0.0
    )
    max_gradient = calculate_max_gradient(tps)
    
    if difficulty is None:
        difficulty = calculate_difficulty(distance, elevation_gain, max_gradient)
    
    if city is None:
        from app.common.geo import infer_city_from_coords  # 第二轮双审 B2A-2 修复：抽到 common
        city = infer_city_from_coords(tps[0].latitude, tps[0].longitude)
    
    # reference_line LINESTRING WKT
    coords_str = ', '.join(f'{tp.longitude} {tp.latitude}' for tp in tps)
    reference_line_wkt = f'LINESTRING({coords_str})'
    
    # 重复检测（第二轮双审 B1-B7 修复：用 ST_HausdorffDistance 判轨迹相似度，
    # 不用 ST_Intersection + ST_Length —— 两 LINESTRING 求交可能返 GeometryCollection / POINT，
    # ST_Length 对非线串返 0 → 漏判重复）
    # ST_HausdorffDistance 单位是度（reference_line SRID 4326）；
    # 1 度 ≈ 111km，**< 0.0005 ≈ 55m** = 两条线整体距离很近 → 视为同一赛段
    HAUSDORFF_THRESHOLD = 0.0005  # 经验值，spec 实施时可调
    existing = (
        db.query(Segment)
        .filter(
            func.ST_HausdorffDistance(
                Segment.reference_line,
                func.ST_GeomFromText(reference_line_wkt, 4326),
            ) < HAUSDORFF_THRESHOLD
        )
        .first()
    )
    if existing:
        raise ValueError(f"赛段已存在 id={existing.id}（轨迹相似度过高，Hausdorff < {HAUSDORFF_THRESHOLD}°）")
    
    new_seg = Segment(
        name=name,
        description=None,
        distance=distance,
        elevation_gain=elevation_gain,
        elevation_loss=elevation_loss,
        avg_gradient=avg_gradient,
        max_gradient=max_gradient,
        difficulty=difficulty,
        city=city,
        start_lat=tps[0].latitude,
        start_lon=tps[0].longitude,
        end_lat=tps[-1].latitude,
        end_lon=tps[-1].longitude,
        reference_line=func.ST_GeomFromText(reference_line_wkt, 4326),
    )
    db.add(new_seg)
    db.commit()
    db.refresh(new_seg)
    return new_seg
```

### §3.2 即时反馈（5.C.1）

#### 3.2.1 get_my_effort_with_compare（新增 service）

**位置**：`app/segment/service.py` 新增

```python
from sqlalchemy import func
from app.segment.models import SegmentEffort
from app.activity.models import Activity  # codex E1 I27 修复：按 Activity.started_at 排序


def get_my_effort_with_compare(
    db: Session,
    segment_id: int,
    user_id: int,
) -> dict:
    """
    返回用户在某赛段的即时反馈对比数据。
    
    用现有索引 idx_efforts_segment_user_time（app/segment/models.py:124）。
    
    陷阱 #4（.one() vs .first()）：用 .first() / .scalar()，**不用 .one()**（NoResultFound 抛 500）
    
    ⚠️ 时序基准（codex E1 I27 修复）：
    "current / last" 必须按 **Activity.started_at**（实际骑行时间）排序，
    不按 SegmentEffort.created_at（DB 入库时间）。
    反例：用户先上传今天的骑行，再补传昨天的 GPX —— 用 created_at 会把昨天的标成 current。
    
    ⚠️ PR 计算与时序无关（第二轮双审 B1-A1 修复）：
    `pr_elapsed_time` 用 `MIN(elapsed_time)` 子查询，**不需要 join Activity 排序**——
    PR 是历史最佳，谁先创下不影响。`current_attempt_is_pr` 仅判 current.elapsed_time == pr_time，
    并列时 is_pr=True 表示用时持平 PR，不区分谁最先。
    
    返回字段：
    - current_attempt_elapsed_time: 这次（按骑行时间最新一次）用时
    - last_attempt_elapsed_time: 上次（按骑行时间倒数第二次）用时
    - pr_elapsed_time: 个人最佳用时
    - current_attempt_diff_to_last: 这次 - 上次（正数 = 变快，负数 = 变慢）
    - current_attempt_is_pr: 这次是否破 PR
    - is_first_attempt: 是否首次（无 last 对比）
    """
    efforts = (
        db.query(SegmentEffort)
        .join(Activity, SegmentEffort.activity_id == Activity.id)
        .filter(
            SegmentEffort.segment_id == segment_id,
            SegmentEffort.user_id == user_id,
        )
        .order_by(Activity.started_at.desc())  # codex E1 I27 修复：实际骑行时间，不是 DB 入库时间
        .limit(2)
        .all()
    )
    
    pr_time = (
        db.query(func.min(SegmentEffort.elapsed_time))
        .filter(
            SegmentEffort.segment_id == segment_id,
            SegmentEffort.user_id == user_id,
        )
        .scalar()
    )
    
    if not efforts:
        return {
            'current_attempt_elapsed_time': None,
            'last_attempt_elapsed_time': None,
            'pr_elapsed_time': None,
            'current_attempt_diff_to_last': None,
            'current_attempt_is_pr': False,
            'is_first_attempt': True,
        }
    
    current = efforts[0]
    last = efforts[1] if len(efforts) > 1 else None
    
    return {
        'current_attempt_elapsed_time': current.elapsed_time,
        'last_attempt_elapsed_time': last.elapsed_time if last else None,
        'pr_elapsed_time': pr_time,
        'current_attempt_diff_to_last': (
            last.elapsed_time - current.elapsed_time if last else None
        ),
        'current_attempt_is_pr': (current.elapsed_time == pr_time),
        'is_first_attempt': last is None,
    }
```

**Router 改动**：新增 endpoint `GET /api/segments/{segment_id}/efforts/me`（参 §5 API 接口章节详述）

### §3.3 功率曲线（5.C.2）

#### 3.3.1 calculate_power_curve（新增纯函数）

**位置**：`app/activity/power_zones.py` 同模块新增（已有 power_zones 计算，扩展功率曲线）

```python
def calculate_power_curve(
    trackpoints: list,
    windows_sec: list[int] | None = None,
) -> dict:
    """
    时长分桶最大平均功率曲线。
    
    Strava 行业标准 6 buckets：1s / 5s / 30s / 1min / 5min / 20min。
    
    算法：对每个 window 秒，找连续 N 个 trackpoints（N ≈ window）的最大平均功率。
    假设：trackpoints 大致 1Hz 采样（GPX 标准）。非均匀采样精度受影响。
    
    陷阱 #1（truthiness）：power=0 是合法值，**用 `if power is not None`，不用 `tp.power or 0` 兜底**
    （`tp.power or 0` 把 0 当 None 处理，反而吞掉合法 0 值）
    
    ⚠️ **不允许跨 activity 拼接 trackpoints**：本函数语义是"单次骑行内的滑窗最大平均"。
    跨 N 次骑行算 period 最佳，必须对每个 activity 独立调本函数，再取 per-window max——
    见 calculate_power_curve_from_activities。直接拼 list 会让"5min 最佳"出现跨日合并的虚假极值。
    
    参数：
        trackpoints: list[Trackpoint] 单个 activity 内、按 seq / created_at 升序，含 power（int|None，单位 W）
        windows_sec: list[int] 时长档位（秒）。None 用默认 6 档
    返回：
        dict[int → float] window_sec → max_avg_power_W
    """
    if windows_sec is None:
        windows_sec = [1, 5, 30, 60, 300, 1200]
    
    if not trackpoints:
        return {w: 0.0 for w in windows_sec}
    
    # 排序保险（如果调用方未排序）
    tps = sorted(trackpoints, key=lambda tp: tp.seq)
    powers = [tp.power if tp.power is not None else 0 for tp in tps]
    n = len(powers)
    
    if n == 0:
        return {w: 0.0 for w in windows_sec}
    
    # 累加和加速 O(n) per window
    prefix = [0.0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + powers[i]
    
    result = {}
    for window in windows_sec:
        if window > n:
            # 数据不足 window → 用全部数据平均
            result[window] = prefix[n] / n if n > 0 else 0.0
            continue
        
        max_avg = 0.0
        for i in range(n - window + 1):
            avg = (prefix[i + window] - prefix[i]) / window
            if avg > max_avg:
                max_avg = avg
        result[window] = max_avg
    
    return result
```

**单元测试要求**（≥ 5 case）：
- 空 trackpoints → 全 0
- 全 None power → 全 0
- 单点 → window=1 等于该点，其他 window 等于该点（数据不足走 fallback）
- 标准 200W 平均 → 全 buckets 接近 200
- 极端高瓦数 1200W spike 1s → window=1 ~1200, window=5 ~240（被平均稀释）
- power=0 合法（休息段）不被当 None

#### 3.3.1.1 calculate_power_curve_from_activities（新增纯函数 / codex E1 C6 反馈环级修复）

**位置**：`app/activity/power_zones.py` 同模块新增。

**目的**：跨 N 个 activity 算"period 内最大平均功率曲线"——对每个 activity 独立算 curve，取所有 activity 的 per-window max。**禁止跨 activity 拼接 trackpoints**（破坏"5min 最佳"语义）。

```python
def calculate_power_curve_from_activities(
    activities_trackpoints: list[list],
    windows_sec: list[int] | None = None,
) -> dict:
    """
    跨 N 个 activity 的时长分桶最大平均功率曲线。
    
    算法：对每个 activity 独立 calculate_power_curve，再对每个 window 取所有 activity 的 max。
    
    codex E1 C6 修复：原跨 activity 拼接 trackpoints 的算法语义错误
    （activity A 末尾 + activity B 开头算 5min 平均会失真）。
    
    参数：
        activities_trackpoints: list[list[Trackpoint]]，每个内层 list 是**单 activity** 的 trackpoints
        windows_sec: list[int] 时长档位（秒）。None 用默认 6 档
    返回:
        dict[int → float] window_sec → max_avg_power_W（取所有 activity 的 max）
    """
    if windows_sec is None:
        windows_sec = [1, 5, 30, 60, 300, 1200]
    
    if not activities_trackpoints:
        return {w: 0.0 for w in windows_sec}
    
    result = {w: 0.0 for w in windows_sec}
    for tps in activities_trackpoints:
        if not tps:
            continue
        curve = calculate_power_curve(tps, windows_sec)
        for w in windows_sec:
            if curve[w] > result[w]:
                result[w] = curve[w]
    
    return result
```

**单元测试要求**（≥ 4 case）：
- 空 list → 全 0
- 单 activity（list of 1）→ 等价 calculate_power_curve
- 2 activity，A 5min 高于 B → 该 window 取 A
- 2 activity，A window=5 高 / B window=300 高 → 各 window 各取最高（不同 activity 可在不同 window 称王）

#### 3.3.2 service 层包装 + Redis 缓存

**位置**：`app/user/service.py` 或 `app/activity/service.py` 新增（具体放哪 spec 实施时拍，建议 user.service 因为是用户主动查询）

```python
import json
from datetime import datetime, timedelta, timezone
from app.queue import redis_conn as REDIS_CLIENT  # 第三轮双审 R3-C1 修复：Sprint 0 task 0.8 单一连接源，禁止 user→strava 反向依赖
from app.activity.models import Activity, Trackpoint
from app.activity.power_zones import calculate_power_curve_from_activities  # codex E1 C6 修复：跨 activity 用 _from_activities 不直接拼

CACHE_TTL_SEC = 3600  # 1 小时


def get_user_power_curve(
    db: Session,
    user_id: int,
    period: str = 'this_month',
) -> dict:
    """
    用户功率曲线（按 period 切片）+ Redis 缓存。
    
    period 枚举：'this_month' / 'last_month' / 'this_year' / 'last_year' / 'all_time'
    
    缓存 key: power_curve:user_{user_id}:period_{period}，TTL 1h
    用户上传新 activity 时 service.invalidate_power_curve_cache(user_id) 清缓存。
    
    陷阱 #2（naive vs aware datetime）：用 datetime.now(timezone.utc)，不用 datetime.utcnow()
    """
    # 1. Cache lookup
    cache_key = f'power_curve:user_{user_id}:period_{period}'
    cached = REDIS_CLIENT.get(cache_key)
    if cached:
        # redis-py 7+ 默认返 bytes（陷阱 #5）
        return json.loads(cached.decode() if isinstance(cached, bytes) else cached)
    
    # 2. 计算 period 时间范围（第三轮双审 R3-C3 修复：CLAUDE.md "时区"硬约定 —— 本周/本月按北京时间 UTC+8）
    BJ_TZ = timezone(timedelta(hours=8))
    now_utc = datetime.now(timezone.utc)
    now_bj = now_utc.astimezone(BJ_TZ)
    if period == 'this_month':
        start_bj = now_bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = start_bj.astimezone(timezone.utc)
        end = now_utc
    elif period == 'last_month':
        first_this_month_bj = now_bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_this_month_bj.astimezone(timezone.utc)
        if first_this_month_bj.month == 1:
            start_bj = first_this_month_bj.replace(year=first_this_month_bj.year - 1, month=12)
        else:
            start_bj = first_this_month_bj.replace(month=first_this_month_bj.month - 1)
        start = start_bj.astimezone(timezone.utc)
    elif period == 'this_year':
        start_bj = now_bj.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        start = start_bj.astimezone(timezone.utc)
        end = now_utc
    elif period == 'last_year':
        first_this_year_bj = now_bj.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_this_year_bj.astimezone(timezone.utc)
        start_bj = first_this_year_bj.replace(year=first_this_year_bj.year - 1)
        start = start_bj.astimezone(timezone.utc)
    elif period == 'all_time':
        start = datetime(1970, 1, 1, tzinfo=timezone.utc)
        end = now_utc
    else:
        raise ValueError(f"unknown period: {period}")
    
    # 3. 查 period 内所有 completed activities 的 trackpoints（按 activity 分组，codex E1 C6）
    activities = (
        db.query(Activity.id)
        .filter(
            Activity.user_id == user_id,
            Activity.status == 'completed',
            Activity.started_at >= start,
            Activity.started_at < end,
        )
        .all()
    )
    
    # 按 activity_id 分组（禁止跨 activity 拼接 trackpoints）
    activities_trackpoints = []
    for act in activities:
        tps = (
            db.query(Trackpoint)
            .filter(Trackpoint.activity_id == act.id)
            .order_by(Trackpoint.seq)
            .all()
        )
        activities_trackpoints.append(tps)
    
    # 4. 计算（每 activity 独立算后取 max）
    curve = calculate_power_curve_from_activities(activities_trackpoints)
    result = {
        'period': period,
        'buckets': curve,  # {1: 850.0, 5: 720.0, 30: 320.0, ...}
    }
    
    # 5. Cache SET
    REDIS_CLIENT.setex(cache_key, CACHE_TTL_SEC, json.dumps(result))
    return result


def invalidate_power_curve_cache(user_id: int) -> None:
    """用户上传新 activity 后清缓存。"""
    pattern = f'power_curve:user_{user_id}:*'
    for key in REDIS_CLIENT.scan_iter(match=pattern):
        REDIS_CLIENT.delete(key)
```

**Worker 集成**（`app/activity/worker.py` 或同等位置，activity processing 完成后调用）：

```python
# 在 activity processing 完成（status='completed'）后调用
from app.user.service import invalidate_power_curve_cache

invalidate_power_curve_cache(activity.user_id)
```

**性能要求（PRD 验收）**：
- 100k trackpoints 算 calculate_power_curve < 500ms（O(n) per window × 6 windows = 600k 次操作）
- Redis cache 命中率 > 80%（连续两次同 user / period 请求）
- API p95 < 300ms（cache hit 路径）

---

## §3 核心逻辑（后半：progress detector + 热图 + 看他人主页 + admin + worker）

**分区隔离原则**（Tim 2026-04-28 拍）：每个子任务标**模块归属 / 隔离边界**。跨主轴只走 service public API，**禁止跨模块 import 内部辅助函数 / 禁止跨主轴数据表污染**。

**前置依赖（Sprint 0 task-0.1 必先完成）**：本节同 §3 前半，假设 datetime 栈内统一 aware UTC（参 §8.1）。

### §2 修订补遗：notifications 表加 payload 字段

§2.3 现有 notifications 字段（event_type / segment_id / activity_id / effort_id / elapsed_time / rank / rival_user_id / expires_at / created_at）是为 PR/KOM 类设计的——progress 类（5min 功率涨 5W）的 (current_value / prev_value / delta) 塞不进现有字段语义。

**修订**：notifications 表加 `payload` JSONB NULL 字段。
- progress 类 type（progress_5min_power / progress_segment_pb / progress_monthly_summary）用 payload 存数据
- PR/KOM 类沿用现有字段（payload 留 NULL）

迁移加（追加到 §2.5 Alembic upgrade）：
```python
# === 5.5 notifications 加 payload JSONB（§2 修订补遗）===
op.add_column(
    'notifications',
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
)
```

downgrade 加：
```python
op.drop_column('notifications', 'payload')
```

**追加（codex E1 C13：progress 幂等闸门）**：notifications 加部分唯一索引兜底 worker 重试 / 并发重复插入。

迁移 upgrade 追加：
```python
# === 5.6 notifications 部分唯一索引：progress 类幂等闸门（codex E1 C13）===
# progress_* 类 type 的 (activity_id, event_type) UNIQUE；PR/KOM 类不受影响（用 effort_id 做幂等）
op.create_index(
    'uniq_progress_notification_per_activity',
    'notifications',
    ['activity_id', 'event_type'],
    unique=True,
    postgresql_where=sa.text("event_type LIKE 'progress_%'"),
)
```

downgrade 追加：
```python
op.drop_index('uniq_progress_notification_per_activity', 'notifications')
```

**⚠ §2.5 主迁移文件顶部 import 必须含**（Cluster 3 陷阱：alembic 缺 postgresql import 会 NameError）：
```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  # ⚠ JSONB 字段 + 部分唯一索引必需
```

### §3.4 progress detector（5.C.3）

**模块归属**：`app/notification/progress_detector.py`（新建，跟 v3/v4 `app/notification/detector.py:45-94` PR/KOM 检测器同模式）。

**隔离边界**：
- 输入：调 `app/activity/power_zones.py` 的 calculate_power_curve（A 档纯函数，跨模块 OK）+ 调 `app/activity/models.py` Trackpoint / Activity（ORM 模型读取 OK）
- 输出：写 notifications 表（沿用现有 + payload 字段）
- **禁止**：调 segment 模块内部 / 写 segment_efforts / 跨进 admin 模块

**完整实现**：

```python
# app/notification/progress_detector.py
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.activity.models import Activity, Trackpoint
from app.notification.models import Notification
from app.user.models import User
from app.activity.power_zones import calculate_power_curve, calculate_power_curve_from_activities

# 进步阈值（PRD Q6 路径 C Tim 拍）
PROGRESS_5MIN_POWER_THRESHOLD_W = 5


def detect_5min_power_progress(
    db: Session,
    user_id: int,
    current_activity_id: int,
) -> Notification | None:
    """
    检测用户上传新 activity 后的 5min 最大平均功率进步。
    
    逻辑：
    1. 算 current activity 的 5min max avg power
    2. 取上月（last_month period）该用户 5min max avg power 作 baseline
    3. delta = current - baseline，如果 >= 5W → 写 notification
    4. 否则返回 None（不推送）
    
    陷阱 #1（truthiness）：阈值用 `>= PROGRESS_5MIN_POWER_THRESHOLD_W`，不用 `if delta`（delta=0 也是 falsy）
    陷阱 #2（naive vs aware datetime）：datetime.now(timezone.utc) 不用 datetime.utcnow()
    """
    # 1. 当前 activity 5min 功率
    current_tps = (
        db.query(Trackpoint)
        .filter(Trackpoint.activity_id == current_activity_id)
        .order_by(Trackpoint.seq)
        .all()
    )
    current_curve = calculate_power_curve(current_tps, windows_sec=[300])
    current_5min = current_curve[300]
    
    if current_5min <= 0:
        return None  # 当前 activity 无功率数据，不检测
    
    # 2. 上月 baseline（第三轮双审 R3-C3 修复：按北京时间 UTC+8 划月，CLAUDE.md 时区约定）
    BJ_TZ = timezone(timedelta(hours=8))
    now_bj = datetime.now(timezone.utc).astimezone(BJ_TZ)
    first_this_month_bj = now_bj.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if first_this_month_bj.month == 1:
        last_month_start_bj = first_this_month_bj.replace(
            year=first_this_month_bj.year - 1, month=12
        )
    else:
        last_month_start_bj = first_this_month_bj.replace(
            month=first_this_month_bj.month - 1
        )
    # 转回 UTC 用于 DB 查询（Activity.started_at Sprint 0 task 0.1 后是 tz-aware UTC）
    first_this_month = first_this_month_bj.astimezone(timezone.utc)
    last_month_start = last_month_start_bj.astimezone(timezone.utc)
    
    # codex E1 C6 修复：按 activity 分组算 baseline，禁止跨 activity 拼接
    baseline_activities = (
        db.query(Activity.id)
        .filter(
            Activity.user_id == user_id,
            Activity.status == 'completed',
            Activity.started_at >= last_month_start,
            Activity.started_at < first_this_month,
        )
        .all()
    )
    
    if not baseline_activities:
        return None  # 上月无 activity，无 baseline
    
    baseline_acts_tps = []
    for act in baseline_activities:
        tps = (
            db.query(Trackpoint)
            .filter(Trackpoint.activity_id == act.id)
            .order_by(Trackpoint.seq)
            .all()
        )
        baseline_acts_tps.append(tps)
    
    baseline_curve = calculate_power_curve_from_activities(baseline_acts_tps, windows_sec=[300])
    baseline_5min = baseline_curve[300]
    
    # 第三轮双审 R3-I1（codex E1 漏抓 / 强制检查清单 #6 边界）：上月无功率数据守卫
    # 反例：上月所有骑行无功率（GPX 无 power 流）→ baseline_5min=0 → current=200 → delta=200
    # → 误推送"涨 200W"假阳性。从无到有不算"进步 5W+"。
    if baseline_5min <= 0:
        return None
    
    # 3. 阈值检测
    delta = current_5min - baseline_5min
    if delta < PROGRESS_5MIN_POWER_THRESHOLD_W:
        return None
    
    # 4. 静音用户跳过（codex E1 I26：PRD 5.C.3 拍 mute_notifications 关闭进步推送）
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.mute_notifications:
        return None
    
    # 5. 幂等检查（codex E1 C13：worker 重试 / 并发会重复插入 progress 通知）
    # 沿用 (activity_id, event_type) 幂等键（§2.3 加部分唯一索引 DB 兜底）
    existing = db.query(Notification).filter(
        Notification.activity_id == current_activity_id,
        Notification.event_type == 'progress_5min_power',
    ).first()
    if existing:
        return None  # 已存在，幂等跳过
    
    # 6. 写 notification（用 payload JSONB 存数据，§2 修订补遗）
    notification = Notification(
        user_id=user_id,
        event_type='progress_5min_power',
        activity_id=current_activity_id,
        payload={
            'current_value': round(current_5min, 1),
            'prev_value': round(baseline_5min, 1),
            'delta': round(delta, 1),
            'window_sec': 300,
            'baseline_period': 'last_month',
        },
    )
    db.add(notification)
    try:
        db.commit()
    except IntegrityError:
        # 并发场景兜底：另一个 worker 同时写入同一 (activity_id, event_type)
        # 部分唯一索引 uniq_progress_notification_per_activity 触发约束
        db.rollback()
        return None
    return notification
```

**Worker 集成**（第二轮双审 B2B-5 修复：明确 hook 位置）：

实施前先 grep 找 status='completed' 赋值点：
```bash
grep -n "status.*completed\|status\s*=\s*['\"]completed" app/activity/worker.py app/activity/service.py
```

确认 hook 落在 worker.py 解析成功路径（即将 commit 之前），不在 status='processing' 切换点、不在 'failed' 路径：

```python
# app/activity/worker.py（hook 落在 status='completed' 赋值后、db.commit 前）
from app.notification.progress_detector import detect_5min_power_progress
from app.user.service import invalidate_power_curve_cache

# activity.status = 'completed' 之后立即触发
detect_5min_power_progress(db, activity.user_id, activity.id)
invalidate_power_curve_cache(activity.user_id)
# 然后 db.commit()
```

**单元测试**（≥ 5 case）：上月无 activity → None / 当前无功率 → None / 涨 4W → None / 涨 5W → notification / 涨 -10W（退步）→ None

### §3.5 个人骑行热图（5.A.1）

**模块归属**：`app/user/service.py` 新增 + `app/user/router.py` 加 endpoint + `app/user/models.py:32-93` 加 city 字段（防火墙破例 1 处）。

**隔离边界**：
- 输入：用 ORM 关系查 Activity（user_id 索引）+ activities.simplified_track（已有 JSONB list of [lon, lat]）—— **纯 Python 端 JSONB 聚合，不调 PostGIS ST_Collect**（第二轮双审 B2A-3 修复：与 §1.3 第 6 条保持一致）
- **禁止**：调 segment / notification 模块；不写其他主轴的表
- 缓存：Redis（沿用 v4 全局 `_redis` 客户端模式）

**完整实现**：

```python
# app/user/service.py 新增
import json
from datetime import datetime, timedelta, timezone  # 第二轮双审 B2A-1/B2B-1 修复：本块行 1819 用了 timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.user.models import User
from app.activity.models import Activity
from app.common.geo import infer_city_from_coords  # 第二轮双审 B2A-2 修复：抽到 common 避免 user→segment 反向依赖
from app.queue import redis_conn as REDIS_CLIENT  # 第三轮双审 R3-C1 修复：Sprint 0 task 0.8 单一连接源，禁止 user→strava 反向依赖

HEATMAP_CACHE_TTL_SEC = 3600


def get_user_heatmap(
    db: Session,
    user_id: int,
    city: str,
) -> dict:
    """
    返回用户在指定城市的骑行热图（GeoJSON multipoint 聚合）。
    
    逻辑：
    1. Redis cache lookup
    2. 查该用户所有 activity（status=completed）的 simplified_track 起点在 city 范围内的
    3. 提取所有 simplified_track 点位 → multipoint 聚合
    4. Redis SET TTL 1h
    
    陷阱 #5（redis-py 返 bytes）：cached.decode() if isinstance(cached, bytes) else cached
    """
    cache_key = f'heatmap:user_{user_id}:city_{city}'
    cached = REDIS_CLIENT.get(cache_key)
    if cached:
        return json.loads(
            cached.decode() if isinstance(cached, bytes) else cached
        )
    
    # 查该用户的 activities（按 simplified_track 起点城市筛）
    activities = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.status == 'completed',
            Activity.simplified_track.isnot(None),
        )
        .all()
    )
    
    # 过滤起点在 city 范围内的（从 simplified_track[0] 提起点，因 activities 表无 start_lat/lon 字段）
    filtered = [
        a for a in activities
        if a.simplified_track and len(a.simplified_track) > 0
        and infer_city_from_coords(
            a.simplified_track[0].get('lat'),
            a.simplified_track[0].get('lon'),
        ) == city
    ]
    
    # 聚合所有 simplified_track 点
    points = []
    for a in filtered:
        track = a.simplified_track  # JSONB list of {lat, lon, ele}
        if not track:
            continue
        for pt in track:
            if pt.get('lat') is not None and pt.get('lon') is not None:
                points.append([pt['lon'], pt['lat']])  # GeoJSON 顺序 [lon, lat]
    
    result = {
        'city': city,
        'multipoint': {
            'type': 'MultiPoint',
            'coordinates': points,
        },
        'activity_count': len(filtered),
    }
    
    REDIS_CLIENT.setex(cache_key, HEATMAP_CACHE_TTL_SEC, json.dumps(result))
    return result


def update_user_city(db: Session, user_id: int, city: str) -> User:
    """
    更新用户主城市（settings 手动改 + 失效热图缓存）。
    
    陷阱 #4（.one() vs .first()）：用 .first() + 显式抛 ValueError
    """
    valid_cities = {'beijing', 'shanghai', 'hangzhou', 'shenzhen',
                    'chengdu', 'taiyuan', 'unknown'}
    if city not in valid_cities and city is not None:
        raise ValueError(f"invalid city: {city}")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"user not found: {user_id}")
    
    user.city = city
    db.commit()
    
    # 失效该用户所有 city 的热图缓存
    pattern = f'heatmap:user_{user_id}:*'
    for key in REDIS_CLIENT.scan_iter(match=pattern):
        REDIS_CLIENT.delete(key)
    
    return user
```

**首次上传 GPX 自动推断主城市**（worker 集成，activity status='completed' 切换点）：

```python
# 在 detect_5min_power_progress 调用旁，**同一事务内**走原子检查避免并发重复触发
# 第三轮双审 R3-Minor 修复：用 SELECT FOR UPDATE 锁住 user 行，
# 保证多 activity 并发解析时只有一次 city 推断 commit
from sqlalchemy.orm import Session

user = (
    db.query(User)
    .filter(User.id == activity.user_id)
    .with_for_update()  # 行锁，并发请求串行
    .first()
)
if user.city is None and activity.simplified_track and len(activity.simplified_track) > 0:
    pt = activity.simplified_track[0]
    if pt.get('lat') is not None and pt.get('lon') is not None:
        user.city = infer_city_from_coords(pt.get('lat'), pt.get('lon'))
        db.commit()
```

**性能 / 缓存**：500 用户 × 30 activity × 80 simplified 点 = 1.2M 点。聚合后端单次 < 1s（按 user_id 索引筛）。Redis 缓存 TTL 1h。

### §3.6 看他人主页（5.A.2）

**模块归属**：`app/user/service.py` 新增 + `app/user/router.py` 加 GET /api/users/{user_id}/profile。

**隔离边界**：
- 输入：查 users 表 + activities 聚合统计（COUNT / SUM）
- **严格字段过滤**：只暴露 PRD 拍过的公开字段，**禁止**返回 efforts / activities 列表 / heatmap / 内部 token
- D-P08 红线：看自己 ID 跟看他人返回**字段一致**

**完整实现**：

```python
# app/user/service.py 新增
from datetime import datetime, timedelta, timezone  # 第二轮双审 B2A-1/B2B-1 修复：本块用了 timedelta
from sqlalchemy import func
from app.user.models import User
from app.activity.models import Activity


# 响应 keys 白名单（**第二轮双审 B2B-3 修复：改名 RESPONSE_KEYS 避免与 User model 字段混淆**）
# 含 4 个 user 表列字段（nickname/avatar_url/city/ftp/bike_type）+ 4 个 service 层聚合字段
# （total_distance_km / total_elevation_m / activity_count / current_month_summary）
# v5 简化：默认全公开（D-P08 红线"看自己 = 看他人"），未来 v6 加 privacy_settings JSONB 控制
RESPONSE_KEYS = {
    'id', 'nickname', 'avatar_url', 'city', 'ftp', 'bike_type',
    'total_distance_km', 'total_elevation_m', 'activity_count',
    'current_month_summary',
}


def get_user_profile_for_others(
    db: Session,
    target_user_id: int,
    requester_user_id: int,  # v6 隐私开关预留（D-P08 红线下 v5 不区分 self/others，参数仅占位）
) -> dict:
    """
    返回他人用户主页字段（严格只读，D-P08 红线）。
    
    返回字段（PRD 5.A.2 拍）：
    - id / nickname / avatar_url / city / ftp / bike_type
    - total_distance_km（累计公里）
    - total_elevation_m（累计爬升）
    - activity_count
    - current_month_summary: { distance_km, elevation_m, avg_power_w }
    
    严格不返回：efforts / activities / heatmap / strava_* / openid / mute_notifications / 任何 token
    
    异常：target_user_id 不存在 → ValueError("用户不存在")
    """
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise ValueError("用户不存在")
    
    # 累计统计（聚合查询）
    totals = (
        db.query(
            func.coalesce(func.sum(Activity.distance), 0).label('total_distance'),
            func.coalesce(func.sum(Activity.elevation_gain), 0).label('total_elevation'),
            func.count(Activity.id).label('activity_count'),
        )
        .filter(
            Activity.user_id == target_user_id,
            Activity.status == 'completed',
        )
        .first()
    )
    
    # 当月汇总（按 UTC+8 北京时间算"本月"，CLAUDE.md 时区约定）
    now_bj = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    )
    first_of_month_bj = now_bj.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    first_of_month_utc = first_of_month_bj.astimezone(timezone.utc)
    
    current_month = (
        db.query(
            func.coalesce(func.sum(Activity.distance), 0).label('m_distance'),
            func.coalesce(func.sum(Activity.elevation_gain), 0).label('m_elevation'),
            func.coalesce(func.avg(Activity.avg_power), 0).label('m_avg_power'),
        )
        .filter(
            Activity.user_id == target_user_id,
            Activity.status == 'completed',
            Activity.started_at >= first_of_month_utc,
        )
        .first()
    )
    
    raw_response = {
        'id': target.id,
        'nickname': target.nickname,
        'avatar_url': target.avatar_url,
        'city': target.city,
        'ftp': target.ftp,
        'bike_type': target.bike_type,
        'total_distance_km': round((totals.total_distance or 0) / 1000.0, 1),
        'total_elevation_m': round(totals.total_elevation or 0, 1),
        'activity_count': totals.activity_count or 0,
        'current_month_summary': {
            'distance_km': round((current_month.m_distance or 0) / 1000.0, 1),
            'elevation_m': round(current_month.m_elevation or 0, 1),
            'avg_power_w': round(current_month.m_avg_power or 0, 1),
        },
    }
    # 第三轮双审 R3-I3 修复：RESPONSE_KEYS 白名单实际生效。
    # 防止未来手滑加 'strava_access_token' / 'openid' 等字段时静默泄漏（D-P08 红线靠机制不靠自觉）。
    return {k: v for k, v in raw_response.items() if k in RESPONSE_KEYS}
```

**测试覆盖**（≥ 4 case）：
- 看自己 vs 看他人 字段集合**完全一致**（防字段泄漏）
- 不存在 user_id → 404
- 严格字段过滤（不含 strava_* / openid / mute_notifications / token）
- 累计统计准确（活动数 + 距离 + 爬升）

### §3.7 admin 工具系列（5.D.1 / 5.D.2 / 5.D.3 / 5.D.5）

**模块归属**：
- 5.D.1 候选池脚本：`scripts/generate_curation_pool.py`（独立 offline 脚本，**不在 app/ 内**，定时跑）
- 5.D.2 AI 草稿生成：`app/agent/segment_writer.py`（**新建 app/agent/ 模块**，按 ADR-009 + PRD 5.B.2 留接口）+ admin endpoint
- 5.D.3 批量管理：admin endpoint 复用 `app/segment/service.py` public API
- 5.D.4 from-activity：已在 §3.1.5 写完
- 5.D.5 H5 admin：**独立前端项目**（不在 velo backend 仓库内，新建 `admin-h5/` 同级目录或独立 repo）

**隔离边界**：
- admin 路由前缀 `/api/admin/*`（新增）—— 跟用户端 `/api/*` 隔离
- admin endpoint 必须 `is_admin` dependency（沿用 users.is_admin 字段）
- app/agent/ 模块：调 DeepSeek API（OpenAI 兼容 SDK）+ 写 segment_ai_drafts 表，**禁止反向 import 业务代码**（参 ADR-009）

#### 3.7.1 候选池脚本（5.D.1）

```python
# scripts/generate_curation_pool.py
import logging
from collections import defaultdict
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.segment.models import Segment, SegmentEffort  # ORM 模型读取 OK
# 注：本脚本在 scripts/ 不在 app/，但调 ORM models 读取数据是合理的（独立读取层）

logger = logging.getLogger(__name__)


def calculate_pool_score(
    attempts_count: int,
    kom_changes: int,
    difficulty_balance_factor: float,
) -> float:
    """
    候选池排序分（PRD Q5 拍：热度前 100 + 难度区间分布平衡）
    
    分数 = attempts_count * 1.0 + kom_changes * 5.0 + difficulty_balance_factor * 50
    （加权值实施时按 5.D.3 批量管理结果调）
    """
    return (
        attempts_count * 1.0
        + kom_changes * 5.0
        + difficulty_balance_factor * 50.0
    )


def generate_curation_pool(db: Session, top_n: int = 100) -> int:
    """
    脚本主函数。计算每条 segment 的 pool_score，UPSERT 写入 segment_curation_pool top 100。
    幂等：重跑不重复（UPSERT by segment_id UNIQUE）。
    
    定时跑：每周一次（cron 在部署时配，spec 实施时拍具体 cron schedule）
    
    返回：写入的赛段数
    """
    from app.segment.models import Segment  # SegmentCurationPool 待 spec 实施时定义 ORM 模型
    from sqlalchemy.dialects.postgresql import insert
    
    # 1. 算每条 segment 的 attempts_count + kom_changes
    segments = db.query(Segment).all()
    
    # 暂用伪代码示意（具体 SQL 实施时拍）：
    # attempts_count: COUNT(segment_efforts WHERE segment_id)
    # kom_changes: 历史 KOM 变更次数（需扫 segment_efforts 时间序列找首位变化）
    # difficulty_balance_factor: 1.0 - (该城该难度赛段已选数 / 目标 5-8 条)，避免某城某难度过度集中
    
    scores = []
    for seg in segments:
        attempts = (
            db.query(SegmentEffort)
            .filter(SegmentEffort.segment_id == seg.id)
            .count()
        )
        # kom_changes 简化：用 distinct user 数 - 1 作 proxy（实施时拍精确算法）
        kom_changes = (
            db.query(SegmentEffort.user_id)
            .filter(SegmentEffort.segment_id == seg.id)
            .distinct()
            .count()
            - 1
        )
        difficulty_balance_factor = 1.0  # 简化版，实施时按城市/难度分布调
        score = calculate_pool_score(attempts, kom_changes, difficulty_balance_factor)
        scores.append((seg.id, score, 'high_attempts'))
    
    # 排序取 top N
    scores.sort(key=lambda x: x[1], reverse=True)
    top = scores[:top_n]
    
    # UPSERT 写 segment_curation_pool（pool_score / pool_reason 更新；selected_for_v5 不动）
    written = 0
    for seg_id, score, reason in top:
        # 用 INSERT ... ON CONFLICT 实现幂等
        # SegmentCurationPool 模型 spec 实施时按 §2.2 表定义建
        # stmt = insert(SegmentCurationPool).values(...).on_conflict_do_update(...)
        # db.execute(stmt)
        written += 1
    
    db.commit()
    logger.info(f"generate_curation_pool: wrote {written} segments")
    return written


def main():
    db = SessionLocal()
    try:
        generate_curation_pool(db, top_n=100)
    finally:
        db.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
```

#### 3.7.2 AI 草稿生成（5.B.2 + 5.D.2）

**模块归属**：`app/agent/segment_writer.py`（新建模块，按 ADR-009 留接口架构）

**隔离边界**：
- 调 DeepSeek API（OpenAI 兼容 SDK，Tim 2026-04-29 拍）
- 写 segment_ai_drafts 表（v5 新建）
- **禁止**：反向 import 业务代码（segment / activity / user 模块的 service）—— 通过 spec 提供的赛段属性 dict 输入，不进业务逻辑

```python
# app/agent/segment_writer.py（新建）
"""
AI 赛段介绍草稿生成器（5.B.2）。
v5 留接口不实现 RAG / 不上向量检索，仅直连 DeepSeek API（OpenAI 兼容 SDK）。
未来 v7+ 扩展 RAG 时此模块为入口；切其他厂商模型把 base_url + model 名改一下即可。
"""
import logging
from openai import OpenAI  # DeepSeek 兼容 OpenAI Python SDK
from app.config import settings

logger = logging.getLogger(__name__)
_client = (
    OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    if settings.DEEPSEEK_API_KEY else None
)


PROMPT_TEMPLATE = """你是 velo 平台的本地骑友写手。给一条赛段写**活人感介绍**：

赛段属性：
- 名称：{name}
- 城市：{city}
- 距离：{distance_km} km
- 总爬升：{elevation_gain_m} m
- 最大坡度：{max_gradient_pct}%
- 难度：{difficulty}

调性要求（必须遵守）：
- **单条 50-100 字**，超过算违规
- **元素稀疏**：1-2 个细节（避雷 / 氛围 / 路面 等），不堆砌 4 个梗
- 满足 RUBRIC-CONTENT 4 条至少 3 条：具体细节 / 避雷建议 / 本地黑话 / 主观感受
- 禁用词：超震撼 / 用户体验 / 解锁 / AI 智能开头 / 所有运动爱好者 等

输出：直接给草稿正文，不加引号 / 不解释 / 不署名。
"""


def generate_segment_draft(
    segment_props: dict,
) -> str:
    """
    调 Claude API 生成赛段活人感介绍草稿。
    
    参数：
        segment_props: dict 含 name / city / distance_km / elevation_gain_m / max_gradient_pct / difficulty
    返回：
        str 50-100 字活人感草稿；调用失败返回空字符串（不抛异常打断业务流）
    
    陷阱 #9（API 嵌套）：response 字段用 .get() 链 / 显式存在性检查
    """
    if _client is None:
        logger.warning("DEEPSEEK_API_KEY not configured, skip generate")
        return ""
    
    prompt = PROMPT_TEMPLATE.format(**segment_props)
    
    try:
        response = _client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,  # 默认 'deepseek-chat'，env 可覆盖
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )
        # 嵌套字段安全访问（陷阱 #9）
        choices = getattr(response, 'choices', None)
        if not choices:
            return ""
        msg = getattr(choices[0], 'message', None)
        if not msg:
            return ""
        text = getattr(msg, 'content', None)
        if not text:
            return ""
        return text.strip()
    except Exception as e:
        logger.error(f"generate_segment_draft failed: {e}")
        return ""
```

#### 3.7.3 AI 草稿 RQ 异步载体（codex E1 C10 修复）

**位置**：`app/agent/tasks.py` 新建（RQ task 入口，与现有 `app/activity/worker.py` 等价分模块）

**为什么需要**：
- `generate_segment_draft` 调 Claude API 单次 ~3-8s，admin endpoint 不能同步阻塞
- 两条调用入口（POST generate / PATCH curation-pool selected=true）必须**复用同一 RQ task 不复制**
- RQ 失败重试、worker 崩溃恢复都走标准基础设施（沿用 v0/v4）

```python
# app/agent/tasks.py（新建）
"""
AI 草稿 RQ 异步任务入口。
所有 admin 触发 AI 草稿生成的入口都 enqueue 这个 task，禁止同步调用 generate_segment_draft。
"""
import logging
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal  # 第二轮双审 B3B-1 修复：真实路径 app.database 不是 app.db
from app.segment.models import Segment, SegmentAiDraft
from app.agent.segment_writer import generate_segment_draft

logger = logging.getLogger(__name__)


def generate_segment_draft_task(segment_id: int) -> None:
    """
    RQ async task：给指定 segment 生成 AI 草稿并 UPSERT segment_ai_drafts。
    
    幂等：UPSERT by segment_id UNIQUE（强制检查清单 #2）。
    失败：generate_segment_draft 返空字符串 → 不 UPSERT，记 logger（不抛异常打断 RQ）。
    """
    db = SessionLocal()
    try:
        seg = db.query(Segment).filter(Segment.id == segment_id).first()
        if not seg:
            logger.error(f"generate_segment_draft_task: segment_id={segment_id} 不存在，skip")
            return
        
        segment_props = {
            'name': seg.name,
            'city': seg.city or '未知',
            'distance_km': round((seg.distance or 0) / 1000, 1),
            'elevation_gain_m': int(seg.elevation_gain or 0),
            'max_gradient_pct': round(seg.max_gradient or 0, 1),
            'difficulty': seg.difficulty or '未知',
        }
        
        ai_text = generate_segment_draft(segment_props)
        if not ai_text:
            logger.warning(f"AI 返回空草稿，segment_id={segment_id}，跳过 UPSERT")
            return
        
        # UPSERT：UNIQUE(segment_id) 保证幂等
        existing = db.query(SegmentAiDraft).filter(
            SegmentAiDraft.segment_id == segment_id
        ).first()
        if existing:
            # 已存在：仅 pending 状态允许覆盖（避免覆盖人工编辑）
            if existing.status == 'pending':
                existing.ai_draft_text = ai_text
            else:
                logger.info(f"draft segment_id={segment_id} status={existing.status}，跳过覆盖")
                return
        else:
            draft = SegmentAiDraft(
                segment_id=segment_id,
                ai_draft_text=ai_text,
                status='pending',
            )
            db.add(draft)
        
        try:
            db.commit()
        except IntegrityError:
            # 并发场景：另一 worker 已插入。回滚不抛
            db.rollback()
            logger.warning(f"draft segment_id={segment_id} 并发插入冲突，跳过")
    finally:
        db.close()
```

**enqueue 入口**（admin/service.py 新增辅助）：

```python
# app/admin/service.py
from app.queue import ai_drafts_queue  # 第三轮双审 R3-I4 修复：直接用 task 0.8 expose 的 queue 实例，不就地 Queue('ai_drafts')

def enqueue_ai_draft_generation(segment_id: int) -> None:
    """admin endpoint 调用：把 AI 草稿生成丢给 RQ。"""
    ai_drafts_queue.enqueue(
        'app.agent.tasks.generate_segment_draft_task',
        segment_id,
        job_timeout=120,  # 整数秒，与项目其他位置一致
        retry={'max': 2, 'interval': [30, 90]},
    )
```

**部署同步**（陷阱 #2 环境变量 N 处同步 + 第二轮双审 B3B-2/B3B-3 修复）：

- **`worker.py` 改造（必做）**：现有 `worker.py:31` 硬编码 `Worker([queue], connection=...)` 单 `velo` 队列。
  v5 改为读 env：`RQ_QUEUES = os.getenv('RQ_QUEUES', 'velo,ai_drafts').split(',')` →
  `Worker([Queue(name, connection=redis_conn) for name in RQ_QUEUES], connection=redis_conn)`。
  确保单 worker 容器同时订阅 velo + ai_drafts。
- **`docker-compose.yml`**：worker service 加 `environment: RQ_QUEUES=velo,ai_drafts`。
  扩容用 `docker compose up --scale worker=3`（**不用 v3 standalone 不支持的 `replicas:` 字段**，B3B-4 修复）。
- 新增 env：`DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL`（Tim 2026-04-29 拍走 DeepSeek） + `FEISHU_BOT_WEBHOOK` —— `.env.example` + `docker-compose.yml` environment + `app/config.py` Settings 类加字段（**不用顶层常量**，B3B-3 修复）：
  ```python
  # app/config.py Settings 类追加
  DEEPSEEK_API_KEY: str = ""
  DEEPSEEK_MODEL: str = "deepseek-chat"  # env 覆盖切其他模型
  FEISHU_BOT_WEBHOOK: str = ""
  ```
  调用方 `from app.config import settings` + `settings.DEEPSEEK_API_KEY`（项目现有风格）。
  **⚠ 真实 API key 仅放生产 .env，不进 git。**
- **`app/queue.py`**：Sprint 0 task 0.8 已建（第二轮双审 B3B-1 修复），本节直接 `from app.queue import redis_conn`。

### §3.8 worker 软目标监控（5.7.1）

**模块归属**：`app/monitor/processing_health.py` 新建（或 app/activity/monitor.py，spec 实施时拍）。

**隔离边界**：
- 读 activities 表（沿用现有，不改 status / _PROCESSING_TIMEOUT）
- 调飞书机器人推告警
- **禁止**：改 activities 表结构 / 改 _PROCESSING_TIMEOUT 常量（沿用 v4 10 分钟兜底）

```python
# app/monitor/processing_health.py（新建）
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.activity.models import Activity
from app.config import settings  # 第二轮双审 B3B-3 修复：项目统一 settings.XXX 风格
import httpx  # 第二轮双审 B3B-2 修复：项目统一 httpx 不是 requests（requirements.txt:httpx==0.28.1）

logger = logging.getLogger(__name__)

# 软目标告警阈值（PRD 5.7.1 拍：建议 80% 即 4 分钟）
WARN_THRESHOLD_SEC = 4 * 60
# 硬上限沿用 v4 _PROCESSING_TIMEOUT = 10 * 60 不改


def scan_processing_health(db: Session) -> list[int]:
    """
    扫 processing 状态超过 4 分钟的 activities，发飞书告警。
    
    注：本函数不标 failed（10 分钟硬上限的 timeout 由现有 worker 自愈机制处理，
    见 app/activity/service.py:297 注释）。仅做监控告警，不阻断用户。
    
    定时跑：每 1 分钟一次（部署 cron 配）
    
    返回：触发告警的 activity_id 列表
    """
    now = datetime.now(timezone.utc)
    warn_cutoff = now - timedelta(seconds=WARN_THRESHOLD_SEC)
    
    stuck_activities = (
        db.query(Activity)
        .filter(
            Activity.status == 'processing',
            Activity.updated_at < warn_cutoff,
        )
        .all()
    )
    
    if not stuck_activities:
        return []
    
    # 推飞书告警
    msg = (
        f"⚠️ velo worker 处理告警\n"
        f"以下 activities 处理超过 {WARN_THRESHOLD_SEC // 60} 分钟未完成：\n"
        + "\n".join(
            f"  - id={a.id} user_id={a.user_id} elapsed={(now - a.updated_at).total_seconds():.0f}s"
            for a in stuck_activities
        )
    )
    
    try:
        httpx.post(
            settings.FEISHU_BOT_WEBHOOK,
            json={"msg_type": "text", "content": {"text": msg}},
            timeout=5,
        )
    except Exception as e:
        logger.error(f"feishu webhook failed: {e}")
    
    return [a.id for a in stuck_activities]
```

**部署集成**（第二轮双审 M-B3-2 修复 + B3B-4 修复）：
- **cron 模式**：沿用 `scripts/cleanup_zombies.py` 容器包装模式（docker-compose 内 `while true; sleep <周期>`）。本节 monitor 周期 **60 秒**（不沿用 cleanup_zombies 的 300 秒，监控更密；第三轮双审 R3-Minor 修复：spec 显式注明独立周期，避免实施 subagent 误抄）。
- **worker 容器扩容**（PRD 5.7.1 拍）：用 `docker compose up --scale worker=3` 命令式扩容，**不用** v3 standalone 不支持的 `replicas:` 字段。容器名自动 `velo_worker_1/_2/_3`。

---

## §4 API 接口完整定义

按模块分组（隔离原则）。每 endpoint 给：路径 + 方法 + 权限 + 参数/body + 响应 schema + 错误码。

### §4.1 segment 模块（用户端 / 5.B.1 + 5.B.3 + 5.C.1）

#### GET /api/segments（扩展现有 app/segment/router.py:103-111）

| 维度 | 内容 |
|---|---|
| 权限 | **公开**（**第二轮双审 B1-B3 + Tim 2026-04-28 拍：赛段目录是发现性内容，匿名可看，沿用现有 router.py:104-111 不加 get_current_user**）|
| 参数 | `page` int default 1 / `page_size` int 1-100 default 20 / `near_lat` float? / `near_lon` float? / `radius` float default 50000（米，沿用现有，**不允许改 None**）/ `search` str? len ≥ 2 / `city` str? enum / `difficulty` str? enum |
| 响应 | `{items: [{id, name, distance, elevation_gain, avg_gradient, max_gradient, city, difficulty, entries, start_lat, start_lon, end_lat, end_lon}], total, page, page_size}`（**字段名 `distance` 单位公里——沿用 v4 router 契约，task-1.A.3 codex 异源审 + Tim 2026-04-30 拍：保留现有不破 v4 leaderboard.js 等前端消费方**）|
| 错误 | 422 invalid enum |

#### GET /api/segments/{segment_id}（扩展返回字段）

| 维度 | 内容 |
|---|---|
| 权限 | current_user |
| 响应字段加 | `difficulty` / `max_gradient` / `city`（沿用其他字段不变）|
| 错误 | 401 / 404 不存在 |

#### GET /api/segments/{segment_id}/efforts/me（新增 / 5.C.1）

| 维度 | 内容 |
|---|---|
| 权限 | current_user |
| 参数 | path: segment_id |
| 响应 | `{current_attempt_elapsed_time: int?, last_attempt_elapsed_time: int?, pr_elapsed_time: int?, current_attempt_diff_to_last: int?, current_attempt_is_pr: bool, is_first_attempt: bool}` |
| 错误 | 401。**404 segment 不存在 由 router 层显式查 `db.query(Segment).get(segment_id)` 校验抛出（第二轮双审 B1-B4 修复：service `get_my_effort_with_compare` 不抛 404，无 effort 时返 `is_first_attempt=True`）**|
| 备注 | 用 idx_efforts_segment_user_time 索引（已存）；router 层 ValueError → 404 翻译参 §4.5 |

### §4.2 user 模块（用户端 / 5.C.2 + 5.A.1 + 5.A.2）

#### GET /api/users/me/power-curve（新增 / 5.C.2）

| 维度 | 内容 |
|---|---|
| 权限 | current_user |
| 参数 | `period` enum: `this_month` / `last_month` / `this_year` / `last_year` / `all_time`，default `this_month` |
| 响应 | `{period: str, buckets: {"1": float, "5": float, "30": float, "60": float, "300": float, "1200": float}}`（6 buckets 单位 W）|
| 错误 | 401 / 422 invalid period |
| 备注 | Redis 缓存 TTL 1h；FTP 为 NULL 用户返绝对 W |

#### GET /api/users/me/heatmap（新增 / 5.A.1）

| 维度 | 内容 |
|---|---|
| 权限 | current_user |
| 参数 | `city` enum: 6 城 + unknown，default user.city（NULL 时返 400）|
| 响应 | `{city: str, multipoint: {"type": "MultiPoint", "coordinates": [[lon, lat], ...]}, activity_count: int}` |
| 错误 | 401 / 400 city 未指定且 user.city is NULL / 422 invalid city |
| 备注 | Redis 缓存 TTL 1h |

#### PATCH /api/users/me（扩展 body / 5.A.1 settings）

| 维度 | 内容 |
|---|---|
| 权限 | current_user |
| body 字段加 | `city` enum: 6 城 + unknown + null（可选） |
| 副作用 | 修改 user.city 后失效该用户所有 city 的 heatmap 缓存 |
| 错误 | 401 / 422 invalid city enum |

#### GET /api/users/{user_id}/profile（新增 / 5.A.2）

| 维度 | 内容 |
|---|---|
| 权限 | current_user（**任意登录用户**可访问）|
| 参数 | path: user_id |
| 响应 | `{id, nickname, avatar_url, city, ftp, bike_type, total_distance_km: float, total_elevation_m: float, activity_count: int, current_month_summary: {distance_km, elevation_m, avg_power_w}}` |
| 错误 | 401 / 404 用户不存在 |
| 红线（D-P08） | **严格不返回**：efforts / activities 列表 / heatmap / strava_* / openid / mute_notifications / 任何 token；看自己 ID 跟看他人**字段一致**（测试覆盖）|

### §4.3 admin 路由前缀（新增 / 5.D.* 系列）

**模块归属**：`app/admin/router.py`（新建）+ `app/admin/dependencies.py`（is_admin dependency）

```python
# app/admin/dependencies.py
from fastapi import Depends, HTTPException, status
from app.user.models import User
from app.dependencies import get_current_user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """is_admin dependency。沿用 users.is_admin 字段（app/user/models.py:62）"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    return current_user
```

#### POST /api/admin/ai/segment-drafts/{segment_id}/generate（新增 / 5.B.2）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| 参数 | path: segment_id |
| body | 无 |
| 响应 | `202 Accepted` `{job_id: str, segment_id, status: 'enqueued'}` —— **不同步等 AI** |
| 副作用 | **enqueue RQ task `app.agent.tasks.generate_segment_draft_task(segment_id)`**（§3.7.3）→ Worker 异步调 DeepSeek API + UPSERT segment_ai_drafts（segment_id UNIQUE）。完成后 admin 通过 GET /api/admin/ai/segment-drafts 拉取 |
| 错误 | 401 / 403 非 admin / 404 segment 不存在（enqueue 前预校验，不到 worker）|

#### GET /api/admin/ai/segment-drafts（新增 / 5.D.2）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| 参数 | `status` enum: pending/human_edited/approved/rejected default pending / `page` / `page_size` |
| 响应 | `{items: [{id, segment_id, segment_name, ai_draft_text, human_edited_text, status, editor_user_id, updated_at}], total}` |
| 错误 | 401 / 403 |

#### PATCH /api/admin/ai/segment-drafts/{draft_id}（新增 / 5.D.2）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| body | `{human_edited_text?: str, status?: enum}` |
| 副作用 | status='approved' → 同步 segments.description = human_edited_text（一致性约束）|
| 响应 | updated draft |
| 错误 | 401 / 403 / 404 draft 不存在 / 422 invalid status |

#### GET /api/admin/curation-pool（新增 / 5.D.1）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| 参数 | `selected` bool? / `city` enum? / `difficulty` enum? / `page` / `page_size` |
| 响应 | `{items: [{id, segment_id, segment_name, segment_city, segment_difficulty, pool_score, pool_reason, selected_for_v5, selected_by_user_id, selected_at}], total, selected_count}` |
| 错误 | 401 / 403 |

#### PATCH /api/admin/curation-pool/{id}（新增 / 5.D.1）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| body | `{selected_for_v5: bool}` |
| 副作用 | false → true 时**enqueue 同一 RQ task**（`app.agent.tasks.generate_segment_draft_task`，§3.7.3）—— 复用 5.B.2 的 worker 路径，不复制 |
| 响应 | updated pool item |
| 错误 | 401 / 403 / 404 / 400 当前选中数 ≥ 50 时拒绝新增 |

#### GET /api/admin/segments（新增 / 5.D.3）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| 参数 | `city` / `difficulty` / `has_draft` bool? / `page` / `page_size` |
| 响应 | `{items: [{...所有 segment 字段, draft_status?: enum}], total}` |
| 错误 | 401 / 403 |
| 备注 | 比 GET /api/segments 多 admin 视角字段（draft 状态等）|

#### PATCH /api/admin/segments/{id}（新增 / 5.D.3）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| body | `{name?, description?, city?: enum, difficulty?: enum}`（其他字段不允许 admin 改）|
| 响应 | updated segment |
| 错误 | 401 / 403 / 404 / 422 invalid enum |

#### DELETE /api/admin/segments/{id}（沿用现有 app/segment/router.py:84）

**改动**：迁移到 `app/admin/router.py`（保持 admin 路由前缀一致），但 service 调用沿用 `app/segment/service.py` 现有逻辑。级联删 segment_efforts 按 FK CASCADE 处理。

#### POST /api/admin/segments/from-activity（新增 / 5.D.4）

| 维度 | 内容 |
|---|---|
| 权限 | require_admin |
| body | `{activity_id: int, name: str, start_index: int, end_index: int, city?: enum, difficulty?: enum}` |
| 响应 | created segment |
| 错误 | 401 / 403 / 404 activity 不存在 / 422 起 ≥ 终 / 422 子序列点数 < 2 / 422 distance < 1000m / **409 重复**（reference_line 重叠 > 80%，error detail 含 existing.id）|

### §4.4 现有 endpoint 不变 / 沿用

- `/api/notifications/*` **修订（codex E1 C14）**：v5 沿用 v3/v4 endpoint 路径，但**响应 schema 必须扩展 payload 字段**——否则 progress 类 type 写入库后前端拿不到 (current_value / prev_value / delta) 渲染数据。spec subagent 实施时改 `app/notification/router.py` 序列化函数：grep 现有 NotificationResponse / NotificationOut schema 加 `payload: dict | None` 字段
- `/api/user/efforts` 沿用 v4 现有 (app/segment/router.py:187)
- `/api/segments` POST 创建沿用 v0 (app/segment/router.py 现有)
- `/api/activities/*` 沿用现有

### §4.5 错误码统一约定

| HTTP code | 语义 | 触发场景 |
|---|---|---|
| 400 | 参数缺失 / 业务约束违反 | 缺 city / 候选池超 50 |
| 401 | 未登录 | 缺 JWT 或 token 失效 |
| 403 | 权限不足 | non-admin 调 /api/admin/* |
| 404 | 资源不存在 | segment_id / user_id / draft_id 不存在 |
| 409 | 资源冲突 | from-activity 重复检测命中 |
| 422 | 参数格式错 | enum 不匹配 / 数值越界 |
| 502 | 上游服务失败 | DeepSeek API 调用失败 |

---

## §5 集成改动点（file:line 精确）

按模块分组（实施时按这个分组派 subagent，不同模块独立 worktree 并行）。

### §5.1 segment 模块

| 文件 | 行号 | 改动 |
|---|---|---|
| `app/segment/models.py` | 40-69 Segment 类 | 加 3 字段：difficulty / max_gradient / city（含 server_default + CheckConstraint）|
| `app/segment/models.py` | 124 后 | 加 Index `idx_segments_city_difficulty(city, difficulty)` |
| `app/segment/models.py` | SegmentEffort 类后追加 | **新增 ORM 类 `SegmentAiDraft` + `SegmentCurationPool`** —— 完整定义参 §2.2.3 |
| `app/segment/service.py` | 现有 + 新增 | 新增 `_haversine_distance` / `calculate_max_gradient` / `calculate_difficulty` / `get_my_effort_with_compare` / `create_segment_from_activity` —— **`infer_city_from_coords` 不在此处**（第二轮双审 B2A-2 拆到 `app/common/geo.py`）|
| `app/common/__init__.py` | **新建** | 空文件，标识 common 是包 |
| `app/common/geo.py` | **新建** | `infer_city_from_coords` + `_CITY_BOUNDS`（第二轮双审 B2A-2 修复反向依赖）|
| `app/segment/service.py` | 123-125 `get_segment_list` | 扩展加 search / city / difficulty 参数 |
| `app/segment/service.py` | 37-46 `create_segment` | **不改**（沿用，admin 用 from-activity 走新路径）|
| `app/segment/router.py` | 103-111 `list_segments` | 加 search / city / difficulty Query 参数 |
| `app/segment/router.py` | 新增 endpoint | `GET /api/segments/{segment_id}/efforts/me` |
| `app/segment/router.py` | 84 `DELETE /api/segments/{id}` | 迁移到 admin router（保持前缀一致），原路径标记 deprecated 或保留兼容 |

### §5.2 user 模块

| 文件 | 行号 | 改动 |
|---|---|---|
| `app/user/models.py` | 32-93 User 类 | 加 1 字段：city VARCHAR(32) NULL + CheckConstraint |
| `app/user/service.py` | 新增 | `get_user_power_curve` / `invalidate_power_curve_cache` / `get_user_heatmap` / `update_user_city` / `get_user_profile_for_others` |
| `app/user/router.py` | 新增 endpoint | `GET /api/users/me/power-curve` / `GET /api/users/me/heatmap` / `GET /api/users/{user_id}/profile` |
| `app/user/router.py` | 现有 `PATCH /api/users/me` | body schema 加 city 字段 |

### §5.3 activity 模块

| 文件 | 行号 | 改动 |
|---|---|---|
| `app/activity/power_zones.py` | 现有 + 新增 | 新增 `calculate_power_curve` 纯函数（与现有 power_zones 计算同模块）|
| `app/activity/service.py` | 42 `_PROCESSING_TIMEOUT` | **不改**（沿用 10 \* 60 = 600s，PRD 5.7.1 拍）|
| `app/activity/worker.py` 或 processing 完成处 | 现有 | 加 hook：activity status='completed' 后调 `progress_detector.detect_5min_power_progress` + `invalidate_power_curve_cache` + 推断 user.city（如 NULL）|

### §5.4 notification 模块

| 文件 | 行号 | 改动 |
|---|---|---|
| `app/notification/models.py` | 45 + 105-107 | event_type CHECK 加 3 新值 + 新增 payload JSONB NULL 字段 + 部分唯一索引 `uniq_progress_notification_per_activity`（codex E1 C13 幂等闸门）|
| `app/notification/progress_detector.py` | **新建** | `detect_5min_power_progress` + `PROGRESS_5MIN_POWER_THRESHOLD_W` 常量 + mute 检查 + 幂等检查 + IntegrityError 兜底 |
| `app/notification/detector.py` | 45-94 现有 | **不改**（PR/KOM 检测器沿用）|
| `app/notification/router.py` | 现有序列化 | **修订（codex E1 C14）**：响应 schema 加 `payload: dict \| None` 字段，否则前端拿不到 progress 数据 |

### §5.5 agent 模块（新建）

| 文件 | 改动 |
|---|---|
| `app/agent/__init__.py` | **新建空模块**（按 ADR-009 留接口架构）|
| `app/agent/segment_writer.py` | **新建**：`generate_segment_draft` + PROMPT_TEMPLATE + OpenAI 兼容 client 初始化（base_url=https://api.deepseek.com） |
| `app/agent/tasks.py` | **新建（第二轮双审 B3A-I3/M-2 修复）**：RQ 异步任务入口 `generate_segment_draft_task(segment_id)` —— UPSERT segment_ai_drafts 幂等。所有 admin 触发 AI 草稿生成都 enqueue 此 task，禁止同步调用 segment_writer |

### §5.6 admin 模块（新建）

| 文件 | 改动 |
|---|---|
| `app/admin/__init__.py` | **新建** |
| `app/admin/dependencies.py` | **新建**：`require_admin` dependency |
| `app/admin/router.py` | **新建**：所有 `/api/admin/*` endpoint（5.D.1-4 + AI 草稿 + DELETE segment 迁移）|
| `app/admin/service.py` | **新建**：admin 编排逻辑（候选池审核同步触发 AI / approved 时同步 segments.description 等），调用其他模块 service public API |

### §5.7 monitor 模块（新建）

| 文件 | 改动 |
|---|---|
| `app/monitor/__init__.py` | **新建** |
| `app/monitor/processing_health.py` | **新建**：`scan_processing_health` + WARN_THRESHOLD_SEC 常量 |

### §5.8 顶层 + 配置

| 文件 | 改动 |
|---|---|
| `app/main.py` | include 新增 router：`admin_router` + `progress_detector` 不需要 router |
| `requirements.txt` | 加 `openai` SDK（DeepSeek 兼容 OpenAI 格式） |
| `.env.example` | 加 `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `FEISHU_BOT_WEBHOOK` |
| `docker-compose.yml` | api/worker 服务的 `environment` 加 DEEPSEEK_API_KEY / DEEPSEEK_MODEL 等；**worker 扩容用 `docker compose up --scale worker=3`**（第三轮双审 R3-I2 修复：v3 standalone 不支持 `replicas:`）；可选加 admin-h5 容器 |

### §5.9 scripts 目录

| 文件 | 改动 |
|---|---|
| `scripts/generate_curation_pool.py` | **新建**：候选池脚本，cron 周一次跑 |
| `scripts/backfill_phase5.py` | **新建**：老数据回填（segments + users.city，参 §2.6）|

### §5.10 alembic 迁移

| 文件 | 改动 |
|---|---|
| `migrations/versions/<rev_id>_phase5_v5_db_changes.py` | **新建（第二轮双审 B3B-3 修复：真实路径是 `migrations/versions/`，不是 `alembic/versions/`）**：完整 upgrade / downgrade（参 §2.5）|
| `migrations/versions/<rev_id>_phase5_tz_aware.py` | **新建（第二轮双审 B2B-2 修复 + Sprint 0 task 0.1）**：迁 5 张表 DateTime 列为 timezone=True，`postgresql_using="<col> AT TIME ZONE 'UTC'"` |

### §5.11 H5 admin 前端项目（独立）

| 路径 | 改动 |
|---|---|
| `admin-h5/`（新建独立 repo 或同级目录）| React/Vue 项目 + 域名 admin.velo.com + Caddyfile 反代 |

**注**：H5 admin 不在 backend 仓库内，独立 repo / 独立部署流水线。本 spec §5 不展开，详见 PRD 5.D.5。

---

## §6 已知风险 + 对策（按 architect Step 5 五维）

### §6.1 崩溃恢复（进程死了能自愈吗）

| 风险 | 对策 |
|---|---|
| alembic 迁移中途失败 | upgrade / downgrade 完整对称（参 §2.5），DDL 单事务 |
| worker 卡死 / OOM | 10 分钟硬上限沿用 v4 `_PROCESSING_TIMEOUT` 自愈（不改）|
| Anthropic API 调用失败 | 不阻断业务，记 logger，draft 保 pending 状态后续重试 |
| service 聚合查询超时（看他人主页 / 热图）| fallback 简化字段返回，记 logger |
| 老数据回填 220 条单条失败 | SAVEPOINT 隔离 + logger 记 failed_segments.txt 后续人工修 |
| Redis cache 服务挂 | cache miss 走全量计算，记 logger（性能下降不阻断）|

### §6.2 并发安全（同时干同一件事会冲突吗）

| 风险 | 对策 |
|---|---|
| 多 admin 同时改同一 segment / draft | updated_at 乐观锁（实施时拍）|
| 多 worker 抢同一 activity | 沿用现有 SELECT FOR UPDATE 原子锁 |
| 候选池脚本跑期间 admin 改候选 | UPSERT by segment_id UNIQUE 幂等 |
| cache miss + 多请求并发计算 | 接受重复计算（结果幂等）；避免 thundering herd 用 Redis SET NX 加锁（可选）|
| approved draft 同步 segments.description 失败 | status 保 approved + 异步重试（不阻断 admin 操作）|
| **多 admin 同时 from-activity 创建相同轨迹（第二轮双审 B3A-I2）**| §3.1.5 进函数即取 `pg_advisory_xact_lock(hashtext('segment-create-from-activity'))` 串行化整条创建路径，事务结束自动释放。低频操作可接受。|
| **RQ task 重试导致同 segment_id 重复 enqueue（B3A-I2）**| §3.7.3 worker 内 UPSERT by `segment_id UNIQUE` + IntegrityError 回滚兜底，幂等保证。|
| **advisory lock 等待超时 / 死锁（B3A-I2）**| from-activity 单 admin 操作 < 1s 完成；可加 `SET LOCAL lock_timeout = '5s'` 兜底，超时返 503 让用户重试 |

### §6.3 批量冲击（100 倍数据量涌入会怎样）

| 风险 | 对策 |
|---|---|
| 220 条 segments 老数据回填内存峰值 | 单条事务 + SAVEPOINT 隔离，不一次性 load |
| 100k trackpoints 算 power_curve | O(n) per window × 6 window = 600k 操作，< 500ms（已验证）|
| 1.2M+ 热图点聚合 | 后端 PostGIS 聚合 + Redis 缓存 + 前端按 zoom 分级加载 |
| 30-50 条 AI 调用并发 | 限速 1 req/s 异步排队（避免 Anthropic rate limit）|
| 候选池 220 条 → top 100 排序 | 内存排序单次 < 10s，定时跑非实时 |

### §6.4 边界值（null / 0 / 空 / 极端值）

| 风险 | 对策 |
|---|---|
| trackpoints 空列表 | 算法返默认（0.0 / 空 dict）|
| power=0（合法值，骑行休息段）| 用 `is not None` 检查（陷阱 #1），不用 truthiness |
| elevation 全 None / 部分 None | 难度推算用 0 / 跳过该窗口 |
| city 推断失败（GPS 跨省 / 海外）| 返 'unknown' fallback，5.D.3 人工修 |
| FTP NULL（用户没填）| 功率曲线显示绝对 W，不规范化 |
| 上月无 activity | progress detector 直接返 None 不推送 |
| 首次骑赛段（无 last）| 5.C.1 返 is_first_attempt=True，UI 显示"首次完成" |

### §6.5 级联删除（上游删了下游怎么办）

| 上游删除 | 级联策略 | 实现 |
|---|---|---|
| delete segment | CASCADE 删 segment_efforts / segment_ai_drafts / segment_curation_pool | FK ondelete='CASCADE'（§2.2 已配）|
| delete activity | CASCADE 删 trackpoints / segment_efforts | 沿用现有 FK |
| delete user | SET NULL editor_user_id / selected_by_user_id（数据保留）| FK ondelete='SET NULL'（§2.2 已配）|
| approved draft 后改 segments.description | 重新走 status pending → human_edited → approved 流转 | service 层强制（§3.7 admin endpoint 实现）|

---

## §7 已知限制

- worker 5min 软目标对超大 GPX（> 50MB）可能超 5min；10 分钟硬上限兜底 standard
- city 推断对跨省 / 海外骑行起点不准；用 5.D.3 人工修
- AI 草稿质量依赖团队人工审核改写（PRD D-P10 UGC 三来源策略）
- calculate_power_curve 假设 1Hz 采样；非均匀采样精度受影响（GPX 标准基本满足）
- 看他人主页 v5 默认全公开 + settings 单一开关；v6+ 加细粒度字段控制
- progress 推送阈值 5W 起步，根据用户反馈 v6 调
- 候选池脚本周一次跑，新赛段最长 7 天才进候选池
- H5 admin 跟主站走独立部署流水线，不依赖 backend 仓库 CI/CD

---

## §8 任务拆分（按模块分组，subagent 派工准备）

**实施原则**（Tim 2026-04-28 拍 + 信条 15）：模块组之间**并行**（独立 worktree 不冲突），模块组内**串行**（同 git 冲突）。每个 task 主 agent 自己写到 `plans/phase5/task-N.X.md`（不派 codex 写）。

### §8.1 Sprint 0：P1 tech-debt 清理 + 迁移基线（5-8 天，单 worktree 串行）

依赖：无。前置 v5 所有 Sprint。

| 任务 | 文件改动 | 工期 |
|---|---|---|
| 0.1 datetime 栈内统一 aware UTC | 全项目 `datetime.utcnow()` → `datetime.now(timezone.utc)` + DateTime 字段加 timezone=True + **alembic 迁移 A（tech-debt tz-aware）独立一份**。**必迁列（第二轮双审 B2B-2 修复）**：`activities.started_at` / `activities.created_at` / `notifications.created_at` / `segment_efforts.created_at` / `users.created_at` —— 写迁移时 `postgresql_using="<col> AT TIME ZONE 'UTC'"`（陷阱 #7）。Sprint 1+ 业务代码（§3.3 / §3.4 / §3.6）假设这些列已 tz-aware，未迁前直接跑会触发陷阱 #2 TypeError | 2-3 天 |
| 0.2 ensure_valid_token 行锁注释化 | `app/strava/service.py` 函数签名改 `(db, user_id) → (User, token)` | 1 天 |
| 0.3 ensure_valid_token 未绑定路径 | 入口加 `if user.strava_refresh_token is None: raise` | 0.5 天 |
| 0.4 SQLAlchemy legacy `.get()` 替换 | `tests/test_notification.py` `Session.query().get()` → `session.get()` | 0.5 天 |
| 0.5 scheduler Redis 连接复用 | `app/strava/import_scheduler.py:187-198` 改用全局 `_redis` | 0.5 天 |
| **0.6 v5 主迁移（codex E1 C11 修复）** | **跑 §2 v5 迁移脚本（segments 加 difficulty/city/max_gradient + users.city + segment_ai_drafts + segment_curation_pool）—— 一份独立 migrations/versions/ revision，依赖 0.1 的 tz-aware revision** | 0.5 天 |
| **0.7 老数据回填（codex E1 C11 修复）** | **跑 `scripts/backfill_phase5.py`（§2.6）：填 segments 三新字段 + users.city。在 0.6 迁移后跑，Sprint 1 启动前完成** | 0.5-1 天 |
| **0.8 建立 app/queue.py 单一 Redis 连接源（第二轮双审 B3B-1 + Tim 拍）** | **新建 `app/queue.py`** 暴露三个对象：`redis_conn = Redis.from_url(settings.REDIS_URL)` / `default_queue = Queue('velo', connection=redis_conn)` / **`ai_drafts_queue = Queue('ai_drafts', connection=redis_conn)`**（第三轮双审 R3-I4 修复：v5 用到的所有队列实例都在此 expose，禁止调用方就地构造 `Queue('xxx')`）。同步重构 `worker.py` / `app/activity/service.py` / `scripts/cleanup_zombies.py` / `app/strava/client.py:_redis` 四处散点都 `from app.queue import redis_conn`。**禁止 v5 各模块各自 `Redis.from_url`** | 1 天 |

**⚠️ 迁移时机硬约束（codex E1 C11 修复）**：
- v5 共**两份独立 migrations revision**：A=tz-aware（task 0.1），B=v5 主迁移（task 0.6）
- 顺序固定：A → B → 老数据回填脚本（0.7）
- B 必须在 Sprint 1 三个模块组**启动前**完成 —— Sprint 1 / 2 / 3 业务代码假设三新字段（difficulty / city / max_gradient）已在 DB
- B 完成 + 0.7 回填完成 + 0.8 app/queue.py 落地 = Sprint 0 closure；任一未完成不许启动 Sprint 1

### §8.2 Sprint 1：B 主轴 + worker 软目标（10-14 天，3 模块组并行）

| 模块组 | 子任务 | 文件 | 串行 / 并行 |
|---|---|---|---|
| **A: segment 模块** | 5.B.1（坡度+难度+城市）+ 5.B.3（搜索）+ **5.C.1（即时反馈）** | `app/segment/models.py` + `service.py` + `router.py` | 组内串行（Index + service + router 顺序）|
| **B: agent 模块（新建）** | 5.B.2（AI 介绍 RAG 留接口）| `app/agent/__init__.py` + `segment_writer.py` + **`tasks.py`**（第二轮双审 B3A-I3 修复：RQ 异步入口必须 Sprint 1 完成，否则 Sprint 3 admin 启动时 enqueue 字符串路径无效）| 独立 worktree |
| **C: monitor 模块（新建）** | 5.7.1（worker 软目标）| `app/monitor/processing_health.py` + cron + 部署文档说明 `--scale worker=3`（第三轮双审 R3-I2 修复）| 独立 worktree |

依赖：Sprint 0 全部完成（含 task 0.1 tz-aware 迁移 + task 0.6 v5 主迁移 + task 0.7 老数据回填）。

### §8.3 Sprint 2：C 主轴 + A 主轴（12-15 天，3 模块组并行 + user 模块内串行）

| 模块组 | 子任务 | 文件 | 串行 / 并行 |
|---|---|---|---|
| **A: notification 模块** | 5.C.3（progress detector）| `app/notification/progress_detector.py` + models 加 payload | 独立 worktree |
| **B: activity power_zones** | 5.C.2 算法部分（calculate_power_curve）| `app/activity/power_zones.py` | 独立 worktree |
| **C: user 模块** | 5.A.1（热图）+ 5.A.2（看他人主页）+ 5.C.2 service 包装 + endpoint | `app/user/models.py` + `service.py` + `router.py` | **组内串行**（同模块）：先 models（加 city）→ 再 service（5 个函数）→ 再 router（4 endpoint）|

依赖：Sprint 1 完成（segment 模块的 difficulty / city 字段是 user 热图筛选依赖）。

### §8.4 Sprint 3：D 主轴（12-18 天）

| 模块组 | 子任务 | 串行 / 并行 |
|---|---|---|
| **A: admin 模块（新建）** | 3.1 框架（dependencies / router 骨架）→ 3.2 5.D.1（候选池）→ 3.3 5.D.2（AI 草稿审核）→ 3.4 5.D.3（批量管理）→ 3.5 5.D.4（from-activity）| **组内严格串行**（admin 模块内顺序依赖）|
| **B: H5 admin 项目（独立 repo / 独立 worktree）** | 5.D.5 | 跟 A 组**并行**（不同代码库）|
| **C: scripts** | `scripts/generate_curation_pool.py` + cron 配 | 跟 A 组并行（独立脚本）|

依赖：Sprint 1 完成（segment 模块 + agent 模块 + alembic 迁移），Sprint 2 部分完成（user 模块 is_admin 校验沿用现有）。

### §8.5 Sprint 4：收尾（5-7 天，主 agent 主导）

| 任务 | 内容 |
|---|---|
| 4.1 文档刷新 | architecture-guide.md / data-flow-guide.md 加 v5 7 条新链路 / changelog.md / tech-debt.md 移除清完的 P1 |
| 4.2 黑盒度三问体检 | 10 分钟讲全貌 / 数据流复述 / 30 秒读懂任意文件 |
| 4.3 集成测试 + 部署验证 | 按 §9 测试策略跑全套 |
| 4.4 ⑨ 复盘归档 | v5 期 lessons learned 沉淀到 memory + adr/ |

---

## §9 测试策略

### §9.1 单元测试（每个新增纯函数 ≥ 5 case，含边界）

| 函数 | 关键 case |
|---|---|
| calculate_max_gradient | 空 / 单点 / 全水平 / 全 None elevation / 标准 5% / 极陡 20% |
| calculate_difficulty | 4 档边界值（5/10/15% 和 300/800/1500m）/ 极陡短赛段 / 长平赛段 |
| infer_city_from_coords | 6 城代表点 / (None, None) / 跨城边界点 / 海外坐标 |
| calculate_power_curve | 空 / 全 None / 单点 / 标准 200W 平均 / 极端 1200W spike / power=0 合法（不被当 None）|
| detect_5min_power_progress | 上月无 activity / 当前无功率 / 涨 4W / 涨 5W / 退步（涨 -10W）|
| _haversine_distance | 同点 → 0 / 1km 直线 / 跨赤道 / 极远点 |

### §9.2 API 契约测试（每个新增 / 改动 endpoint ≥ 4 case）

- 正常路径（200）
- 401（未登录）/ 403（non-admin 调 admin endpoint）
- 404（资源不存在）/ 422（参数格式错）
- **关键专项**：
  - 看他人主页字段一致性（看自己 vs 看他人 字段集合相同）—— D-P08 红线
  - admin endpoint non-admin 调全部返 403
  - from-activity 重复检测返 409
  - 候选池超 50 时 PATCH 返 400

### §9.3 集成测试（关键链路）

| 链路 | 验证点 |
|---|---|
| GPX 上传 → processing → segment 匹配 → segment_efforts → 即时反馈 + 进步推送 | 5.C.1 vs 5.C.3 不重复（前者 API 内嵌，后者异步通知）|
| AI 草稿生成 → 审核改写 → approved → segments.description 同步 | 5.B.2 + 5.D.2 端到端 |
| 候选池脚本 → admin 勾选 → 触发 AI 生成 → 草稿入库 → 审核 → segments 更新 | 5.D.1 → 5.B.2 → 5.D.2 链路 |
| 用户改 settings.city → 失效 heatmap 缓存 → 下次 GET /api/users/me/heatmap 用新 city | 5.A.1 缓存失效一致性 |
| 看他人主页字段过滤防 D-P08 泄漏 | 5.A.2 严格红线 |
| from-activity 提坐标创建赛段 → 自动算 difficulty / max_gradient / city | 5.D.4 算法跟 5.B.1 一致 |

### §9.4 部署验证（CLAUDE.md "部署前强制检查清单"）

- requirements.txt 含 `anthropic` SDK
- docker-compose.yml `environment` 含 ANTHROPIC_API_KEY / FEISHU_BOT_WEBHOOK
- worker 容器扩容用 `docker compose up --scale worker=3`（第三轮双审 R3-I2 修复：v3 standalone 不支持 `replicas:`）
- alembic upgrade + downgrade 在 PostgreSQL 真实环境跑通
- backfill_phase5.py 跑完 220 条 segments + N 条 users（unknown 占比 < 30%）
- admin.velo.com 域名解析 + Caddyfile 反代 + JWT 复用主站登录态
- Anthropic API endpoint 测连通

### §9.5 性能基线

| 指标 | 目标 |
|---|---|
| API p95 | < 300ms（沿用 v4 标准）|
| worker 处理 GPX p95 | < 4 分钟（5min 软目标）|
| calculate_power_curve（100k trackpoints）| < 500ms |
| 看他人主页聚合查询 | < 200ms |
| 热图聚合（1.2M 点 + 缓存命中）| < 50ms（命中）/ < 1s（miss 全量计算）|
| AI 介绍生成单次调用 | < 10s（Anthropic API 上游限制）|

---

## §10 spec 双审策略 + 文档维护

### §10.1 spec 双审分批策略（Tim 2026-04-28 拍）

按 Tim "**禁止一次性审视全部**"约束 + 信条 5 双审 + Tim 模块隔离原则：**3 批次 × 2 agent 并行 = 6 次双审 subagent 调用**。

| 批次 | spec 范围 | Agent A 焦点（内部一致性）| Agent B 焦点（代码兼容性）|
|---|---|---|---|
| **Batch 1: 现有模块改动** | §3.1-§3.6 + §4.1-§4.2 + §5.1-§5.4 + 相关 §2 字段 | 段落自我矛盾 / TBD / 函数实现完整性 | grep `app/segment/` + `app/user/` + `app/activity/` + `app/notification/` 验证 file:line / 字段名 / 函数签名 / 状态值 |
| **Batch 2: 新建模块（agent / admin / monitor）** | §3.7-§3.8 + §4.3 + §5.5-§5.7 | 模块边界清晰 / 跨模块接口约定 | ADR-009 隔离原则 / 不反向 import 业务代码 / 跟其他模块的依赖方向正确 |
| **Batch 3: 跨模块全局** | §0 + §1 + §2 + §6 + §7 + §8 + §9 + §10 | 决策记录完整 / 跨模块引用一致（如 calculate_max_gradient 在 §3.1 定义 / §3.7 调用 / §5.1 引用要互相对得上）| §0.1 代码事实表与 §3-§5 引用一致性 / 任务拆分依赖图正确 / 风险表覆盖 5 维 |

每批次 prompt 互补（Agent B 明写"禁止重复 A 已列的问题"）。3 批次结果合并去重后修。**每批 Critical=0 才进 §10.2**。

### §10.2 决策者审阅（8-12 yes/no 翻译版给 Tim）

3 批次双审收敛 Critical=0 后，主 agent 翻译成 8-12 条 yes/no 给 Tim 拍。建议条目（实施时主 agent 自己拟）：
1. 4 主轴覆盖 14 子任务无遗漏对吗？
2. 防火墙破例 4 处（segments × 3 + users × 1）你认吗？
3. notifications 表加 payload JSONB（§2 修订补遗）你认吗？
4. AI 介绍 30-50 精选 / 单条 50-100 字 边界对吗？
5. 看他人主页**默认公开** + settings 隐私开关（v5 简化版）对吗？
6. worker 软目标 90% < 5min + 10 分钟 timeout 沿用 对吗？
7. 7 个模块组 + 模块组并行 + 组内串行（§8）对吗？
8. 5W 进步阈值 / 6 buckets / 城市 6 枚举 对吗？
9. RAG 留接口不实现（v5 仅建 app/agent/ 目录）对吗？
10. H5 admin 独立 repo（不在 backend 仓库内）对吗？
11. Sprint 节奏 0 → 1 → 2 → 3 → 4（依赖图）对吗？
12. ⭐ 你想拍但本 spec 没列的产品决策（你说）

### §10.3 文档维护

- **版本**：v1.0（spec 初版，主 agent chunk by chunk 自己写完成）
- **维护者**：Tim + Claude 协作
- **下次更新触发**：v5 实施过程中发现 spec 缺陷 → **改 spec 再改代码**（不允许 spec / 代码不一致）
- **关联文档**：
  - PRD：`docs/prd/phase-5-prd.md` v0.4
  - 架构全景：`docs/architecture-guide.md`（Sprint 4 收尾刷新加 v5 模块）
  - 数据流全景：`docs/data-flow-guide.md`（Sprint 4 收尾加 v5 7 条新链路）
  - 工程规则：`CLAUDE.md`（项目根）
  - 产品规则：`docs/agent-rules/product-decisions.md`
  - 思考框架：`docs/agent-rules/velo-mental-model.md`
  - 技术债：`docs/tech-debt.md`（Sprint 0 清完后移除已修条目 + 新增 v5 实施期发现的）
  - architect SKILL：`~/.claude/skills/architect/SKILL.md` 信条 15
  - 分工宪章：`docs/agent-rules/agent-collaboration.md` v1.3
  - 全局 CLAUDE.md：`~/.claude/CLAUDE.md`（4 条工作风格硬规则）

---
