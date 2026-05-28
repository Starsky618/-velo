# 约骑模块 v1 设计文档（2026-05-28 brainstorm 成果）

> **本文档是什么**：把 2026-05-28 Tim 和 Claude 4 轮 brainstorm 拍下的决策落成工程师能照着做的技术骨架。后续 codex 据此出实施 plans。
>
> **修订记录**：
> - **2026-05-28 v1.0** 初稿（commit `89f71f2`）
> - **2026-05-28 v1.1** Round 1 三审整合：7 Critical / 13 Important / 4 Minor 修（commit `c8a69b9`）
> - **2026-05-28 v1.2** Round 2 三审整合：2 Critical / 10 Important / 7 Minor（本版）
>
> **标注约定**：
> - ✅ Tim 2026-05-28 明确拍定
> - 🔵 基于拍定方向的初步技术设计（字段名 / 路径可在 codex 实施时微调）
> - 📊 现有代码事实（grep 实证带 file:line 出处）
> - ⛔ v1 明确不做（v2 / v3 / 转 iOS app 后做）
>
> **产品故事**在 §3，**技术细节**在 §4-§9，**给 Tim 验收**在 §13。

---

## 1. 定位

velo v5 阶段引入"约骑"作为社交模块——支持骑友发起 / 加入约骑活动，让"渴望连接但不敢搭讪"的严肃骑手有半硬连接的入口。

战略层依据：
- ✅ `velo-vision.md:355` — v5/v6 主线"约骑 event 系统（发起/报名/提醒/完成）+ 路书机制"
- ✅ `velo-strategy.md:38-40` — "回应骑手孤独感" 的具体产品形式
- ✅ `velo-product-spec.md:47` — 核心产品洞察"渴望连接但不敢搭讪 / 柔性连接"

防火墙隔离（CLAUDE.md 防火墙式扩展）：
- ✅ 新建 `app/meetup/`（约骑活动）+ `app/route_book/`（路书）2 个独立模块
- ✅ 不修改核心表 `users` / `activities` / `segments`
- ✅ 单向依赖链：`User ← Activity ← Segment ← RouteBook ← Meetup`

---

## 2. v1 范围

| # | 功能 | 状态 | 工程量 |
|---|---|---|---|
| ① | 约骑活动 CRUD（创建 / 草稿 / 查 / 取消）| ✅ 必做 | 5 天 |
| ② | 路线选择下拉（复用现有 segment）| ✅ 必做 | 0.5 天 |
| ③ | 路书导入 + 从已有活动衍生（B2 / 纯展示不参与匹配）| ✅ 必做 | 2.5 天 |
| ⑤ | 路线详情页"本路线约骑"卡片 | ✅ 必做 | 0.5 天 |
| ⑦ | 媒体上传（图片 / 视频 / MIME 白名单 / 失败补偿）| ✅ 必做 | 2 天 |
| ④ | 路线足迹 / 打招呼卡片 | ⛔ v6 做（`velo-vision.md:355` feed/kudos 节奏）|
| ⑥ | 「为你推荐」算法匹配 | ⛔ v2 后做（100 用户量级冷启动无意义）|

**v1 总工程量**：~16 天 / 跨 3 个 sprint（详见 §11 task 拆解 / **v1.2 修订 R2-I1：原 15 天加和错误 / 改 16**）

---

## 3. 用户故事

### 3.1 陈哥发起约骑（happy path）

周五晚 9 点 → velo "约骑" tab → 右下 FAB ➕ → 填 7 字段（路线 / 配速档 / 时间 / 集合点 / 人数 / 备注 / 媒体）→ 孩子哭了"保存草稿" → 周六早 5 点恢复 → 发布 → 卡片立刻入约骑 tab list 顶部，状态 1/6（陈哥自动计入）。

**v1.2 修订 R2-I2**：分清楚"路线选择"vs"路书创建"两个不同概念。

**路线选择 2 种入口**（用户在创建约骑时选哪条路）：
- ① 从 segment 列表选（已有精选赛段）
- ② 从路书列表选（含自建路书）

**路书创建 2 种方式**（用户主动建路书时用哪种）：
- ① 上传 GPX 文件
- ② 从我已骑过的活动衍生（trackpoints 反向转 LINESTRING）

### 3.2 阿杰加入约骑

周五晚 11 点刷约骑 tab → 看到陈哥的卡片配速对得上 → 点详情 → 看到陈哥 FTP 280 / 老李 245 配速档对得上 → 点"加入"→ 按钮立刻变"已加入 ✓"/ 列表 3/6 → 周六 6:00 到集合点 → 6:30 出发 → 9:30 自动转 COMPLETED 进历史。

### 3.3 意外场景

| 场景 | 处理 |
|---|---|
| 🌧 出发前 30 min 内陈哥想取消 | ❌ 不允许（避免临时甩袖子）/ 出发前 30 min 之前可 cancel / 已加入者列表里看到"已取消"灰态 / **不发主动通知**（v1 无通知体系）|
| 🎯 5/6 人 + 两人同时点加入 | 行级锁 FOR UPDATE 物理保证只 1 人成功 / 另一人按钮变"已满员" / 满员后有人退出再开放报名 |
| ❌ 用户删账号 | 他发起的"已发布"约骑 → status='CANCELLED' / 他参与的约骑 → 从列表消失 + **名额自动空出** / 他创建的路书 → 保留供他人复用 / **他的 DRAFT 约骑 → 硬删（v1.2 修订 R2-L1）**|
| 🗑 admin 删 segment | 关联约骑保留路线名 / 距离 / 爬升**快照字段** / segment_id 设 NULL / 用户能看到"原路线已删除"但不能点进路线详情 |

### 3.4 5 条体验承诺

1. ✅ 创建一个约骑 ≤ 90 秒（含选路线 / 填字段 / 不传图）
2. ✅ 加入一个约骑 ≤ 3 秒（点加入即生效 / 不需审核 / 不需发起人同意）
3. ✅ 看见但不互动（微信小程序备案约束 / 见 §6.3）
4. ✅ 已结束不消失（COMPLETED 进历史 / 身份沉淀基础）
5. ✅ 路书复利（一次创建多人复用 / 默认公开 ✅ Tim 拍）

---

## 4. 数据模型（4 张新表）

### 4.1 meetups（约骑活动主表）🔵

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INT | PK | |
| `creator_id` | INT | FK→users.id ON DELETE SET NULL | 删账号 service hook 先 cancel 再删（见 §6.2）|
| `status` | VARCHAR(16) | CHECK IN ('DRAFT','OPEN','CANCELLED','COMPLETED') | 默认 DRAFT |
| `segment_id` | INT | FK→segments.id NULL ON DELETE SET NULL | 选 segment 路线时填 |
| `route_book_id` | INT | FK→route_books.id NULL ON DELETE SET NULL | 选自建路书时填 |
| `snapshot_route_name` | VARCHAR(128) | NOT NULL | 创建时从 segment/route_book 复制 / **v1.2 修订 R2-I10：发布后历史快照 / 不随源改名自动刷新** |
| `snapshot_distance` | FLOAT | NOT NULL | 距离快照（米）|
| `snapshot_climb` | FLOAT | NULL | 爬升快照（米）|
| `snapshot_city` | VARCHAR(32) | NOT NULL | city 快照 / 列表 city 筛用 |
| `start_time` | TIMESTAMPTZ | NOT NULL | 出发时间 |
| `estimated_end_time` | TIMESTAMPTZ | NOT NULL | demo `velo-v2.html:403-410` estEnd 公式算 |
| `meeting_point` | VARCHAR(128) | NOT NULL | demo MEETS 7 项 + 自定义 |
| `pace_level` | VARCHAR(16) | CHECK IN ('relaxed','cruise','training','race') | 4 档配速 |
| `max_participants` | INT | NOT NULL CHECK (2 ≤ n ≤ 20) | demo line 548 |
| `description` | TEXT | NULL | 备注（选填）|
| `created_at` / `updated_at` | TIMESTAMPTZ | tz-aware 沿用 segment pattern（📊 `segment/models.py:103`）|
| `cancelled_at` / `completed_at` | TIMESTAMPTZ | NULL | 状态转换时填 |

**v1.2 修订 R2-N6 完整 CHECK 约束**（alembic 显式 CheckConstraint / 复制 📊 `segment/models.py:109-117` 原文 / 防止打字漂移）：
- `ck_meetups_status`: `status IN ('DRAFT', 'OPEN', 'CANCELLED', 'COMPLETED')`
- `ck_meetups_pace_level`: `pace_level IN ('relaxed', 'cruise', 'training', 'race')`
- `ck_meetups_max`: `max_participants >= 2 AND max_participants <= 20`
- `ck_meetups_city` on snapshot_city: `snapshot_city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')`

**索引**：
- `(status, start_time)` — 约骑列表查询主索引
- `(creator_id, status)` — "我发起的"查询
- **partial UNIQUE INDEX** `(creator_id) WHERE status='DRAFT'` — 强制"每人最多 1 个草稿"
  - **v1.2 修订 R2-N5 ORM + alembic 双声明**：参照 📊 `app/notification/models.py:130-134` 现有 pattern → ORM models.py 加 `Index("uq_meetups_creator_draft", "creator_id", unique=True, postgresql_where=text("status='DRAFT'"))` + alembic migration 显式 `op.create_index(..., unique=True, postgresql_where="status='DRAFT'")`

### 4.2 meetup_participants（参与者表）🔵

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | INT | PK |
| `meetup_id` | INT | FK→meetups.id ON DELETE CASCADE |
| `user_id` | INT | FK→users.id ON DELETE CASCADE（删账号自动清掉记录 + 名额空出）|
| `is_creator` | BOOLEAN | DEFAULT false / 发起人标记计入 max |
| `joined_at` | TIMESTAMPTZ | |

**UNIQUE(meetup_id, user_id)**：防重复加入 + 配 FOR UPDATE 物理防超员

**索引**：`(user_id, joined_at)` "我加入的"

### 4.3 meetup_media（媒体附件）🔵

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | INT | PK |
| `meetup_id` | INT | FK→meetups.id ON DELETE CASCADE |
| `uploader_id` | INT | FK→users.id ON DELETE SET NULL |
| `type` | VARCHAR(16) | CHECK IN ('image','video')|
| `url` | VARCHAR(512) | `app/storage/` 上传后 URL |
| `caption` | VARCHAR(128) | NULL / service 层 HTML escape |
| `seq` | INT | 显示顺序 |
| `created_at` | TIMESTAMPTZ | |

**v1.2 修订 R2-C1 鉴权完整规则**（IDOR 防护）：
- 删媒体 = `media.uploader_id == current_user OR meetup.creator_id == current_user`
- **同时校验 `media.meetup_id == path_meetup_id`**（防"拿自己 meetup_id 删别人 media_id"跨父级删除）

**媒体上传安全闭环（沿用 v1.1）**：
- MIME 白名单：image/jpeg / image/png / image/webp / video/mp4
- 大小限制：图片 ≤ 5MB / 视频 ≤ 50MB
- caption 写入前 service 层 HTML escape
- DB 写入失败 → 删 storage 已上传文件（防孤儿文件）

### 4.4 route_books（路书 / 独立模块）🔵

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | INT | PK |
| `creator_id` | INT | FK→users.id ON DELETE SET NULL（保留路书供他人复用）|
| `name` | VARCHAR(128) | NOT NULL |
| `distance` | FLOAT | NOT NULL（米，沿用 📊 `segment/models.py:55` pattern）|
| `climb` | FLOAT | NULL（米，沿用 📊 `segment/models.py:56`）|
| `reference_line` | GEOMETRY(LINESTRING, 4326) | NOT NULL（复用 📊 `segment/models.py:69` PostGIS pattern）|
| `gpx_file_url` | VARCHAR(512) | NULL（原始 GPX 文件存 `app/storage/`）|
| `source` | VARCHAR(32) | CHECK IN ('gpx_upload','activity_derived') |
| `source_activity_id` | INT | FK→activities.id NULL（从活动衍生时记录来源 ON DELETE SET NULL）|
| `city` | VARCHAR(32) | NOT NULL `ck_route_books_city` 完整 7 枚举值（同 §4.1 列表）|
| `created_at` | TIMESTAMPTZ | tz-aware |

**v1.2 修订 R2-I5 visibility 决策落地**（Tim 已拍默认公开）：
- v1 路书一律公开 / 任何骑友可见可选 / **不加 visibility 列**
- v2 再加 `visibility ENUM('public','private')` + 默认 'public' 让用户选

**v1.1 C7 IDOR 防御（activity_derived 路径）**：service 层 `POST /api/route-books` source='activity_derived' 必须校验 `activity.user_id == current_user`，否则返回 403。

**关键产品定义**（Tim 2026-05-28 拍）：
- 路书 = "图纸"（用户主动定义"我打算骑哪")
- segment = 严格限制 + 排名的精选单元（管理员审核 / 不混 UGC）
- **路书 v1 不参与 segment 匹配算法**（防止野鸡 KOM 污染）

---

## 5. 状态机

```
┌─────────┐    publish    ┌──────────┐    cancel (出发前 30+ min)    ┌────────────┐
│  DRAFT  │ ────────────→ │   OPEN   │ ─────────────────────────────→│ CANCELLED  │
└────┬────┘  (creator only) └────┬─────┘                              └────────────┘
     │                           │
     │ DELETE                    │ cron 5 min/次：now() > estimated_end_time
     │ (硬删 / creator only)      ↓
     ↓                       ┌─────────────┐
   (deleted)                 │ COMPLETED   │
                             └─────────────┘
```

**时间边界规则**（所有路径含 ±30 秒缓冲）：
- 截止报名 = `start_time - 30 min`（含 ±30 秒缓冲）
- 退出截止 = `start_time - 30 min`（含 ±30 秒缓冲）
- 取消截止 = `start_time - 30 min`（含 ±30 秒缓冲）
- COMPLETED 自动转 = cron 5 分钟扫一次 `WHERE status='OPEN' AND now() > estimated_end_time`

**v1.2 修订 R2-N4 状态机异常路径**：
- 用户删 status != 'DRAFT' 的约骑 → 返回 **409 Conflict** + message "只能硬删草稿 / 已发布请用 cancel"

**参与者子状态**：JOINED ⇄ LEFT（LEFT = DELETE record，不留状态行）

---

## 6. 关键技术决策

### 6.1 并发控制 + IDOR 防护（v1.2 修订 R2-C1 全面扩展）

**复用项目 pattern**：CLAUDE.md 陷阱 #12 `.with_for_update().populate_existing().first()` + [[feedback_savepoint_isolation_for_inner_modules]]

**所有写接口必须的权限校验链**（v1.2 修订 R2-C1）：

| Endpoint | 校验链 |
|---|---|
| `POST /api/meetups` | 仅认证用户 / 无对象级校验 |
| `PATCH /api/meetups/{id}` | `meetup.creator_id == current_user` + `meetup.status == 'DRAFT'` |
| `POST /api/meetups/{id}/publish` | `meetup.creator_id == current_user` + `meetup.status == 'DRAFT'` |
| `POST /api/meetups/{id}/cancel` | `meetup.creator_id == current_user` + `meetup.status == 'OPEN'` + 时间边界 |
| `DELETE /api/meetups/{id}` | `meetup.creator_id == current_user` + `meetup.status == 'DRAFT'` |
| `POST /api/meetups/{id}/join` | 仅认证用户 + 时间边界 + 满员 / 重复检查 |
| `DELETE /api/meetups/{id}/leave` | 当前用户必须已加入 + 时间边界 |
| `POST /api/meetups/{id}/media` | `meetup.creator_id == current_user`（仅 creator 上传） |
| `DELETE /api/meetups/{id}/media/{media_id}` | `media.meetup_id == path_meetup_id` **AND** (`media.uploader_id == current_user` **OR** `meetup.creator_id == current_user`) |
| `POST /api/route-books` source='activity_derived' | `activity.user_id == current_user` |
| `DELETE /api/route-books/{id}` | `route_book.creator_id == current_user` |

**共享 helper（v1.2）**：
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

加入流程伪代码：
```python
with db.begin():
    meetup = _load_and_authorize_meetup(
        db, meetup_id, current_user,
        require_status=['OPEN'],
        check_time_cutoff=True,
    )
    count = db.query(MeetupParticipant).filter_by(meetup_id=meetup_id).count()
    if count >= meetup.max_participants:
        raise HTTPException(409, "meetup full")
    if db.query(MeetupParticipant).filter_by(meetup_id=meetup_id, user_id=current_user.id).first():
        raise HTTPException(409, "already joined")
    db.add(MeetupParticipant(meetup_id=meetup_id, user_id=current_user.id, is_creator=False))
```

**v1.2 修订 R2-I8 partial unique IntegrityError 处理**：
```python
# POST /api/meetups (status=DRAFT) 创建草稿
try:
    db.add(meetup)
    db.flush()
except IntegrityError as e:
    if 'uq_meetups_creator_draft' in str(e.orig):
        db.rollback()
        existing = db.query(Meetup).filter_by(
            creator_id=current_user.id, status='DRAFT'
        ).first()
        raise HTTPException(409, detail={
            "code": "draft_exists",
            "existing_draft_id": existing.id,
            "message": "你已有 1 个草稿，是否覆盖？"
        })
    raise
```

错误码区分：满员 = 409 / 截止过期 = 410 / 已取消 = 410 / 已加入 = 409+already_joined / 404 not found / 403 无权限 / 409+draft_exists 草稿冲突。

### 6.2 用户删账号级联策略（v1.2 修订 R2-I11 顺序保证）

**v1.2 修订 R2-I11 关键**：service 层必须**先 hook 处理用户关联约骑 / 再删 user**（防止 creator_id 已 NULL 时找不到关联）：

```python
def delete_user(db, user_id):
    with db.begin():
        # Step 1: 先 cancel 该用户发起的所有 OPEN 约骑
        db.query(Meetup).filter_by(
            creator_id=user_id, status='OPEN'
        ).update({'status': 'CANCELLED', 'cancelled_at': func.now()})
        
        # Step 2: 硬删该用户的 DRAFT 约骑（v1.2 修订 R2-L1）
        draft_ids = db.query(Meetup.id).filter_by(
            creator_id=user_id, status='DRAFT'
        ).all()
        for (mid,) in draft_ids:
            _delete_meetup_with_storage_cleanup(db, mid)  # 见 R2-I7
        
        # Step 3: 最后才删 user（触发 SET NULL cascade）
        db.query(User).filter_by(id=user_id).delete()
```

| 表 | 字段 | 策略 | 副作用 |
|---|---|---|---|
| `meetups` | `creator_id` | SET NULL（service hook 先 cancel OPEN + 硬删 DRAFT） | 已发布约骑变 CANCELLED / 草稿真删除 |
| `meetup_participants` | `user_id` | CASCADE 删 record | **名额自动空出 / 别人可补位** |
| `meetup_media` | `uploader_id` | SET NULL（媒体留存 / 不丢约骑视觉信息）| 媒体仍可见 / 鉴权降级到 creator |
| `route_books` | `creator_id` | SET NULL | 路书保留供他人复用 |
| `route_books` | `source_activity_id` | SET NULL（activity 删时）| 衍生关系断开 / 路书仍可用 |

### 6.3 微信小程序合规约束 ✅ Tim 拍

参考 [[feedback_wechat_miniprogram_no_direct_social]]：v1 砍所有"用户↔用户双向互动"：
- ⛔ 详情页点头像跳转私聊
- ⛔ 评论区 / 私信 / 点赞 / 打招呼
- ⛔ "@发起人" 提醒
- ⛔ 约骑群聊

允许的：
- ✅ 详情页单向看见昵称 / FTP / 均速 / 已加入列表
- ✅ 用户↔系统状态变更（join / leave / cancel / publish）

**均速字段说明**：约骑详情页"均速 31km/h" 不是 users 表字段，是 service 层 JOIN `activities.avg_speed`（📊 `app/activity/models.py` 字段）按最近 N 次活动聚合。**不在 users 表新增 avg_speed 列 / 防字段蔓延**。

### 6.4 cron 调度（v1.2 修订 R2-I3 路径 + 异常隔离）🔵

**📊 现状 grep**：调度器真实路径 `/Users/macbookair/Desktop/velo/scheduler.py`（项目根 / 不在 `app/strava/`）/ 当前使用 `while True + time.sleep(15)` 模式，15s tick 间隔 / `scheduler.py:43-48` 现有 `try/except` 包裹 import tick。

**v1.2 修订**：在项目根 `scheduler.py` while 循环加 `_meetup_tick_counter` 计数器，**保留现有 try/except 异常隔离**：

```python
_meetup_tick_counter = 0
while True:
    # 现有 strava import tick（保留 try/except）
    try:
        run_import_tick()
    except Exception:
        logger.exception("import tick 失败")
    
    _meetup_tick_counter += 1
    if _meetup_tick_counter >= 20:  # 15s × 20 = 5 min
        try:
            run_meetup_complete_tick()  # SELECT meetups WHERE status='OPEN' AND now()>estimated_end_time → UPDATE COMPLETED
        except Exception:
            logger.exception("meetup tick 失败")
        _meetup_tick_counter = 0
    
    time.sleep(15)
```

**关键纪律**（继承现有 scheduler）：任何异常都不能让 while 循环退出。两个 tick 独立 try/except 互不拖累。

`run_meetup_complete_tick()` 函数放在 `app/meetup/cron.py`（codex 实施时新建），scheduler.py 用 `from app.meetup.cron import run_meetup_complete_tick`。

**部署影响**：改 scheduler.py 必须 `docker compose up -d --build scheduler`（CLAUDE.md feedback_deploy_must_rebuild_all_affected_containers）/ 不能只 restart。

---

## 7. API endpoint 清单（~17 个）🔵

### 约骑模块（app/meetup/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/meetups` | 列表（filter: status / city / date_range / pace / page）/ **v1.2 修订 R2-I9：用 participants 聚合子查询 + media 首图子查询 + meetups 主查询 三段 / 不只 JOIN+GROUP BY** |
| GET | `/api/meetups/{id}` | 详情 |
| POST | `/api/meetups` | 创建（默认 status=DRAFT / IntegrityError → 409 draft_exists）|
| PATCH | `/api/meetups/{id}` | 修改（仅 DRAFT 可改 / 仅 creator / 可改字段 = 全部业务字段除 status / creator_id / created_at / id）|
| POST | `/api/meetups/{id}/publish` | DRAFT → OPEN（仅 creator）|
| POST | `/api/meetups/{id}/cancel` | OPEN → CANCELLED（仅 creator + 出发前 30 min + 30s 缓冲）|
| DELETE | `/api/meetups/{id}` | 硬删 / 仅 status='DRAFT' / 仅 creator / status≠DRAFT 返回 409 / 删前清理 storage 媒体文件（见 §6.2 helper）|
| POST | `/api/meetups/{id}/join` | 加入（行级锁）|
| DELETE | `/api/meetups/{id}/leave` | 退出（出发前 30 min + 30s 缓冲）|
| POST | `/api/meetups/{id}/media` | 上传媒体（仅 meetup creator）|
| DELETE | `/api/meetups/{id}/media/{media_id}` | 删媒体（meetup_id 与 path 匹配 + uploader_id 或 creator_id）|
| GET | `/api/meetups/my-draft` | 获取我的草稿（每人最多 1 / DB 层 partial unique 保证）|

### 路书模块（app/route_book/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/route-books` | 列表（filter: mine=1 / city）|
| GET | `/api/route-books/{id}` | 详情 |
| POST | `/api/route-books` | 创建（gpx_upload 或 activity_derived / activity_derived 必须校验 user_id）|
| DELETE | `/api/route-books/{id}` | 删除（仅 creator / 删前清理 storage gpx_file_url）|
| **GET** | **`/api/route-books/activity-candidates`** | **v1.2 修订 R2-I3：从已有活动衍生路书的候选列表 / 单独 endpoint / 不混进 GET /api/route-books filter** |

### 现有模块扩展

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/segments/{id}/upcoming-meetups` | 路线详情页⑤卡片（新增到 app/segment/router.py）|

---

## 8. 数据流图（3 关键场景 / v1.2 修订 R2-C2 媒体上传时序）

### 8.1 创建约骑（v1.2 修订 R2-C2：先建草稿拿 id / 再上传媒体）

```
小程序点 FAB ➕ → 创建 sheet
  ↓
GET /api/segments (路线下拉数据)
GET /api/route-books?mine=1 (我的路书列表)
GET /api/route-books/activity-candidates (我可衍生的活动 / 单独 endpoint)
  ↓
用户填字段（路线 / 配速 / 时间 / 集合点 / 人数 / 备注）
  ↓
【第 1 步】先建 DRAFT 草稿拿 meetup_id：
POST /api/meetups (status=DRAFT)
  ↳ service 层从 segment/route_book 复制 snapshot_* 字段
  ↳ IntegrityError(partial unique) → 409 + existing_draft_id（前端引导用户覆盖或编辑）
  ↳ 返回 meetup_id
  ↓
【第 2 步】上传媒体（用刚拿到的 meetup_id）：
POST /api/meetups/{meetup_id}/media (loop 用户选的图/视频)
  ↳ MIME 白名单 + 大小限制 + caption HTML escape
  ↳ storage 写入失败 → 删 DB record 防孤儿
  ↓
【第 3 步】用户点"发布"：
POST /api/meetups/{meetup_id}/publish
  ↳ status DRAFT → OPEN
  ↳ INSERT creator 到 participants is_creator=true
```

### 8.2 加入约骑

```
列表 → 详情 → 点加入
  ↓
POST /api/meetups/{id}/join
  ↓ (后端)
BEGIN
_load_and_authorize_meetup(require_status=['OPEN'], check_time_cutoff=True)
  → 404 / 410 / 503
count check / 用户未加入 check → 409
INSERT meetup_participants
COMMIT
  ↓
返回 200 + 更新后 participants 列表
前端：按钮变"已加入 ✓" + 卡片右下角 count+1
```

### 8.3 取消约骑（含 30s 缓冲）

```
发起人 → 详情 → 点取消
  ↓
POST /api/meetups/{id}/cancel
  ↓ (后端)
BEGIN
_load_and_authorize_meetup(require_creator=True, require_status=['OPEN'], check_time_cutoff=True)
  → 404 / 403 / 409 / 410
UPDATE status='CANCELLED', cancelled_at=now()
COMMIT
  ↓
返回 200
v1 不发主动通知（用户自己刷新看到灰态）
```

### 8.4 硬删草稿 + storage 清理（v1.2 修订 R2-I7）

```
发起人 → 草稿 → 点删除
  ↓
DELETE /api/meetups/{id}
  ↓ (后端)
BEGIN
_load_and_authorize_meetup(require_creator=True, require_status=['DRAFT'])
  → 404 / 403 / 409（status≠DRAFT）

# 先查媒体文件 url 列表
media_urls = SELECT url FROM meetup_media WHERE meetup_id=?

# 删 storage 文件（防孤儿）
for url in media_urls:
    storage.delete(url)  # 调 app/storage/local.py

# 再删 DB（CASCADE 自动连带 meetup_media records）
DELETE meetups WHERE id=?

COMMIT
```

---

## 9. 风险表（故障 5 维 / architect 信条 2 / v1.2 补全）

| # | 维度 | 风险 | 严重度 | 对策 |
|---|---|---|---|---|
| 1 | 崩溃 | 加入后 worker 崩 / 用户没收到 200 | 中 | UNIQUE 约束 + 用户 retry 自然幂等 / 前端按钮防抖 |
| 2 | 崩溃 | cron 跑 COMPLETED 时崩 | 低 | 下一个 5 min cron 接着扫 / 状态机自然恢复 |
| 3 | 并发 | 满员抢位 | 高 | FOR UPDATE + populate_existing（§6.1）|
| 4 | 并发 | cancel race（cancel 同时有人 join）| 高 | 同 FOR UPDATE 互斥 |
| 5 | 并发 | **partial unique 草稿并发创建** | 中 | **R2-I8：IntegrityError catch → 409 + existing_draft_id** |
| 6 | 批量 | 约骑列表 N+1 | 中 | **R2-I9：participants 聚合子查询 + media 首图子查询 + meetups 主查询 三段** |
| 7 | 边界 | 截止时间 ±30s 边界 | 中 | server-side 严格判 + 30 秒缓冲 |
| 8 | 边界 | max_participants=2 / 发起即满员 | 低 | CHECK(≥2) / 发起人 +1 时自动 |
| 9 | 边界 | 路书跨城市 / meetup snapshot_city 由所选路线自动填充 | 低 | 路书 city 不限制 / meetup snapshot_city 不让用户手动覆盖 |
| 10 | 级联 | 用户删账号 | 高 | **R2-I11 service hook 顺序：先 cancel OPEN → 硬删 DRAFT → 再删 user** |
| 11 | 级联 | segment 被 admin 删 / 关联约骑 | 高 | snapshot_route_name + segment_id SET NULL |
| 12 | 级联 | route_book 被 creator 删 / 关联约骑 | 中 | snapshot 字段保留 / route_book_id SET NULL |
| 13 | 合规 | 微信小程序备案合规变更 | 中 | v1 砍所有用户互动 / 政策变化 → 暂停部署 / 走法律咨询 |
| 14 | 安全 | 媒体上传 XSS / 注入 / 孤儿文件 | 中 | MIME 白名单 / 大小限制 / caption HTML escape / DB 失败删 storage 文件 |
| 15 | **安全** | **写接口 IDOR**（PATCH/publish/delete/media）| **高** | **R2-C1：所有写接口 + media 删 + meetup_id == path 校验 / §6.1 权限校验链表** |
| 16 | 安全 | 路书衍生 IDOR | 高 | service 层校验 activity.user_id |
| 17 | 安全 | **硬删草稿留 storage 孤儿文件** | **中** | **R2-I7：DELETE 草稿 service 先查 media url → 调 storage.delete → 再删 DB** |
| 18 | dialect | PostGIS LINESTRING 在 SQLite 测试 fixture 炸 | 中 | 陷阱 #15 dialect 守卫 / `if db.bind.dialect.name == "postgresql"` |
| 19 | **语义** | **snapshot 字段含义模糊（是否随源刷新）**| **低** | **R2-I10 spec 写死：发布后历史快照不随 segment/route_book 改名刷新** |

---

## 10. 测试策略

按 CLAUDE.md 原则 3 TDD 红→绿：
- **单元测试**（service 层）：状态机转换 / 并发 FOR UPDATE / 时间边界 / 级联策略 / 路书衍生算法
- **API 测试**（router 层）：每个 endpoint happy + 4 类错误码（404/403/409/410）/ 权限检查（IDOR / uploader_id / media.meetup_id 路径校验）/ 微信合规约束
- **集成测试**：创建→加入→取消 全链路 / 用户删账号级联 / cron 自动 COMPLETED / admin 删 segment 后约骑仍显示快照
- **避坑测试**：truthiness（陷阱 #1）/ tz-aware（陷阱 #2）/ SAVEPOINT（陷阱 #13）/ dialect 守卫（陷阱 #15）/ first() 后 None（陷阱 #4）

**真用回归 hot spot**（v1.2 修订 R2-I12 补全 / 必须真 PG / 单测覆盖不到）：
1. 满员抢位并发：两个小程序账号同时点最后一个名额
2. activity_derived 路书 LINESTRING 构建：真 PG 跑 ST_MakeLine
3. cron COMPLETED 转换 + scheduler 容器 rebuild 后真生效
4. **partial unique index 并发建草稿** → 第 2 个返回 409 而非 500
5. **admin 删 segment 后 snapshot 字段展示** → 列表/详情仍能看到原路线名
6. **DRAFT 删除后 storage 文件清理** → uploads/ 对应文件已删
7. **scheduler 双 tick 互不拖死** → 故意制造 meetup tick 异常 / 确认 strava import tick 继续跑
8. **partial unique SQLite fixture 覆盖**：单测在 SQLite 测不出（postgresql_where 不模拟）→ 真 PG 集成测验证 409 场景

---

## 11. 任务拆解（v1.2 工程量校验 = 16 天）🔵

| Task | 范围 | 工程量 |
|---|---|---|
| Task 1 | 数据模型 + Alembic 迁移（4 表 + partial unique on creator_id WHERE DRAFT + 完整 CHECK 约束 + PostGIS 索引）| 1 天 |
| Task 2 | 路书 service + API（创建 / 列表 / 详情 / 删除 + GPX 上传解析 + activity_derived 路径含 IDOR 校验 + ST_MakeLine + dialect 守卫 + storage 清理 + activity-candidates endpoint）| 2.5 天 |
| Task 3 | 约骑 service（CRUD + 状态机 + 时间边界 + snapshot 字段自动填充 + 共享 `_load_and_authorize_meetup` helper + IntegrityError → 409 处理）| 2 天 |
| Task 4 | 约骑 API（12 个 endpoint / 完整权限校验链）| 1.5 天 |
| Task 5 | 加入 / 退出（FOR UPDATE + 并发测试 + 共享 helper）| 1 天 |
| Task 6 | 媒体上传 + 删除（MIME 白名单 / 大小限制 / caption HTML escape / 失败补偿 / meetup_id == path 校验）| 1 天 |
| Task 7 | cron auto-complete（scheduler.py + _meetup_tick_counter / try/except 隔离）+ 用户删账号 service hook（先 cancel OPEN → 硬删 DRAFT → 再删 user）| 0.5 天 |
| Task 8 | segment router 扩展（upcoming-meetups）| 0.5 天 |
| Task 9 | 小程序前端 3 页（list / detail / create sheet 3 步流：先建 DRAFT → 传 media → publish）| 5 天 |
| Task 10 | 真用回归 + hotfix（8 类 hot spot 覆盖）| 1 天 |

**总计 1+2.5+2+1.5+1+1+0.5+0.5+5+1 = 16 天**（与 §2 一致 / v1.2 修订 R2-I1 算对）

---

## 12. 明确不做 ⛔

| # | 不做 | 理由 / 何时做 |
|---|---|---|
| 1 | 用户↔用户直接互动（私信/关注/评论/点赞/打招呼）| 微信备案约束 / 转 iOS app 阶段 |
| 2 | 「为你推荐」算法 | 100 用户量级冷启动无意义 / v2 后 |
| 3 | 路线足迹卡片 / 打招呼按钮 | v6 主线 |
| 4 | 路书参与 KOM 排行 | 防野鸡 KOM 污染精选 segment |
| 5 | 通知体系（cancel / 满员 / 出发提醒）| v1 用户自己刷新 / v2 加 |
| 6 | 草稿反向（OPEN → DRAFT）| 发布后只能 cancel |
| 7 | 跨城市约骑筛选（用户手动选 city）| snapshot_city 由所选路线决定 / 用户不能跨城手动覆盖 |
| 8 | 修改已发布约骑（OPEN → 改字段）| 只能 cancel 重发 |
| 9 | 路书第 3 种创建方式（选 segment 当路书）| segment 本身能直接选 / 转路书冗余 |
| 10 | 路书私密标记（visibility 字段）| v1 一律公开 / v2 加 |

---

## 13. 验收清单（给 Tim · v1.2）

Tim 逐条确认。任一 "不对" → 改 doc 再 review。

- [ ] **1**. 范围：v1 做 ① + ② + ③ + ⑤ + ⑦，④/⑥ 留 v6/v2，对吗？
- [ ] **2**. 路书定义：路书 = 用户自建图纸 / segment = 管理员精选排名单元 / 两者独立 / 路书不参与 KOM 排行，对吗？
- [ ] **3**. 路书 2 种创建方式（v1.2 修订）：上传 GPX / 从我已骑活动衍生。路线选择 2 种入口（创建约骑时选哪条路）：从 segment 选 / 从路书选，对吗？
- [ ] **4**. 状态机：DRAFT → OPEN → (CANCELLED \| COMPLETED) / DRAFT 可硬删 / OPEN 不可改字段 / 出发前 30 min（±30s）截止报名+退出+取消 / 出发后所有操作锁死，对吗？
- [ ] **5**. 微信合规：v1 砍所有用户间直接互动，允许单向看见列表，对吗？
- [ ] **6**. 满员抢位：物理上不可能超员 / 满员后有人退出再开放报名，对吗？
- [ ] **7**. admin 删 segment：约骑保留路线名/距离/爬升**快照**继续可见但不能点进路线详情。**Snapshot 是发布后历史快照 / 不随源改名自动刷新**（v1.2 修订 R2-I10），对吗？
- [ ] **8**. 用户删账号：service 先 cancel 他的 OPEN 约骑 → 硬删他的 DRAFT 约骑 → 再删 user / 他参与的约骑名额自动空出别人可补位 / 他创建的路书保留供他人复用 / 他上传的媒体保留（v1.2 修订 R2-I11 顺序），对吗？
- [ ] **9**. 工程量 ~16 天 / 跨 3 sprint 你能接受吗？
- [ ] **10**. 路书默认公开（任何骑友都能在约骑创建表里看到 + 选你创建的路书）/ v1 不加 visibility 列 / v2 再加"设为私密"开关 ✅ Tim 拍

---

## 14. v1.2 修订记录（Round 2 三审整合）

**Round 2 三 reviewer**（reviewer-spec-faithful / reviewer-integration / codex）共抓到 2 Critical / 10 Important / 7 Minor。本版处理状态：

| 来源 | 编号 | 问题 | 处理 |
|---|---|---|---|
| codex C1 | R2-C1 | IDOR 写接口收不干净（PATCH/publish/delete-draft 无 creator 校验 + media 删缺 meetup_id 路径校验）| ✅ §6.1 加权限校验链表 + 共享 `_load_and_authorize_meetup` helper |
| codex C2 + spec-faithful I4 | R2-C2 | 创建含媒体流程顺序不可执行 | ✅ §8.1 重写 3 步流：先建 DRAFT → 上传 media → publish |
| spec-faithful I1 | R2-I1 | 工程量加和 16 ≠ 声称 15 | ✅ §2 + §11 + §13 第 9 条统一 16 天 |
| spec-faithful I2 + integration I2 | R2-I2 | "路线 2 种"vs 3 个 bullet | ✅ §3.1 拆"路线选择 2 种入口"+"路书创建 2 种方式" |
| spec-faithful I3 + integration I3 + codex | R2-I3 | §8.1 `route-books?source=activity_derivable_for_user` undefined filter | ✅ §7 加新 endpoint `GET /api/route-books/activity-candidates` 单独 |
| integration I1 + codex | R2-I4 | scheduler 路径错（app/strava/scheduler.py → 真实是项目根 scheduler.py）+ 异常隔离 | ✅ §6.4 路径修正 + 保留现有 try/except + meetup tick 独立 try/except |
| spec-faithful I5 | R2-I5 | §13 第 10 条路书 default 公开 Tim 拍未落地 spec | ✅ §4.4 加 visibility 决策 v1 不加列 / §13 改 ✅ |
| codex I1 | R2-I8 | partial unique IntegrityError 转 409 没写 | ✅ §6.1 加 IntegrityError catch + 返回 409+existing_draft_id |
| codex I3 | R2-I9 | N+1 修复深度不够 | ✅ §7 GET /api/meetups 明确"participants 聚合子查询 + media 首图子查询 + meetups 主查询" |
| codex I4 | R2-I10 | snapshot 语义要写死 | ✅ §4.1 注"发布后历史快照不随源改名刷新" / §13 第 7 条强调 |
| codex I7 | R2-I11 | 用户删账号 auto cancel 顺序 race | ✅ §6.2 service hook 顺序伪代码：先 cancel OPEN → 硬删 DRAFT → 再删 user |
| codex I8 | R2-I12 | 真 PG 回归 hot spot 不全 | ✅ §10 加 4 类 hotspot（partial unique 并发 / admin 删 snapshot / DRAFT 删除 storage / scheduler 双 tick 互不拖死）|
| integration I4 + codex | R2-I7 | DELETE 草稿 storage 孤儿文件 | ✅ §8.4 新增数据流：先查 media url → storage.delete → 再删 DB |
| spec-faithful 漏实现 | R2-L1 | 用户删账号 DRAFT 处理路径未定义 | ✅ §6.2 service hook 加硬删 DRAFT 步骤 |
| spec-faithful N1 | R2-N1 | §9 vs §12 跨城市表述矛盾 | ✅ §9 风险 9 重述 / §12 第 7 条强调 snapshot_city 由路线决定 |
| spec-faithful N2 | R2-N2 | §14 4 Minor 表只列 2 行 | ✅ 本版 §14 表覆盖所有 R2 条目 |
| spec-faithful N3 | R2-N3 | §5 状态机图未命名框 | ✅ §5 重画清晰图 |
| spec-faithful N4 | R2-N4 | DELETE 非 DRAFT 返回码 | ✅ §5 注 409 + message |
| integration N1 | R2-N5 | partial unique ORM vs alembic 双声明 | ✅ §4.1 索引段注"ORM models.py + alembic migration 双写"+ 参照 notification 现有 pattern |
| integration N2 | R2-N6 | city 7 枚举完整字符串 | ✅ §4.1 CHECK 约束写出完整 7 枚举值 |
| integration N3 | R2-N7 | partial unique SQLite fixture 覆盖 | ✅ §10 真用回归 hot spot 第 8 条 |

---

## 15. 链接索引

- 用户故事 HTML（visual companion）：`.superpowers/brainstorm/56665-1779953873/content/user-story.html`
- 微信合规 memory：[[feedback_wechat_miniprogram_no_direct_social]]
- 并发处理 memory：[[feedback_savepoint_isolation_for_inner_modules]]
- review pipeline memory：[[feedback_three_review_pipeline]] / [[feedback_spec_three_round_review_convergence]]
- 战略 PRD：`docs/prd/velo-vision.md:355` / `docs/prd/velo-strategy.md:38-40` / `docs/prd/velo-product-spec.md:47`
- 现有代码事实：`app/segment/models.py:55-117` / `app/user/models.py:37-51` / `app/activity/models.py` avg_speed / `scheduler.py:1-50`（项目根）/ `app/notification/models.py:130-134`（partial unique 先例）
