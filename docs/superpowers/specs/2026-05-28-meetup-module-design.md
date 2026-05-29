# 约骑模块 v1 设计文档（2026-05-28 brainstorm 成果）

> **本文档是什么**：把 2026-05-28 Tim 和 Claude 4 轮 brainstorm 拍下的决策落成工程师能照着做的技术骨架。后续 codex 据此出实施 plans。
>
> **修订记录**：
> - **v1.0** 初稿（commit `89f71f2`）
> - **v1.1** Round 1 三审整合：7 Critical / 13 Important 修（commit `c8a69b9`）
> - **v1.2** Round 2 三审整合：2 Critical / 10 Important 修（commit `08ebe4d`）
> - **v1.3** Round 3 三审整合：0 Critical / 9 Important 修（本版 / Critical+Important=0 达成 ship gate）
>
> **标注约定**：✅ Tim 拍定 / 🔵 初步技术设计可微调 / 📊 grep 实证带 file:line / ⛔ v1 不做

---

## 1. 定位

velo v5 阶段引入"约骑"作为社交模块——支持骑友发起 / 加入约骑活动，让"渴望连接但不敢搭讪"的严肃骑手有半硬连接的入口。

战略层依据：
- ✅ `velo-vision.md:355` — v5/v6 主线"约骑 event 系统 + 路书机制"
- ✅ `velo-strategy.md:38-40` — "回应骑手孤独感" 的具体产品形式
- ✅ `velo-product-spec.md:47` — 核心产品洞察"柔性连接"

防火墙隔离：
- ✅ 新建 `app/meetup/` + `app/route_book/` 2 个独立模块
- ✅ 不修改核心表 users / activities / segments
- ✅ 单向依赖链：`User ← Activity ← Segment ← RouteBook ← Meetup`

---

## 2. v1 范围

| # | 功能 | 状态 | 工程量 |
|---|---|---|---|
| ① | 约骑活动 CRUD | ✅ 必做 | 5 天 |
| ② | 路线选择下拉（复用 segment）| ✅ | 0.5 天 |
| ③ | 路书导入 + 从活动衍生（B2 / 纯展示不参与匹配）| ✅ | 2.5 天 |
| ⑤ | 路线详情页"本路线约骑"卡片 | ✅ | 0.5 天 |
| ⑦ | 媒体上传（MIME 白名单 / 失败补偿）| ✅ | 2 天 |
| ④ | 路线足迹 / 打招呼卡片 | ⛔ v6 |
| ⑥ | 「为你推荐」算法 | ⛔ v2+ |

**v1 总工程量**：~16.5 天 / 跨 3 个 sprint（v1.3 修订 R3-I8：Task 10 估时 1→1.5 天）

---

## 3. 用户故事

### 3.1 陈哥发起约骑

周五晚 9 点 → velo "约骑" tab → 右下 FAB ➕ → 填字段 → 孩子哭了"保存草稿" → 周六早 5 点恢复 → 发布 → 卡片入约骑 tab list 顶部 / 1/6 人。

**约骑路线选两种来源**（陈哥点"路线"字段时弹出 2 个选项 / 二选一）：
- ① 选已有赛段（紫金山南坡 / 西山环线 等 admin 团队精选的）
- ② 选已有路书（自己上传或活动衍生的 / 也含别人公开的路书）

**用户自建路书 2 种方式**（陈哥要建一条新路书时 / 创建路书时用哪种）：
- ① 上传 **GPX 或 FIT** 文件 + 输入路名 / 距离 / 爬升（复用 📊 `app/parsing/gpx_parser.py` + `fit_parser.py` 现有解析器 / 与 activity 上传同 pattern `app/activity/service.py:46`）
- ② 从我已骑过的活动衍生（一键转 / 自动算距离爬升）

### 3.2 阿杰加入约骑

周五晚 11 点刷约骑 → 看到陈哥的卡片 → 详情看 FTP 配速对得上 → 点加入 → "已加入 ✓" / 3/6 → 周六骑完 9:30 自动 COMPLETED。

### 3.3 意外场景

| 场景 | 处理 |
|---|---|
| 🌧 出发前 30 min 内取消 | ❌ 不允许 / 之前可 cancel / 不发主动通知 |
| 🎯 满员抢位 | FOR UPDATE 物理保证不超员 / 退位补位 |
| ❌ 用户删账号 | OPEN cancel + DRAFT 硬删 + 参与名额空出 + 路书保留 |
| 🗑 admin 删 segment | snapshot 字段保留 / segment_id SET NULL |

### 3.4 5 条体验承诺

1. 创建约骑 ≤ 90 秒 / 2. 加入约骑 ≤ 3 秒 / 3. 看见但不互动 / 4. 已结束不消失 / 5. 路书复利（默认公开）

---

## 4. 数据模型（4 张新表）

### 4.1 meetups（约骑活动主表）🔵

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INT | PK | |
| `creator_id` | INT | FK→users.id ON DELETE SET NULL | 删账号 service hook 先 cancel 再删 |
| `status` | VARCHAR(16) | CHECK IN ('DRAFT','OPEN','CANCELLED','COMPLETED') | 默认 DRAFT |
| `segment_id` | INT | FK→segments.id NULL ON DELETE SET NULL | |
| `route_book_id` | INT | FK→route_books.id NULL ON DELETE SET NULL | |
| `snapshot_route_name` | VARCHAR(128) | NOT NULL | 路线名快照（**v1.3 修订 R3-I2 写入时机见 §4.1 末尾**）|
| `snapshot_distance` | FLOAT | NOT NULL | 距离快照（米）|
| `snapshot_climb` | FLOAT | NULL | 爬升快照（米）|
| `snapshot_city` | VARCHAR(32) | NOT NULL | city 快照 |
| `start_time` | TIMESTAMPTZ | NOT NULL | |
| `estimated_end_time` | TIMESTAMPTZ | NOT NULL | demo `velo-v2.html:403-410` estEnd 公式算 |
| `meeting_point` | VARCHAR(128) | NOT NULL | |
| `pace_level` | VARCHAR(16) | CHECK IN ('relaxed','cruise','training','race')| |
| `max_participants` | INT | NOT NULL CHECK (2 ≤ n ≤ 20) | |
| `description` | TEXT | NULL | |
| `created_at` / `updated_at` | TIMESTAMPTZ | tz-aware（📊 `segment/models.py:103`）| |
| `cancelled_at` / `completed_at` | TIMESTAMPTZ | NULL | |

**完整 CHECK 约束**（复制 📊 `segment/models.py:109-117` 原文）：
- `ck_meetups_status`: `status IN ('DRAFT', 'OPEN', 'CANCELLED', 'COMPLETED')`
- `ck_meetups_pace_level`: `pace_level IN ('relaxed', 'cruise', 'training', 'race')`
- `ck_meetups_max`: `max_participants >= 2 AND max_participants <= 20`
- `ck_meetups_city` on snapshot_city: `IN ('beijing','shanghai','hangzhou','shenzhen','chengdu','taiyuan','unknown')`
- `ck_meetups_time_order` on (start_time, estimated_end_time): `estimated_end_time > start_time`（**v1.9 修订 / Tim 2026-05-29 复审拍**：estimated_end_time 由后端公式算正常恒大于 start_time，此 CHECK 是防公式 bug 写入颠倒时间对的 DB 兜底）

**索引**：
- `(status, start_time)` / `(creator_id, status)` / **partial UNIQUE `(creator_id) WHERE status='DRAFT'`**（ORM + alembic 双声明 / 参照 📊 `notification/models.py:130-134`）

**v1.3 修订 R3-I2 snapshot 写入时机**（关键产品决策 / 推荐方案）：
- **DRAFT 期间 PATCH 改 segment_id / route_book_id → 自动重算 snapshot_* 4 字段**（用户修改路线时直觉同步）
- PATCH 改其他业务字段（时间 / 集合点 / 备注 etc）→ 不动 snapshot
- **publish 时 freeze**：DRAFT → OPEN 后 snapshot 永远不再变（admin 改 segment 名 / route_book creator 改路书名 → 已发布约骑保留原快照）

### 4.2 meetup_participants 🔵

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | INT | PK |
| `meetup_id` | INT | FK→meetups.id ON DELETE CASCADE |
| `user_id` | INT | FK→users.id ON DELETE CASCADE |
| `is_creator` | BOOLEAN | DEFAULT false / 计入 max |
| `joined_at` | TIMESTAMPTZ | |

**UNIQUE(meetup_id, user_id)** / 索引 `(user_id, joined_at)`

### 4.3 meetup_media 🔵（v1.3 修订 R3-I1 url→file_id）

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | INT | PK |
| `meetup_id` | INT | FK→meetups.id ON DELETE CASCADE |
| `uploader_id` | INT | FK→users.id ON DELETE SET NULL |
| `type` | VARCHAR(16) | CHECK IN ('image','video')|
| **`file_id`** | **VARCHAR(512)** | **v1.3 修订 R3-I1：存 storage 相对路径（如 `202605/abc123.jpg`）/ 对齐 📊 `app/storage/local.py:85` `delete(self, file_id: str)` API 签名 / 不是 HTTP URL** |
| `caption` | VARCHAR(128) | NULL / service 层 HTML escape |
| `seq` | INT | 显示顺序 |
| `created_at` | TIMESTAMPTZ | |

**鉴权完整规则**（IDOR 防护）：
- 删媒体 = `media.uploader_id == current_user OR meetup.creator_id == current_user`
- **同时校验 `media.meetup_id == path_meetup_id`**

**媒体上传安全闭环**（v1.3 修订 R3-I4 方向统一）：
- MIME 白名单：image/jpeg / image/png / image/webp / video/mp4
- 大小限制：图片 ≤ 5MB / 视频 ≤ 50MB
- caption HTML escape
- **上传方向**：先 INSERT meetup_media DB record（拿 id）→ 上传 storage（用 file_id 命名）→ 失败回滚 DB record（防孤儿 DB record）
- **删除方向**：先 DB COMMIT 删 record → 再 storage.delete（DB 是 source of truth / storage 失败 logger.warning 留定期清理 v2）

### 4.4 route_books 🔵

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | INT | PK |
| `creator_id` | INT | FK→users.id ON DELETE SET NULL |
| `name` | VARCHAR(128) | NOT NULL |
| `distance` | FLOAT | NOT NULL（米）|
| `climb` | FLOAT | NULL |
| `reference_line` | GEOMETRY(LINESTRING, 4326) | NOT NULL（**spatial_index=False** + 手动 GIST 索引 `idx_route_books_geom`；显式关掉 GeoAlchemy2 自动建索引，避免与手动命名索引在 PG 上重复建 / 比 📊 `segment/models.py:69` 旧写法更干净）|
| `file_id` | VARCHAR(512) | NULL（v1.5 generic 化 / 不再叫 gpx_file_id / 容纳 GPX 或 FIT）|
| `file_type` | VARCHAR(8) | NULL / 仅 source='file_upload' 才填 / source='activity_derived' 时 NULL（见下方复合 CHECK）|
| `source` | VARCHAR(32) | CHECK IN ('file_upload','activity_derived') / v1.5 修订 R4-N2：原 'gpx_upload' 改 'file_upload' 容纳 GPX+FIT |
| `source_activity_id` | INT | FK→activities.id NULL ON DELETE SET NULL / **仅 source='activity_derived' 时有值** / source='file_upload' 时必须 NULL（见下方复合 CHECK）|
| `city` | VARCHAR(32) | NOT NULL `ck_route_books_city` 完整 7 枚举 |
| `created_at` | TIMESTAMPTZ | |

**v1.7 修订 R6-Critical 复合 CHECK 约束**（**方案 B：source_activity_id NOT NULL 校验下沉到 service 层** / 避免 FK ON DELETE SET NULL 与 CHECK NOT NULL 死锁 / Tim 拍）：

```sql
-- DB 层只校验 file_type / source 联动 / 不校验 source_activity_id NOT NULL
-- （否则删 activity 时 SET NULL 触发 CHECK 报错让整条 DELETE 失败）
ALTER TABLE route_books ADD CONSTRAINT ck_route_books_file_type_source CHECK (
    (source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL AND source_activity_id IS NULL)
    OR
    (source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL)
);
```

防止半状态写入：source='file_upload' 但 file_type=NULL / source='activity_derived' 但 file_type='gpx' / 等。alembic 用 `op.create_check_constraint(...)` 添加。

**service 层补强校验**（**v1.7 修订 R6 / 由 service 层入口而非 DB CHECK 保障**）：
```python
# POST /api/route-books service.create_route_book(...)
if source == 'activity_derived' and source_activity_id is None:
    raise HTTPException(422, "activity_derived 必须提供 source_activity_id")
# DB schema 允许 source_activity_id 后续被 ON DELETE SET NULL 变 NULL
```

**业务孤儿态语义**（**v1.7 修订 R6 / 源活动被删后路书仍有效**）：
- 路书一旦创建 / 源 activity 被删 → `source_activity_id` 自动变 NULL（FK ON DELETE SET NULL）/ source 仍是 'activity_derived'
- 业务层把此状态当作 "**源活动已删 / 路书仍可用作图纸**"（路书复利原则 / 路书不依赖 activity 存活）
- 前端显示：路书详情页"衍生自活动"链接在 source_activity_id NULL 时隐藏（不显示坏链）

**v1.2 visibility 决策**：v1 路书一律公开 / 不加 visibility 列 / v2 加。

**v1.9 重复路书决策**（2026-05-29 Tim task2 复审拍）：**允许**同一用户从同一活动衍生多条路书 / 不加 `(creator_id, source_activity_id)` 唯一约束 / 理由：用户可能想从一条长骑行剪裁多条不同路书，重复了自己删即可，不值得为防双击加约束。

**路书衍生 IDOR 防御**：service 层 `POST /api/route-books` source='activity_derived' 必须 `activity.user_id == current_user` 否则 403。

**v1.3 修订 R3-I9 路书端 IDOR 不对称说明**：路书端**不**共用 meetup 的 `_load_and_authorize_meetup` helper / route_book service 层 inline 校验 `route_book.creator_id == current_user`（路书无并发 race / 不需要 FOR UPDATE / inline 更轻）。

**关键产品定义**：路书 = 用户自建图纸 / segment = 管理员精选排名单元 / 路书 v1 不参与 KOM 排行。

---

## 5. 状态机

```
┌─────────┐  publish   ┌──────────┐  cancel (出发前 30+ min)  ┌────────────┐
│  DRAFT  │ ─────────→ │   OPEN   │ ────────────────────────→ │ CANCELLED  │
└────┬────┘            └────┬─────┘                            └────────────┘
     │ DELETE                │ cron 5min/次（约 5min / 非硬实时）
     ↓ (creator only)        ↓ now() > estimated_end_time
   (deleted)            ┌────────────┐
                        │ COMPLETED  │
                        └────────────┘
```

**时间边界**（含 ±30 秒缓冲）：截止报名 / 退出 / 取消 = `start_time - 30 min`。

**v1.3 修订 R3-I7 cron 精度说明**：tick 周期约 5 分钟（15s × 20 tick）/ 上游 strava import tick 阻塞时 meetup tick 会延后 / **非硬实时 / OPEN → COMPLETED 偶尔延后几分钟无业务影响**。

**异常路径**：用户删 status != 'DRAFT' 的约骑 → 409 + "只能硬删草稿"。

---

## 6. 关键技术决策

### 6.1 并发控制 + IDOR 防护

复用项目 pattern：陷阱 #12 `.with_for_update().populate_existing().first()` + [[feedback_savepoint_isolation_for_inner_modules]]

**所有写接口权限校验链**：

| Endpoint | 校验链 |
|---|---|
| POST /api/meetups | 仅认证用户 |
| PATCH /api/meetups/{id} | creator + status='DRAFT' |
| POST /api/meetups/{id}/publish | creator + status='DRAFT' |
| POST /api/meetups/{id}/cancel | creator + status='OPEN' + 时间边界 |
| DELETE /api/meetups/{id} | creator + status='DRAFT' |
| POST /api/meetups/{id}/join | 认证 + 时间边界 + 满员/重复检查 |
| DELETE /api/meetups/{id}/leave | 当前用户已加入 + 时间边界 |
| POST /api/meetups/{id}/media | meetup creator |
| DELETE /api/meetups/{id}/media/{media_id} | `media.meetup_id == path` AND (uploader OR creator) |
| POST /api/route-books source='activity_derived' | activity.user_id == current_user |
| DELETE /api/route-books/{id} | route_book.creator_id == current_user（inline / 不用 meetup helper / R3-I9）|

**共享 helper 位置**（v1.3 修订 R3-I5 落点明确）：
- `_load_and_authorize_meetup` 放在 **`app/meetup/service.py`**
- 仅用于 meetup 对象 / 路书端 inline 校验

```python
def _load_and_authorize_meetup(db, meetup_id, current_user, *,
                                require_status=None,
                                require_creator=False,
                                check_time_cutoff=False) -> Meetup:
    meetup = (db.query(Meetup).filter(Meetup.id == meetup_id)
              .with_for_update().populate_existing().first())
    if meetup is None:
        raise HTTPException(404, "meetup not found")
    if require_creator and meetup.creator_id != current_user.id:
        raise HTTPException(403, "not creator")
    if require_status and meetup.status not in require_status:
        raise HTTPException(409, f"invalid status: {meetup.status}")
    if check_time_cutoff:
        cutoff = meetup.start_time - timedelta(minutes=30, seconds=30)
        if datetime.now(UTC) > cutoff:
            raise HTTPException(410, "cutoff passed")
    return meetup
```

**N+1 修复 SQLAlchemy 2.0 模板**（v1.3 修订 R3-I6 给出可照搬代码）：

```python
# GET /api/meetups 列表查询：3 段查询 / 不用 JOIN+GROUP BY 直接乘行
def list_meetups(db, status=None, city=None, page=1, page_size=20):
    # 主查询
    base = db.query(Meetup)
    if status: base = base.filter(Meetup.status == status)
    if city: base = base.filter(Meetup.snapshot_city == city)
    meetups = (base.order_by(Meetup.start_time.desc())
               .offset((page-1)*page_size).limit(page_size).all())
    meetup_ids = [m.id for m in meetups]
    
    # 子查询 1: participants 聚合
    p_counts = dict(db.query(
        MeetupParticipant.meetup_id, func.count(MeetupParticipant.id)
    ).filter(MeetupParticipant.meetup_id.in_(meetup_ids))
     .group_by(MeetupParticipant.meetup_id).all())
    
    # 子查询 2: media 首图
    first_media = {m.meetup_id: m.file_id for m in db.query(
        MeetupMedia.meetup_id, MeetupMedia.file_id
    ).filter(MeetupMedia.meetup_id.in_(meetup_ids), MeetupMedia.seq == 0).all()}
    
    # 组装返回
    return [{
        "id": m.id, "snapshot_route_name": m.snapshot_route_name,
        "participants_count": p_counts.get(m.id, 0),
        "first_media_file_id": first_media.get(m.id),
        # ... 其他字段
    } for m in meetups]
```

**partial unique IntegrityError → 409**：
```python
try:
    db.add(meetup); db.flush()
except IntegrityError as e:
    if 'uq_meetups_creator_draft' in str(e.orig):
        db.rollback()
        existing = db.query(Meetup).filter_by(
            creator_id=current_user.id, status='DRAFT'
        ).first()
        raise HTTPException(409, detail={
            "code": "draft_exists", "existing_draft_id": existing.id,
            "message": "你已有 1 个草稿，是否覆盖？"
        })
    raise
```

错误码：满员 409 / 截止过期 410 / 已取消 410 / 已加入 409+already_joined / 404 not found / 403 无权限 / 409+draft_exists。

### 6.2 用户删账号级联策略

**v1.3 修订 R3-I5**：在 **`app/user/service.py`** 新增 `delete_user(db, user_id)`：

```python
def delete_user(db, user_id):
    with db.begin():
        # Step 1: 先 cancel 该用户发起的 OPEN 约骑
        db.query(Meetup).filter_by(
            creator_id=user_id, status='OPEN'
        ).update({'status': 'CANCELLED', 'cancelled_at': func.now()})
        
        # Step 2: 硬删该用户的 DRAFT 约骑（含 storage 清理）
        draft_ids = [m.id for m in db.query(Meetup.id).filter_by(
            creator_id=user_id, status='DRAFT'
        ).all()]
        for mid in draft_ids:
            _delete_meetup_with_storage_cleanup(db, mid)
        
        # Step 3: 最后才删 user（触发剩下 SET NULL cascade）
        db.query(User).filter_by(id=user_id).delete()
```

级联表：
| 表 | 字段 | 策略 |
|---|---|---|
| meetups | creator_id | SET NULL（service hook 先 cancel OPEN + 硬删 DRAFT）|
| meetup_participants | user_id | CASCADE（名额自动空出）|
| meetup_media | uploader_id | SET NULL |
| route_books | creator_id | SET NULL |

### 6.3 微信小程序合规约束

参考 [[feedback_wechat_miniprogram_no_direct_social]]：v1 砍所有"用户↔用户双向互动"（私信 / 关注 / 评论 / 点赞 / 打招呼 / 群聊 / @ / 私聊跳转）/ 允许单向看见列表（昵称 / FTP / 均速）。

均速字段：service 层 JOIN `activities.avg_speed` 聚合最近 N 次 / 不在 users 表加列。

### 6.4 cron 调度

**📊 现状**：调度器在 `/Users/macbookair/Desktop/velo/scheduler.py`（项目根 / 不在 app/strava/）/ `scheduler.py:43-48` 有现有 try/except / 当前使用 `while True + time.sleep(15)` 模式。

**修订**：保留现有 try/except + 新增独立 meetup tick（异常隔离）：

```python
_meetup_tick_counter = 0
while True:
    try:
        run_import_tick()
    except Exception:
        logger.exception("import tick 失败")
    
    _meetup_tick_counter += 1
    if _meetup_tick_counter >= 20:  # 15s × 20 = 5 min
        try:
            run_meetup_complete_tick()
        except Exception:
            logger.exception("meetup tick 失败")
        _meetup_tick_counter = 0
    
    time.sleep(15)
```

`run_meetup_complete_tick()` 放在 `app/meetup/cron.py`。

**部署影响**：改 scheduler.py 必须 `docker compose up -d --build scheduler`。

---

## 7. API endpoint 清单（17 个）🔵

### 约骑模块（app/meetup/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/meetups` | 列表（status / city / date_range / pace / page）/ 三段子查询防 N+1 |
| GET | `/api/meetups/{id}` | 详情 |
| POST | `/api/meetups` | 创建（默认 DRAFT / IntegrityError → 409 draft_exists）|
| PATCH | `/api/meetups/{id}` | 修改（仅 creator / 仅 DRAFT / 改路线时自动重算 snapshot）|
| POST | `/api/meetups/{id}/publish` | DRAFT → OPEN（仅 creator / freeze snapshot）|
| POST | `/api/meetups/{id}/cancel` | OPEN → CANCELLED（仅 creator + 时间边界）|
| DELETE | `/api/meetups/{id}` | 硬删（仅 creator + DRAFT / 含 storage 清理 / status≠DRAFT 返 409）|
| POST | `/api/meetups/{id}/join` | 加入（FOR UPDATE）|
| DELETE | `/api/meetups/{id}/leave` | 退出（时间边界）|
| POST | `/api/meetups/{id}/media` | 上传媒体（仅 creator / DB record → storage）|
| DELETE | `/api/meetups/{id}/media/{media_id}` | 删媒体（meetup_id==path + uploader 或 creator）|
| GET | `/api/meetups/my-draft` | 获取我的草稿 |

### 路书模块（app/route_book/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/route-books` | 列表（mine=1 / city）|
| GET | `/api/route-books/{id}` | 详情 |
| POST | `/api/route-books` | 创建（file_upload 或 activity_derived / file_upload 含 GPX/FIT）|
| DELETE | `/api/route-books/{id}` | 删除（inline creator 校验 / 含 file storage 清理 / GPX 或 FIT 文件）|
| GET | `/api/route-books/activity-candidates` | 从已有活动衍生路书的候选列表 |

### 现有模块扩展

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/segments/{id}/upcoming-meetups` | 路线详情页⑤卡片 |

---

## 8. 数据流图（4 关键场景）

### 8.1 创建约骑（3 步流）

```
GET /api/segments / GET /api/route-books?mine=1 / GET /api/route-books/activity-candidates
  ↓ 用户填字段
【第 1 步】POST /api/meetups (status=DRAFT) → 拿 meetup_id
  ↳ service 层从 segment/route_book 复制 snapshot_* 字段
  ↳ IntegrityError(partial unique) → 409 + existing_draft_id
【第 2 步】POST /api/meetups/{meetup_id}/media (loop 用户选的图/视频)
  ↳ DB INSERT meetup_media（拿 media id + file_id）→ storage 上传 → 失败回滚 DB
【第 3 步】POST /api/meetups/{meetup_id}/publish
  ↳ status DRAFT → OPEN + freeze snapshot + INSERT creator 到 participants is_creator=true
```

### 8.2 加入约骑

```
POST /api/meetups/{id}/join
  ↓ BEGIN
_load_and_authorize_meetup(require_status=['OPEN'], check_time_cutoff=True) → 404/410
count check / 用户未加入 check → 409
INSERT meetup_participants
COMMIT → 200
```

### 8.3 取消约骑

```
POST /api/meetups/{id}/cancel
  ↓ BEGIN
_load_and_authorize_meetup(require_creator=True, require_status=['OPEN'], check_time_cutoff=True) → 404/403/409/410
UPDATE status='CANCELLED', cancelled_at=now()
COMMIT → 200
```

### 8.4 硬删草稿 + storage 清理

```
DELETE /api/meetups/{id}
  ↓
_load_and_authorize_meetup(require_creator=True, require_status=['DRAFT']) → 404/403/409
BEGIN
SELECT file_id FROM meetup_media WHERE meetup_id=?
DELETE meetups WHERE id=? (CASCADE 自动删 meetup_media)
COMMIT  ← DB 是 source of truth / 先 commit 再清 storage
  ↓
for file_id in file_ids:
    try: storage.delete(file_id)  # app/storage/local.py:85
    except: logger.warning(...)  # 失败留定期清理 v2 / 不阻塞用户
```

---

## 9. 风险表（故障 5 维）

| # | 维度 | 风险 | 严重度 | 对策 |
|---|---|---|---|---|
| 1 | 崩溃 | 加入后 worker 崩 | 中 | UNIQUE + 用户 retry 自然幂等 |
| 2 | 崩溃 | cron 跑 COMPLETED 时崩 | 低 | 下一个 5 min cron 接着扫 / try/except 隔离 |
| 3 | 并发 | 满员抢位 | 高 | FOR UPDATE + populate_existing |
| 4 | 并发 | cancel race | 高 | 同 FOR UPDATE 互斥 |
| 5 | 并发 | partial unique 草稿并发 | 中 | IntegrityError → 409 |
| 6 | 批量 | 列表 N+1 | 中 | 3 段子查询模板（§6.1）|
| 7 | 边界 | 截止时间 ±30s | 中 | server-side 严格判 + 30s 缓冲 |
| 8 | 边界 | max=2 / 发起即满员 | 低 | CHECK + creator +1 自动 |
| 9 | 边界 | 路书跨城市 / snapshot_city 由路线决定 | 低 | meetup snapshot_city 不让用户手动覆盖 |
| 10 | 级联 | 用户删账号 | 高 | service hook 顺序保证 |
| 11 | 级联 | admin 删 segment | 高 | snapshot 字段保留 + SET NULL |
| 12 | 级联 | route_book 被删 | 中 | snapshot 保留 + SET NULL |
| 13 | 合规 | 微信备案变更 | 中 | v1 砍互动 / 政策变化暂停部署 |
| 14 | 安全 | 媒体上传 XSS / 注入 / 孤儿 | 中 | MIME 白名单 + 大小限制 + escape + 失败回滚 |
| 15 | 安全 | 写接口 IDOR | 高 | §6.1 权限校验链 + helper |
| 16 | 安全 | 路书衍生 IDOR | 高 | service 层校验 activity.user_id |
| 17 | 安全 | 硬删草稿 storage 孤儿 | 中 | DB COMMIT 先 / storage.delete 失败 logger.warning |
| 18 | dialect | PostGIS LINESTRING 在 SQLite 测试炸 | 中 | 陷阱 #15 dialect 守卫 |
| 19 | 语义 | snapshot 写入时机歧义 | 低 | §4.1 末尾拍 DRAFT PATCH 路线时重算 / publish freeze |

---

## 10. 测试策略

按 CLAUDE.md 原则 3 TDD 红→绿：
- **单元测试**：状态机 / 并发 FOR UPDATE / 时间边界 / 级联 / 路书衍生算法
- **API 测试**：每个 endpoint happy + 4 类错误码（404/403/409/410）/ IDOR / media.meetup_id 路径校验
- **集成测试**：创建→加入→取消 全链路 / 用户删账号顺序 / admin 删 segment 后 snapshot 展示
- **避坑测试**：truthiness（陷阱 #1）/ tz-aware（#2）/ SAVEPOINT（#13）/ dialect 守卫（#15）/ first() None（#4）

**真用回归 hot spot**（必须真 PG / 单测覆盖不到）：
1. 满员抢位并发：两个小程序账号同时点最后一个名额
2. activity_derived 路书 LINESTRING：真 PG 跑 ST_MakeLine
3. cron COMPLETED + scheduler 容器 rebuild 真生效
4. partial unique 并发建草稿 → 第 2 个返回 409 而非 500
5. admin 删 segment 后 snapshot 字段展示
6. DRAFT 删除后 storage 文件清理
7. scheduler 双 tick 互不拖死（故意制造 meetup tick 异常）
8. partial unique SQLite fixture 不能模拟 → 真 PG 集成测覆盖 409 场景

---

## 11. 任务拆解（v1.3：16.5 天）🔵

| Task | 范围 | 工程量 |
|---|---|---|
| Task 1 | 数据模型 + Alembic 迁移（4 表 + partial unique + CHECK + PostGIS 索引）| 1 天 |
| Task 2 | 路书 service + API（CRUD + **GPX/FIT 上传**（复用 `app/parsing/gpx_parser` + `fit_parser` / activity 同 pattern）+ activity_derived + IDOR + ST_MakeLine + dialect 守卫 + storage 清理 + activity-candidates endpoint）/ **v1.6 修订 R5-I4 storage 层无需改代码**：`app/storage/local.py:65` 扩展名由原文件名 `os.path.splitext` 决定 / FIT 自动存 `.fit` / 仅 `local.py:29` docstring 写"存到 .gpx 路径"是注释偏差不是 bug | 2.5 天 |
| Task 3 | 约骑 service（CRUD + 状态机 + 时间边界 + snapshot 字段自动填充 + `_load_and_authorize_meetup` helper + IntegrityError → 409 处理）| 2 天 |
| Task 4 | 约骑 API（12 个 endpoint / 完整权限校验链）+ **v1.6 修订 R5-I2**：`app/main.py` 加 `from app.meetup.router import router as meetup_router` + `app.include_router(meetup_router)` / 同理路书 router 挂载 / 不挂载 = endpoint 全 404 | 1.5 天 |
| Task 5 | 加入 / 退出（FOR UPDATE + 并发测试）| 1 天 |
| Task 6 | 媒体上传 + 删除（MIME 白名单 + DB→storage 方向 + meetup_id == path）| 1 天 |
| Task 7 | cron auto-complete + `app/user/service.py` delete_user hook（顺序保证）| 0.5 天 |
| Task 8 | segment router 扩展（upcoming-meetups）| 0.5 天 |
| Task 9 | 小程序前端 3 页（list / detail / create sheet 3 步流）| 5 天 |
| Task 10 | 真用回归（8 类 hot spot 含 partial unique + scheduler 双 tick 等）+ hotfix（v1.3 修订 R3-I8 1→1.5 天）| 1.5 天 |

**总计 1+2.5+2+1.5+1+1+0.5+0.5+5+1.5 = 16.5 天**

---

## 12. 明确不做 ⛔

| # | 不做 | 理由 |
|---|---|---|
| 1 | 用户↔用户直接互动 | 微信备案约束 / 转 iOS app 阶段 |
| 2 | 「为你推荐」算法 | 100 用户量级冷启动 / v2 后 |
| 3 | 路线足迹 / 打招呼按钮 | v6 主线 |
| 4 | 路书参与 KOM 排行 | 防野鸡 KOM 污染 |
| 5 | 通知体系 | v1 自己刷新 / v2 加 |
| 6 | OPEN → DRAFT 反向 | 发布后只能 cancel |
| 7 | 跨城市约骑筛选（用户手动）| snapshot_city 由路线决定 |
| 8 | 修改已发布约骑 | 只能 cancel 重发 |
| 9 | 路书第 3 种创建方式（选 segment 当路书）| segment 直接选 / 冗余 |
| 10 | 路书私密标记 | v1 一律公开 / v2 加 |
| 11 | 媒体 / storage 孤儿文件清理 | DB 是 source of truth / v2 加定期 cleanup task |

---

## 13. 验收清单（给 Tim · v1.3）

- [ ] **1**. 范围：① + ② + ③ + ⑤ + ⑦ / ④⑥ v6/v2，对吗？
- [ ] **2**. 路书定义：路书 = 用户自建图纸 / segment = 管理员精选 / 路书不参与 KOM，对吗？
- [ ] **3**. 路书 2 种创建方式（上传 GPX或FIT / 活动衍生）/ 路线选择 2 种入口（segment / 路书），对吗？
- [ ] **4**. 状态机：DRAFT → OPEN → (CANCELLED \| COMPLETED) / DRAFT 可硬删 / OPEN 不可改字段 / 30 min ± 30s 截止，对吗？
- [ ] **5**. 微信合规：v1 砍所有用户互动 / 允许单向看见，对吗？
- [ ] **6**. 满员抢位：物理不可超员 / 退位补位，对吗？
- [ ] **7**. admin 删 segment：snapshot 保留可见 / **发布后历史快照不随源改名刷新**，对吗？
- [ ] **8**. 用户删账号：service hook 顺序（cancel OPEN → 硬删 DRAFT → 删 user）/ 参与名额自动空出 / 路书保留，对吗？
- [ ] **9**. 工程量 ~16.5 天 / 跨 3 sprint，对吗？
- [ ] **10**. 路书默认公开（v1 不加 visibility 列）/ v2 加私密开关，对吗？
- [ ] **11**. v1.3 新增 snapshot 写入时机：DRAFT PATCH 改路线时自动重算 / publish 时 freeze / 之后不再变，对吗？

---

## 14. 修订记录（Round 3 三审整合 / Critical=0 + Important=0 达成）

**Round 3 三 reviewer 抓**：0 Critical（3 reviewer 一致判定 ship gate 达成）+ 9 Important + 4 Minor。本版全部修：

| 编号 | 来源 | 问题 | 处理 |
|---|---|---|---|
| R3-I1 | integration | storage.delete 签名问题 / `app/storage/local.py:85` 真 API 是 `delete(file_id)` | ✅ §4.3 url → file_id / §8.4 调用对齐 |
| R3-I2 | spec-faithful + codex | snapshot 写入时机歧义（PATCH 重算 vs publish 一次性）| ✅ §4.1 末尾明确：DRAFT PATCH 改路线时重算 / publish freeze |
| R3-I3 | spec-faithful | storage.delete 失败策略未定义 | ✅ §8.4：先 DB COMMIT 后 storage.delete / 失败 logger.warning 留 v2 清理 |
| R3-I4 | codex | 媒体补偿方向不一致（创建 vs 删除） | ✅ §4.3：创建 DB→storage / 删除 DB COMMIT 先 / 方向一致 |
| R3-I5 | codex | delete_user hook 落点模糊 | ✅ §6.2 明确 `app/user/service.py` 新增 `delete_user(db, user_id)` |
| R3-I6 | codex | N+1 缺 SQLAlchemy 2.0 模板 | ✅ §6.1 给 3 段子查询完整 ORM 代码 |
| R3-I7 | codex | scheduler tick 精度未注 | ✅ §5：约 5 min 非硬实时 / 上游阻塞会延后 |
| R3-I8 | spec-faithful + codex | Task 10 真 PG 测试 1 天偏紧 | ✅ §11 Task 10 改 1.5 天 / 总 16.5 天 |
| R3-I9 | spec-faithful | 路书端 IDOR helper 不对称 | ✅ §4.4 + §6.1 明确路书 inline 校验 / 不共用 meetup helper |

**收敛节奏**：Critical 7 → 2 → 0 ✅ / Important 13 → 10 → 9 → 0（v1.3 全修）/ ship gate 完整达成。

---

## 15. 完整依赖图 + 模块删除 SOP（v1.4 修订 / 防"地基不牢"）

> **背景**：2026-05-28 Tim 抽查 spec 防火墙时一次发现 3 轮 12 次 reviewer 都漏抓的反向依赖问题。本节强制把"约骑模块到底依赖哪些 + 谁反向依赖它 + 删除时影响清单"全量画出来。

### 15.1 完整依赖图（约骑生态正向依赖 + 既有反向漂移虚线）

```
                                        【顶层 entrypoint】
                                        scheduler.py（项目根）
                                                  ↓ import meetup.cron
                                                  ↓
┌──────────┐    ┌─────────────┐    ┌──────────┐    ┌─────────────┐    ┌──────────────┐
│  user/   │ ← │  activity/   │ ← │ segment/  │ ← │ route_book/ │ ← │   meetup/    │
└──────────┘    └─────────────┘    └──────────┘    └─────────────┘    └──────────────┘
   ↑ ↑ ⤴────────┘  (R4-N1 既有漂移虚线 / Sprint 9+10 引入 / 7 处反向 / 见 §15.4)
   │ │              ↑                  ↑                ↑ ↑                ↑
   │ │              │                  │                │ │                │
   │ └─ user_id     └─ avg_speed       └─ name/         └─┴─ creator_id    └─ 自己
   │    nickname        trackpoints      distance/         + reference_line
   │                    (反转 LINESTRING) city
   │                                                  
   └─ storage/（共享 / 被 meetup + route_book 用 / 不属于业务依赖链）
       └─ LocalStorage.upload/delete（app/storage/local.py:49/85）
```

**箭头说明**：实线 ← = 设计的单向依赖（声明）/ 虚线 ⤴ = 既有反向漂移（Sprint 9+10 引入 / 不是 meetup 引入 / 但和 §15.2 计划反向 hook 一起算项目级架构治理待办）

**正向依赖**（约骑读这些模块）：
- `app/user/` — user_id (auth) / nickname
- `app/activity/` — activities.avg_speed JOIN（详情页"骑友均速"）/ trackpoints（路书衍生反转 LINESTRING）/ activity.user_id（路书衍生 IDOR 校验）
- `app/segment/` — segments 列表（路线下拉）/ name/distance/city（snapshot 来源）
- `app/storage/` — LocalStorage.upload/delete
- `app/route_book/` — 自己新建（约骑生态内部）
- `scheduler.py` 项目根 — 顶层 entrypoint import meetup.cron

### 15.2 反向 hook 清单（2 处 / spec 设计的有意反向 / **当前状态：待建** / R4-I3 措辞修正）

| # | 位置 | 当前状态 | 反向依赖说明 | 删除约骑模块时同步动作 |
|---|---|---|---|---|
| 1 | `app/user/service.py` 新增 `delete_user(db, user_id)` | **待建**（meetup 模块 ship 时同步加 / grep 2026-05-28：app/user/ 无 delete_user）| `import app.meetup.models` + query Meetup（user → meetup）| 整个 `delete_user` 函数删 / 或砍 meetup query 那段 |
| 2 | `app/segment/router.py` 加 `/api/segments/{id}/upcoming-meetups` endpoint | **待建**（grep 2026-05-28：app/segment/router.py 无此 endpoint）| `import app.meetup.models` + query Meetup（segment → meetup）| 整个 endpoint 删（1 个 endpoint）|

**反向 hook 数量**：2 处（待建 / 计划反向）/ 不是 100% 完全独立 / 但**模块边界清晰 + 设计阶段就标记 + ship 时同步加**。

**为什么接受反向 hook**：100 用户量级 / 工程务实 / 比 event listener 系统更轻 / Tim 2026-05-28 拍方案 A "承认局部反向 + spec 明确标记"。

### 15.3 模块删除 SOP（如果未来想砍约骑功能）

按顺序执行：

1. **数据库**：drop 4 张表（**顺序不可调换** / R4-I2 PostgreSQL DDL FK 约束规则：子表先于父表 / CASCADE 是 DML 行为不是 DDL 行为 / `DROP TABLE meetups` 时若 meetup_participants/meetup_media 仍存在会报 `ERROR: table meetups has dependent objects`）
   - `DROP TABLE meetup_media;`（子表 / FK→meetups）
   - `DROP TABLE meetup_participants;`（子表 / FK→meetups）
   - `DROP TABLE meetups;`（父表 / 还引用 route_books）
   - `DROP TABLE route_books;`（最底层）
   - drop partial unique index 自动随之消失

2. **代码**：删 2 整个模块文件夹
   - `rm -rf app/meetup/ app/route_book/`
   - **v1.6 修订 R5-I2**：`app/main.py` 删 `include_router(meetup_router)` + `include_router(route_book_router)` 两行（**反挂载** / 不删会让 FastAPI 启动 ImportError）

3. **反向 hook 清理**（同 §15.2 表 / 2 处）：
   - `app/user/service.py` 删 `delete_user` 函数或砍 meetup query 那段
   - `app/segment/router.py` 删 `/api/segments/{id}/upcoming-meetups` endpoint

4. **顶层 entrypoint**：
   - `scheduler.py` 项目根删 `_meetup_tick_counter` 段（保留 strava import tick try/except 不动）

5. **测试 + 部署**：
   - pytest 全跑 / 应无 ImportError
   - `docker compose up -d --build scheduler api`

**总改动量**：~10-20 行代码修改 + drop 4 表 + 2 目录删 = 5-15 分钟工作量。

### 15.4 项目级既有依赖漂移（**v1.6 修订 R5-I3 scope 收紧 / 本节仅列与本 spec 相关的 user→activity 漂移**）

> **scope 声明（R5-I3）**：本节**仅列与约骑模块涉及的 user→activity 漂移**（因约骑 §6.2 计划在 user.service.py 加 delete_user / 而 user 已反向 import activity / 与约骑反向 hook 同类型）。**全项目漂移**（user→segment / activity→segment/notification / segment→notification 等）属于项目级架构治理待办 / 不在本 spec scope。

`grep` 实证 2026-05-28：velo CLAUDE.md 原则 4 声明 **"User ← Activity ← Segment ← Notification ← Strava"** 单向依赖，但实际 `app/user/` 已反向 import `app/activity/` **共 7 处**（不是原 spec 写的 4 处 / `service.py` 自己其实不 import / 真实落点是 router.py + service_stats.py + service_social.py）：

```
app/user/router.py:20-23  (4 行 / 含 backfill_ftp / ftp_estimator / Activity 等)
app/user/service_stats.py:47-48  (2 行 / 训练负荷曲线)
app/user/service_social.py:53  (1 行 / 社交统计)
共 7 处反向 import / 全部由 Sprint 9+10 v5 训练分析功能引入
```

注意：`app/user/service.py` 自己**不**反向 import activity / 这是 v1.4 spec 写错被 round 4 reviewer 抓的真 bug。

**结论**：项目级 CLAUDE.md 单向依赖声明 vs 真实代码有漂移 / 不是本 spec 引入 / 但和约骑反向 hook（user → meetup / segment → meetup）一起属于**项目级架构治理待办**。建议未来专题处理（参考 memory `feedback_no_reverse_dep_in_compat_window` + agent-collab §4.0）。

---

## 16. 链接索引

- 用户故事 HTML：`.superpowers/brainstorm/56665-1779953873/content/user-story.html`
- 微信合规 memory：[[feedback_wechat_miniprogram_no_direct_social]]
- 并发处理 memory：[[feedback_savepoint_isolation_for_inner_modules]]
- 三审收敛 memory：[[feedback_three_review_pipeline]] / [[feedback_spec_three_round_review_convergence]] / [[feedback_spec_bug_fix_before_plans]] / [[feedback_reviewer_must_grep_dependency]]
- 战略 PRD：`docs/prd/velo-vision.md:355` / `velo-strategy.md:38-40` / `velo-product-spec.md:47`
- 现有代码事实：`app/segment/models.py:55-117` / `app/user/models.py:37-51` / `app/storage/local.py:85` / `scheduler.py:1-50`（项目根）/ `app/notification/models.py:130-134`（partial unique 先例）
