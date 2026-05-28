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

**路线选择 2 种入口**：从 segment 列表选 / 从路书列表选
**路书创建 2 种方式**：上传 GPX / 从我已骑活动衍生

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
| `reference_line` | GEOMETRY(LINESTRING, 4326) | NOT NULL（复用 📊 `segment/models.py:69`）|
| `gpx_file_id` | VARCHAR(512) | NULL（v1.3 同 R3-I1 改名 file_id）|
| `source` | VARCHAR(32) | CHECK IN ('gpx_upload','activity_derived') |
| `source_activity_id` | INT | FK→activities.id NULL ON DELETE SET NULL |
| `city` | VARCHAR(32) | NOT NULL `ck_route_books_city` 完整 7 枚举 |
| `created_at` | TIMESTAMPTZ | |

**v1.2 visibility 决策**：v1 路书一律公开 / 不加 visibility 列 / v2 加。

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
| POST | `/api/route-books` | 创建（gpx_upload 或 activity_derived）|
| DELETE | `/api/route-books/{id}` | 删除（inline creator 校验 / 含 gpx storage 清理）|
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
| Task 2 | 路书 service + API（CRUD + GPX 上传 + activity_derived + IDOR + ST_MakeLine + dialect 守卫 + storage 清理 + activity-candidates endpoint）| 2.5 天 |
| Task 3 | 约骑 service（CRUD + 状态机 + 时间边界 + snapshot 字段自动填充 + `_load_and_authorize_meetup` helper + IntegrityError → 409 处理）| 2 天 |
| Task 4 | 约骑 API（12 个 endpoint / 完整权限校验链）| 1.5 天 |
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
- [ ] **3**. 路书 2 种创建方式（上传 GPX / 活动衍生）/ 路线选择 2 种入口（segment / 路书），对吗？
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

## 15. 链接索引

- 用户故事 HTML：`.superpowers/brainstorm/56665-1779953873/content/user-story.html`
- 微信合规 memory：[[feedback_wechat_miniprogram_no_direct_social]]
- 并发处理 memory：[[feedback_savepoint_isolation_for_inner_modules]]
- 三审收敛 memory：[[feedback_three_review_pipeline]] / [[feedback_spec_three_round_review_convergence]] / [[feedback_spec_bug_fix_before_plans]]
- 战略 PRD：`docs/prd/velo-vision.md:355` / `velo-strategy.md:38-40` / `velo-product-spec.md:47`
- 现有代码事实：`app/segment/models.py:55-117` / `app/user/models.py:37-51` / `app/storage/local.py:85` / `scheduler.py:1-50`（项目根）/ `app/notification/models.py:130-134`（partial unique 先例）
