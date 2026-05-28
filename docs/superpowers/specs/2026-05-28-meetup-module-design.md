# 约骑模块 v1 设计文档（2026-05-28 brainstorm 成果）

> **本文档是什么**：把 2026-05-28 Tim 和 Claude 4 轮 brainstorm 拍下的决策落成工程师能照着做的技术骨架。后续 codex 据此出实施 plans。
>
> **修订记录**：
> - **2026-05-28 v1.0** 初稿（commit `89f71f2`）
> - **2026-05-28 v1.1** 三 reviewer 审查后整合修复：7 Critical / 13 Important / 4 Minor（本版）
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
| ③ | 路书导入 + 从已有活动衍生（B2 / 纯展示不参与匹配）| ✅ 必做 | 2 天 |
| ⑤ | 路线详情页"本路线约骑"卡片 | ✅ 必做 | 0.5 天 |
| ⑦ | 媒体上传（图片 / 视频 / MIME 白名单 / 失败补偿）| ✅ 必做 | 2 天 |
| ④ | 路线足迹 / 打招呼卡片 | ⛔ v6 做（`velo-vision.md:355` feed/kudos 节奏）|
| ⑥ | 「为你推荐」算法匹配 | ⛔ v2 后做（100 用户量级冷启动无意义）|

**v1 总工程量**：~15 天 / 跨 3 个 sprint（详见 §11 task 拆解）

---

## 3. 用户故事

### 3.1 陈哥发起约骑（happy path）

周五晚 9 点 → velo "约骑" tab → 右下 FAB ➕ → 填 7 字段（路线 / 配速档 / 时间 / 集合点 / 人数 / 备注 / 媒体）→ 孩子哭了"保存草稿" → 周六早 5 点恢复 → 发布 → 卡片立刻入约骑 tab list 顶部，状态 1/6（陈哥自动计入）。

**路线 2 种来源**（v1.1 修订：删第 3 种"选 segment 当路书"冗余路径）：
- 已有路线下拉（复用 segment 列表）
- 上传 GPX 文件创建新路书（→ 同时进 route_books 表可复用）
- 从我已骑过的活动衍生路书（trackpoints 反向转 LINESTRING）

### 3.2 阿杰加入约骑

周五晚 11 点刷约骑 tab → 看到陈哥的卡片配速对得上 → 点详情 → 看到陈哥 FTP 280 / 老李 245 配速档对得上 → 点"加入"→ 按钮立刻变"已加入 ✓"/ 列表 3/6 → 周六 6:00 到集合点 → 6:30 出发 → 9:30 自动转 COMPLETED 进历史。

### 3.3 意外场景

| 场景 | 处理 |
|---|---|
| 🌧 出发前 30 min 内陈哥想取消 | ❌ 不允许（避免临时甩袖子）/ 出发前 30 min 之前可 cancel / 已加入者列表里看到"已取消"灰态 / **不发主动通知**（v1 无通知体系）|
| 🎯 5/6 人 + 两人同时点加入 | 行级锁 FOR UPDATE 物理保证只 1 人成功 / 另一人按钮变"已满员" / 满员后有人退出再开放报名 |
| ❌ 用户删账号 | 他发起的"已发布"约骑 → status='CANCELLED' / 他参与的约骑 → 从列表消失 + **名额自动空出**（Tim 拍）/ 他创建的路书 → 保留供他人复用 |
| 🗑 admin 删 segment | 关联约骑保留路线名 / 距离 / 爬升**快照字段**（v1.1 Tim 拍 C1）/ segment_id 设 NULL / 用户能看到"原路线已删除"但不能点进路线详情 |

### 3.4 5 条体验承诺

1. ✅ 创建一个约骑 ≤ 90 秒（含选路线 / 填字段 / 不传图）
2. ✅ 加入一个约骑 ≤ 3 秒（点加入即生效 / 不需审核 / 不需发起人同意）
3. ✅ 看见但不互动（微信小程序备案约束 / 见 §6.3）
4. ✅ 已结束不消失（COMPLETED 进历史 / 身份沉淀基础）
5. ✅ 路书复利（一次创建多人复用）

---

## 4. 数据模型（4 张新表）

### 4.1 meetups（约骑活动主表）🔵

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INT | PK | |
| `creator_id` | INT | FK→users.id ON DELETE SET NULL | 删账号 service 层自动 cancel |
| `status` | VARCHAR(16) | CHECK IN ('DRAFT','OPEN','CANCELLED','COMPLETED') | 默认 DRAFT |
| `segment_id` | INT | FK→segments.id NULL ON DELETE SET NULL | 选 segment 路线时填 |
| `route_book_id` | INT | FK→route_books.id NULL ON DELETE SET NULL | 选自建路书时填 |
| **`snapshot_route_name`** | **VARCHAR(128)** | **NOT NULL** | **v1.1 修订 C1：创建时从 segment/route_book 复制路线名 / admin 删源后仍显示** |
| **`snapshot_distance`** | **FLOAT** | **NOT NULL** | **v1.1 修订 C1：路线距离快照（米）** |
| **`snapshot_climb`** | **FLOAT** | **NULL** | **v1.1 修订 C1：爬升快照（米）** |
| **`snapshot_city`** | **VARCHAR(32)** | **NOT NULL CHECK** | **v1.1 修订 I9：city 快照供约骑列表 city 筛选用 / 7 城枚举沿用 segment** |
| `start_time` | TIMESTAMPTZ | NOT NULL | 出发时间 |
| `estimated_end_time` | TIMESTAMPTZ | NOT NULL | demo `velo-v2.html:403-410` estEnd 公式算 |
| `meeting_point` | VARCHAR(128) | NOT NULL | demo MEETS 7 项 + 自定义 |
| `pace_level` | VARCHAR(16) | CHECK IN ('relaxed','cruise','training','race') | 4 档配速 |
| `max_participants` | INT | NOT NULL CHECK (2 ≤ n ≤ 20) | demo line 548 |
| `description` | TEXT | NULL | 备注（选填）|
| `created_at` / `updated_at` | TIMESTAMPTZ | tz-aware 沿用 segment pattern（📊 `segment/models.py:103`）|
| `cancelled_at` / `completed_at` | TIMESTAMPTZ | NULL | 状态转换时填 |

**v1.1 修订 C1**：原 CHECK `segment_id IS NOT NULL OR route_book_id IS NOT NULL` **取消**（删 segment 时 SET NULL 会触发 CHECK fail 炸 500）。改为依赖 snapshot_route_name NOT NULL 保证有路线名显示。

**CHECK 约束**（alembic 显式 CheckConstraint 形式，沿用 📊 `segment/models.py:109-117` 写法）：
- `ck_meetups_status` on status
- `ck_meetups_pace_level` on pace_level  
- `ck_meetups_max` on max_participants (2-20)
- `ck_meetups_city` on snapshot_city（沿用 segment 7 城枚举）

**索引**：
- `(status, start_time)` — 约骑列表查询主索引
- `(creator_id, status)` — "我发起的"查询
- **v1.1 修订 C3**：`partial UNIQUE INDEX (creator_id) WHERE status='DRAFT'` — 强制"每人最多 1 个草稿"（alembic 用 `postgresql_where` 参数）

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
| **`uploader_id`** | **INT** | **FK→users.id ON DELETE SET NULL（v1.1 修订 C6）** |
| `type` | VARCHAR(16) | CHECK IN ('image','video')|
| `url` | VARCHAR(512) | `app/storage/` 上传后 URL |
| `caption` | VARCHAR(128) | NULL / **v1.1 修订 I10：service 层 HTML 转义防 XSS** |
| `seq` | INT | 显示顺序 |
| `created_at` | TIMESTAMPTZ | |

**v1.1 修订 C6 鉴权规则**：删媒体的权限 = `uploader_id == current_user OR meetup.creator_id == current_user`

**v1.1 修订 I10 媒体上传安全闭环**：
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
| `source` | VARCHAR(32) | CHECK IN ('gpx_upload','activity_derived') / **v1.1 修订 C2：保留 2 种（删第 3 种 segment_reference）** |
| `source_activity_id` | INT | FK→activities.id NULL（从活动衍生时记录来源）|
| `city` | VARCHAR(32) | **NOT NULL CHECK IN (...)** v1.1 修订 C4：与 segment 严格一致 7 城枚举 |
| `created_at` | TIMESTAMPTZ | tz-aware |

**v1.1 修订 C7 IDOR 防御**：service 层创建 route_book（activity_derived 路径）必须校验 `activity.user_id == current_user`，否则返回 403。

**关键产品定义**（Tim 2026-05-28 拍）：
- 路书 = "图纸"（用户主动定义"我打算骑哪")
- segment = 严格限制 + 排名的精选单元（管理员审核 / 不混 UGC）
- **路书 v1 不参与 segment 匹配算法**（防止野鸡 KOM 污染）

---

## 5. 状态机

```
                                ┌─────────────────┐
   creator delete draft         │                  │
   ←──────────────────          ↓                  │
                       ┌─────────┐    publish    ┌──────────┐    cancel (出发前 30+ min)    ┌────────────┐
                       │  DRAFT  │ ────────────→ │   OPEN   │ ─────────────────────────────→│ CANCELLED  │
                       └─────────┘  (creator only) └────┬─────┘                              └────────────┘
                                                       │
                                                       │ cron 5 min/次：now() > estimated_end_time
                                                       ↓
                                                 ┌─────────────┐
                                                 │ COMPLETED   │
                                                 └─────────────┘
```

**v1.1 修订 I12 草稿放弃路径**：`DELETE /api/meetups/{id}` 只能删 status='DRAFT' 的（OPEN / CANCELLED / COMPLETED 都不可硬删 / 保留历史）

**时间边界规则**（所有路径含 ±30 秒缓冲 / v1.1 修订 I1 统一）：
- 截止报名 = `start_time - 30 min`（含 ±30 秒缓冲）
- 退出截止 = `start_time - 30 min`（含 ±30 秒缓冲）
- 取消截止 = `start_time - 30 min`（含 ±30 秒缓冲 / **v1.1 修订 I1：原 §8.3 取消伪代码遗漏 30 秒缓冲，本次统一**）
- COMPLETED 自动转 = cron 5 分钟扫一次 `WHERE status='OPEN' AND now() > estimated_end_time`

**参与者子状态**：JOINED ⇄ LEFT（LEFT = DELETE record，不留状态行）

---

## 6. 关键技术决策

### 6.1 并发控制（行级锁 FOR UPDATE）✅ Tim 拍

**复用项目 pattern**：CLAUDE.md 陷阱 #12 `.with_for_update().populate_existing().first()`（v5 task-0.2 Codex 抓的 Critical）+ [[feedback_savepoint_isolation_for_inner_modules]]

加入流程伪代码（**v1.1 修订 I8：补 None 判断防 500**）：
```python
with db.begin():
    meetup = (
        db.query(Meetup)
        .filter(Meetup.id == meetup_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if meetup is None:                                    # ← v1.1 修订 I8：陷阱 #4
        raise HTTPException(404, "meetup not found")
    if meetup.status != 'OPEN':
        raise HTTPException(410, "meetup not open")
    cutoff = meetup.start_time - timedelta(minutes=30, seconds=30)  # ±30s 缓冲
    if datetime.now(UTC) > cutoff:
        raise HTTPException(410, "join cutoff passed")
    count = (
        db.query(MeetupParticipant)
        .filter(meetup_id=meetup_id)
        .count()
    )
    if count >= meetup.max_participants:
        raise HTTPException(409, "meetup full")
    if (
        db.query(MeetupParticipant)
        .filter_by(meetup_id=meetup_id, user_id=u.id)
        .first()
    ):
        raise HTTPException(409, "already joined")
    db.add(MeetupParticipant(meetup_id=meetup_id, user_id=u.id, is_creator=False))
    # commit on exit
```

**共享 helper（v1.1 修订 Important）**：join / cancel / leave 三处都需要 `SELECT ... FOR UPDATE + populate_existing + None 判断 + 时间边界`，应抽 `_lock_meetup_or_raise(db, meetup_id, current_user)` 共享。

错误码区分：满员 = 409 / 截止过期 = 410 / 已取消 = 410 / 已加入 = 409+already_joined / 404 not found / 403 无权限。

### 6.2 用户删账号级联策略 ✅ Tim 拍

| 表 | 字段 | 策略 | 副作用 |
|---|---|---|---|
| `meetups` | `creator_id` | SET NULL + service 自动 cancel | 已发布约骑变 CANCELLED |
| `meetup_participants` | `user_id` | CASCADE 删 record | **名额自动空出 / 别人可补位** |
| `meetup_media` | `uploader_id` | SET NULL（媒体留存 / 不丢约骑视觉信息）| 媒体仍可见 / 鉴权降级到 creator |
| `route_books` | `creator_id` | SET NULL | 路书保留供他人复用 |
| `route_books` | `source_activity_id` | FK 不 cascade（activity 删 → SET NULL）| 衍生关系断开 / 路书仍可用 |

**v1.1 修订 C7 IDOR 防御**（路书衍生）：
- `POST /api/route-books` source='activity_derived' 路径必须 service 层校验 `activity.user_id == current_user`
- 前端不显示其他用户活动 + 后端独立校验（前后端双保险）

### 6.3 微信小程序合规约束 ✅ Tim 拍

参考 [[feedback_wechat_miniprogram_no_direct_social]]：v1 砍所有"用户↔用户双向互动"：
- ⛔ 详情页点头像跳转私聊
- ⛔ 评论区 / 私信 / 点赞 / 打招呼
- ⛔ "@发起人" 提醒
- ⛔ 约骑群聊

允许的：
- ✅ 详情页单向看见昵称 / FTP / 均速 / 已加入列表
- ✅ 用户↔系统状态变更（join / leave / cancel / publish）

**均速字段说明（v1.1 修订 I11）**：约骑详情页"均速 31km/h" 不是 users 表字段，是 service 层 JOIN `activities.avg_speed`（📊 `app/activity/models.py` 字段）按最近 N 次活动聚合。**不在 users 表新增 avg_speed 列 / 防字段蔓延**。

### 6.4 cron 调度（v1.1 修订 I2 细化）🔵

**现状 grep**：`app/strava/scheduler.py` 使用 `while True + time.sleep(15)` 模式（**不是 rq-scheduler / 原 spec 措辞错误**），15s tick 间隔。

**v1.1 修订**：在 `scheduler.py` while 循环加 `_meetup_tick_counter` 计数器：
```python
_meetup_tick_counter = 0
while True:
    # 现有 import tick 逻辑
    run_strava_import_tick()
    
    _meetup_tick_counter += 1
    if _meetup_tick_counter >= 20:  # 15s × 20 = 5 min
        run_meetup_complete_tick()  # SELECT meetups WHERE status='OPEN' AND now()>estimated_end_time → UPDATE COMPLETED
        _meetup_tick_counter = 0
    
    time.sleep(15)
```

**部署影响**（v1.1 修订）：改 scheduler.py 必须 `docker compose up -d --build scheduler`（CLAUDE.md feedback_deploy_must_rebuild_all_affected_containers）/ 不能只 restart。

---

## 7. API endpoint 清单（~16 个）🔵

### 约骑模块（app/meetup/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/meetups` | 列表（filter: status / city / date_range / pace / page）/ **v1.1 修订 I7：用 JOIN + GROUP BY 聚合 participants_count 避免 N+1** |
| GET | `/api/meetups/{id}` | 详情 |
| POST | `/api/meetups` | 创建（默认 status=DRAFT / 自动写入 snapshot 字段从 segment 或 route_book）|
| PATCH | `/api/meetups/{id}` | 修改（**v1.1 修订 I4：仅 DRAFT 可改 / 可改字段集合 = 全部业务字段除 status / creator_id / created_at / snapshot_* 由 segment_id/route_book_id 变化时自动重算**）|
| POST | `/api/meetups/{id}/publish` | DRAFT → OPEN |
| POST | `/api/meetups/{id}/cancel` | OPEN → CANCELLED（出发前 30 min + 30s 缓冲）|
| DELETE | `/api/meetups/{id}` | **v1.1 修订 I12：硬删 / 仅 status='DRAFT' 可调用** |
| POST | `/api/meetups/{id}/join` | 加入（行级锁）|
| DELETE | `/api/meetups/{id}/leave` | 退出（出发前 30 min + 30s 缓冲）|
| POST | `/api/meetups/{id}/media` | 上传媒体（MIME 白名单 / 大小限制 / 失败补偿）|
| DELETE | `/api/meetups/{id}/media/{media_id}` | 删媒体（uploader_id 或 creator_id 才能删）|
| GET | `/api/meetups/my-draft` | 获取我的草稿（每人最多 1 / DB 层 partial unique 保证）|

### 路书模块（app/route_book/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/route-books` | 列表（filter: mine=1 / city）|
| GET | `/api/route-books/{id}` | 详情 |
| POST | `/api/route-books` | 创建（gpx_upload 或 activity_derived / activity_derived 必须校验 user_id）|
| DELETE | `/api/route-books/{id}` | 删除（仅 creator）|

### 现有模块扩展

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/segments/{id}/upcoming-meetups` | 路线详情页⑤卡片（新增到 app/segment/router.py）|

**v1.1 修订 C5**：原 §8.1 提到 `GET /api/activities?for_route_book=1` 在 activity router 不存在 / 改为 **route_book service 层直接 query activities 表 + trackpoints 表**，不动 activity router。

---

## 8. 数据流图（3 关键场景）

### 8.1 创建约骑（v1.1 修订 C5）

```
小程序点 FAB ➕ → 创建 sheet
  ↓
GET /api/segments (路线下拉数据)
GET /api/route-books?mine=1 (我的路书)
GET /api/route-books?source=activity_derivable_for_user 
    或 route_book service 内部查 activities（不调 activity router / 修订 C5）
  ↓
用户填字段 / 选媒体 → 上传媒体 POST /api/meetups/{id}/media
  ↓
保存草稿 POST /api/meetups (status=DRAFT / service 层自动复制 snapshot_* 字段从 segment/route_book)
  ↓
用户点发布 POST /api/meetups/{id}/publish (DRAFT→OPEN + 自动 INSERT creator 到 participants is_creator=true)
```

### 8.2 加入约骑

```
列表 → 详情 → 点加入
  ↓
POST /api/meetups/{id}/join
  ↓ (后端)
BEGIN
SELECT meetups WHERE id=? FOR UPDATE + populate_existing
None check → 404
status check / 时间边界(±30s) check / count check / 用户未加入 check
INSERT meetup_participants
COMMIT
  ↓
返回 200 + 更新后 participants 列表
前端：按钮变"已加入 ✓" + 卡片右下角 count+1
```

### 8.3 取消约骑（v1.1 修订 I1：加 30s 缓冲）

```
发起人 → 详情 → 点取消
  ↓
POST /api/meetups/{id}/cancel
  ↓ (后端)
BEGIN
SELECT meetups WHERE id=? FOR UPDATE + populate_existing
None check → 404
权限 check creator_id == current_user → 403
status check OPEN → 410
cutoff = start_time - timedelta(minutes=30, seconds=30)  ← v1.1 修订 I1 加 30s 缓冲
if now() > cutoff: raise 410
UPDATE status='CANCELLED', cancelled_at=now()
COMMIT
  ↓
返回 200
v1 不发主动通知（用户自己刷新看到灰态）
```

---

## 9. 风险表（故障 5 维 / architect 信条 2 / v1.1 补全）

| # | 维度 | 风险 | 严重度 | 对策 |
|---|---|---|---|---|
| 1 | 崩溃 | 加入后 worker 崩 / 用户没收到 200 | 中 | UNIQUE 约束 + 用户 retry 自然幂等 / 前端按钮防抖 |
| 2 | 崩溃 | cron 跑 COMPLETED 时崩 | 低 | 下一个 5 min cron 接着扫 / 状态机自然恢复 |
| 3 | 并发 | 满员抢位 | 高 | FOR UPDATE + populate_existing（§6.1）|
| 4 | 并发 | cancel race（cancel 同时有人 join）| 高 | 同 FOR UPDATE 互斥（cancel 也锁 meetup row）|
| 5 | 批量 | **约骑列表 N+1（卡片要展示参与者数 / 媒体）** | **中** | **v1.1 修订 I7：列表查询用 JOIN + GROUP BY 聚合 / 不在循环里逐条查** |
| 6 | 边界 | 截止时间 ±30s 边界 | 中 | server-side 严格判 + 30 秒缓冲（Tim 拍 / 4 个时间点全统一）|
| 7 | 边界 | max_participants=2 / 发起即满员 | 低 | CHECK(≥2) / 发起人 +1 时自动 / 加入逻辑统一 |
| 8 | 边界 | 路书跨城市（路书 city=taiyuan / meetup 创建者在 chengdu）| 低 | 不限制 / 路书 city 仅元数据 / meeting_point 字符串自由 / 约骑 snapshot_city 由用户选路线决定 |
| 9 | 级联 | 用户删账号 | 高 | §6.2 三类策略（meetup + media + route_book）|
| 10 | 级联 | segment 被 admin 删 / 关联约骑 | 高 | **v1.1 修订 C1：snapshot_route_name + segment_id SET NULL / 不让 CHECK 炸** |
| 11 | 级联 | route_book 被 creator 删 / 关联约骑 | 中 | snapshot 字段保留 / route_book_id SET NULL |
| 12 | **合规** | **微信小程序备案合规变更** | **中** | **v1.1 修订 I3：v1 砍所有用户互动 / 若小程序审核后政策变化 → 暂停部署 / 走法律咨询 → 不主动绕 / [[feedback_wechat_miniprogram_no_direct_social]] 文档更新** |
| 13 | **安全** | **媒体上传 XSS / 注入 / 孤儿文件** | **中** | **v1.1 修订 I10：MIME 白名单 / 大小限制 / caption HTML escape / DB 失败删 storage 文件** |
| 14 | **安全** | **路书衍生 IDOR**（用他人 activity_id）| **高** | **v1.1 修订 C7：service 层校验 activity.user_id == current_user / 前后端双保险** |
| 15 | **dialect** | **PostGIS LINESTRING 在 SQLite 测试 fixture 炸** | **中** | **v1.1 修订 I6：陷阱 #15 dialect 守卫 / `if db.bind.dialect.name == "postgresql"` / 抽纯函数算法 + 真 PG 集成测** |

---

## 10. 测试策略

按 CLAUDE.md 原则 3 TDD 红→绿：
- **单元测试**（service 层）：状态机转换 / 并发 FOR UPDATE / 时间边界 / 级联策略 / 路书衍生算法（纯函数抽出来易测）
- **API 测试**（router 层）：每个 endpoint happy + 4 类错误码（404/403/409/410）/ 权限检查（IDOR / uploader_id）/ 微信合规约束（评论字段不存在）
- **集成测试**：创建→加入→取消 全链路 / 用户删账号级联 / cron 自动 COMPLETED / admin 删 segment 后约骑仍显示快照
- **避坑测试**：truthiness（CLAUDE.md 陷阱 #1）/ tz-aware（陷阱 #2）/ SAVEPOINT（陷阱 #13）/ SQLite vs PG dialect 守卫（陷阱 #15 — 路书 PostGIS 必须 PG 守卫）/ first() 后 None（陷阱 #4）

**真用回归 hot spot**（必须真 PG / 不是单测能覆盖的）：
1. 满员抢位并发：两个小程序账号同时点最后一个名额（单线程测试漏）
2. activity_derived 路书 LINESTRING 构建：真 PG 跑 ST_MakeLine
3. cron COMPLETED 转换 + scheduler 容器 rebuild 后真生效（陷阱：只 restart 不 rebuild）

---

## 11. 任务拆解预估 🔵（v1.1 与 §2 工程量对齐）

| Task | 范围 | 工程量 |
|---|---|---|
| Task 1 | 数据模型 + Alembic 迁移（4 表 + partial unique + CHECK 约束 + PostGIS 索引）| 1 天 |
| Task 2 | 路书 service + API（创建 / 列表 / 详情 / 删除）+ GPX 上传解析 + activity_derived 路径（含 IDOR 校验 + ST_MakeLine + dialect 守卫）| 2.5 天 |
| Task 3 | 约骑 service（CRUD + 状态机 + 时间边界 + snapshot 字段自动填充 + 共享 _lock_meetup helper）| 2 天 |
| Task 4 | 约骑 API（12 个 endpoint）| 1.5 天 |
| Task 5 | 加入 / 退出（FOR UPDATE + 并发测试 + 共享 lock helper）| 1 天 |
| Task 6 | 媒体上传（MIME 白名单 / 大小限制 / caption 转义 / 失败补偿）| 1 天 |
| Task 7 | cron auto-complete（在 scheduler.py 加 _meetup_tick_counter / 用户删账号级联 / scheduler 容器 rebuild）| 0.5 天 |
| Task 8 | segment router 扩展（upcoming-meetups）| 0.5 天 |
| Task 9 | 小程序前端 3 页（list / detail / create sheet）/ **v1.1 修订 I13：3→5 天（4 数据源跨模块状态机表单）** | 5 天 |
| Task 10 | 真用回归 + hotfix | 1 天 |

**v1 总工程量**：~15 天 / 跨 3 个 sprint（与 §2 一致）

---

## 12. 明确不做 ⛔

| # | 不做 | 理由 / 何时做 |
|---|---|---|
| 1 | 用户↔用户直接互动（私信/关注/评论/点赞/打招呼）| 微信备案约束 / 转 iOS app 阶段 |
| 2 | 「为你推荐」算法 | 100 用户量级冷启动无意义 / v2 后 |
| 3 | 路线足迹卡片 / 打招呼按钮 | v6 主线（velo-vision.md:355）|
| 4 | 路书参与 KOM 排行 | 防野鸡 KOM 污染精选 segment |
| 5 | 通知体系（cancel / 满员 / 出发提醒）| v1 用户自己刷新 / v2 加 |
| 6 | 草稿反向（OPEN → DRAFT）| 发布后只能 cancel |
| 7 | 跨城市约骑筛选 | 约骑 snapshot_city 由路线决定 / 不让用户跨城选 |
| 8 | 修改已发布约骑（OPEN → 改字段）| 只能 cancel 重发 |
| 9 | **路书第 3 种创建方式（选 segment 当路书）**| **v1.1 Tim 拍 C2：segment 本身能直接选 / 转路书冗余** |

---

## 13. 验收清单（给 Tim · v1.1 修订）

Tim 逐条确认。任一 "不对" → 改 doc 再 review。

- [ ] **1**. 范围：v1 做 ① + ② + ③ + ⑤ + ⑦（约骑活动 + 路线下拉 + 路书 + 路线详情入口 + 媒体），④/⑥ 留 v6/v2，对吗？
- [ ] **2**. 路书定义：路书 = 用户自建图纸 / segment = 管理员精选排名单元 / 两者独立 / 路书不参与 KOM 排行，对吗？
- [ ] **3**. 路书 2 种创建方式：上传 GPX / 从我已骑活动衍生（删 v1.0 第 3 种 segment_reference 冗余），对吗？
- [ ] **4**. 状态机：DRAFT → OPEN → (CANCELLED \| COMPLETED) / DRAFT 可硬删 / OPEN 不可改字段（只能 cancel 重发）/ 出发前 30 min（±30s 缓冲）截止报名+退出+取消 / 出发后所有操作锁死，对吗？
- [ ] **5**. 微信合规：v1 砍所有用户间直接互动（评论 / 私信 / 打招呼按钮 / 跳转私聊 / 关注），允许单向看见列表，对吗？
- [ ] **6**. 满员抢位：物理上不可能超员 / 满员后有人退出再开放报名（不是先到先得，是从那一刻起再点的人能加），对吗？
- [ ] **7**. admin 删 segment：约骑保留路线名/距离/爬升**快照**继续可见但不能点进路线详情（v1.1 修订 C1），对吗？
- [ ] **8**. 用户删账号：他发起的约骑 auto cancel / 他参与的约骑名额自动空出别人可补位 / 他创建的路书保留供他人复用 / 他上传的媒体保留（uploader_id SET NULL），对吗？
- [ ] **9**. 工程量 ~15 天 / 跨 3 sprint 你能接受吗？还是想砍哪个 task 进一步压缩？
- [ ] **10**. ⚠ 待拍：路书默认**公开**（任何骑友都能在约骑创建表里看到 + 选你创建的路书）还是默认**私密**（只创建者自己能选）？默认公开 = 路书复利更强但创建者可能不愿暴露"我探的私路"/ 默认私密 = 安全但路书生态起不来。我推荐默认公开 + 后续 v2 给用户加一个"设为私密路书"的开关。你拍 y/n / 或者 v1 就直接两选项都给（多 0.5 天工程量）。

---

## 14. v1.1 修订记录（reviewer 抓的全部问题处理状态）

**3 个 reviewer**（reviewer-spec-faithful / reviewer-integration / codex）共抓到 7 Critical / 13 Important / 4 Minor，本版处理状态：

| 来源 | 问题 | 处理 |
|---|---|---|
| codex C1 | FK SET NULL + CHECK 打架 | ✅ 修：删 CHECK / 加 snapshot_route_name + snapshot_distance + snapshot_climb + snapshot_city |
| spec-faithful C2 | §13 路书第 3 种 vs §4.4 source 枚举 | ✅ 修：Tim 拍删第 3 种 / §13 改 2 种 / §12 加第 9 条 |
| spec-faithful C3 | 草稿"每人最多 1" 无 DB 约束 | ✅ 修：§4.1 加 partial unique index |
| integration C1 | route_books.city 无 CHECK | ✅ 修：§4.4 明确 CHECK 约束 |
| integration C2 | `for_route_book` activity router 不存在 | ✅ 修：§8.1 改 route_book service 内查 / 不动 activity router |
| integration C3 | meetup_media 缺 uploader_id | ✅ 修：§4.3 加 uploader_id FK |
| codex C2 | 路书衍生 IDOR | ✅ 修：§6.2 + §4.4 加 service 层校验 |
| spec-faithful I1 | §6.1 加入有 30s 缓冲 / §8.3 取消无 | ✅ 修：§5 + §8.3 统一 30s 缓冲 |
| integration I1 / codex I4 | cron 说"rq-scheduler" 实际是 while+sleep | ✅ 修：§6.4 细化 _meetup_tick_counter 模式 |
| spec-faithful I3 | §6.3 合规决策 §9 无对应 | ✅ 修：§9 加风险 12 |
| spec-faithful I4 | PATCH 哪些字段可改未定义 | ✅ 修：§7 明确 |
| spec-faithful I5 | §2 工程量 vs §11 不一致 | ✅ 修：§2 和 §11 统一 15 天 |
| integration I3 / codex I5 | trackpoints→LINESTRING dialect 守卫 | ✅ 修：§9 加风险 15 / §10 测试策略加 |
| codex I1 / I7 | 列表 N+1 | ✅ 修：§9 加风险 5 / §7 endpoint 注 GROUP BY |
| codex I2 / I8 | first() 后缺 404 | ✅ 修：§6.1 伪代码 + §8.2 数据流 |
| codex I3 / I9 | meetups 无 city 字段但 GET 支持 city filter | ✅ 修：§4.1 加 snapshot_city |
| codex I6 / I10 | 媒体上传安全 | ✅ 修：§4.3 + §9 风险 13 |
| integration I2 | avg_speed 跨模块 join | ✅ 修：§6.3 明确 |
| spec-faithful I12 | DRAFT 放弃路径未定义 | ✅ 修：§5 加 DRAFT delete |
| codex I13 | Task 9 前端 3 天低估 | ✅ 修：§11 Task 9 改 5 天 |
| spec-faithful M9 | feedback_wechat_miniprogram_no_direct_social memory 不存在 | ❌ 误报 / 本 session 已新建 / reviewer 派出前快照未见 |
| spec-faithful M10 | estimated_end_time demo 路径未给 | ✅ 修：§4.1 标 `velo-v2.html:403-410` |

---

## 15. 链接索引

- 用户故事 HTML（visual companion）：`.superpowers/brainstorm/56665-1779953873/content/user-story.html`
- 微信合规 memory：[[feedback_wechat_miniprogram_no_direct_social]]
- 并发处理 memory：[[feedback_savepoint_isolation_for_inner_modules]]
- review pipeline memory：[[feedback_three_review_pipeline]]
- 战略 PRD：`docs/prd/velo-vision.md:355` / `docs/prd/velo-strategy.md:38-40` / `docs/prd/velo-product-spec.md:47`
- 现有代码事实：`app/segment/models.py:55-117` / `app/user/models.py:37-51` / `app/activity/models.py` avg_speed / `app/strava/scheduler.py` while loop
