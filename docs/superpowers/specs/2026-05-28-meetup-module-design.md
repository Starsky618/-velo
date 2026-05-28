# 约骑模块 v1 设计文档（2026-05-28 brainstorm 成果）

> **本文档是什么**：把 2026-05-28 Tim 和 Claude 4 轮 brainstorm 拍下的决策落成工程师能照着做的技术骨架。后续 codex 据此出实施 plans。
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
| ① | 约骑活动 CRUD（创建 / 草稿 / 查 / 取消）| ✅ | 5-7 天 |
| ② | 路线选择下拉（复用现有 segment）| ✅ | 0.5 天 |
| ③ | 路书导入 + 从已有活动衍生 | ✅ B2 方案 / 纯展示不参与匹配 | 1.5-2 天 |
| ⑤ | 路线详情页"本路线约骑"卡片 | ✅ | 0.5 天 |
| ⑦ | 媒体上传（图片 / 视频）| ✅ | 2 天 |
| ④ | 路线足迹 / 打招呼卡片 | ⛔ v6 做（`velo-vision.md:355` feed/kudos 节奏）|
| ⑥ | 「为你推荐」算法匹配 | ⛔ v2 后做（100 用户量级冷启动无意义）|

**总工程量**：~10-13 天 / 跨 2-3 个 sprint

---

## 3. 用户故事

### 3.1 陈哥发起约骑（happy path）

周五晚 9 点 → velo "约骑" tab → 右下 FAB ➕ → 填 7 字段（路线 / 配速档 / 时间 / 集合点 / 人数 / 备注 / 媒体）→ 孩子哭了"保存草稿" → 周六早 5 点恢复 → 发布 → 卡片立刻入约骑 tab list 顶部，状态 1/6（陈哥自动计入）。

路线 3 种来源：
- 已有路线下拉（复用 segment 列表）
- 上传 GPX 文件创建新路书
- 从我已骑过的活动衍生路书（trackpoints 反向转 LINESTRING）

### 3.2 阿杰加入约骑

周五晚 11 点刷约骑 tab → 看到陈哥的卡片 配速对得上 → 点详情 → 看到陈哥 FTP 280 / 老李 245 配速档对得上 → 点"加入"→ 按钮立刻变"已加入 ✓"/ 列表 3/6 → 周六 6:00 到集合点 → 6:30 出发 → 9:30 自动转 COMPLETED 进历史。

### 3.3 意外场景

| 场景 | 处理 |
|---|---|
| 🌧 出发前 30 min 内陈哥想取消 | ❌ 不允许（避免临时甩袖子）/ 出发前 30 min 之前可 cancel / 已加入者列表里看到"已取消"灰态 / **不发主动通知**（v1 无通知体系）|
| 🎯 5/6 人 + 两人同时点加入 | 行级锁 FOR UPDATE 物理保证只 1 人成功 / 另一人按钮变"已满员" / 满员后有人退出再开放报名 |
| ❌ 用户删账号 | 他发起的"已发布"约骑 → status='CANCELLED' / 他参与的约骑 → 从列表消失 + **名额自动空出**（Tim 拍）/ 他创建的路书 → 保留供他人复用 |

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
| `segment_id` | INT | FK→segments.id NULL ON DELETE SET NULL | 选 segment 路线 |
| `route_book_id` | INT | FK→route_books.id NULL ON DELETE SET NULL | 选自建路书 |
| `start_time` | TIMESTAMPTZ | NOT NULL | 出发时间 |
| `estimated_end_time` | TIMESTAMPTZ | NOT NULL | demo line 403-410 公式算 |
| `meeting_point` | VARCHAR(128) | NOT NULL | demo MEETS 7 项 + 自定义 |
| `pace_level` | VARCHAR(16) | CHECK IN ('relaxed','cruise','training','race') | 4 档配速 |
| `max_participants` | INT | NOT NULL CHECK (2 ≤ n ≤ 20) | demo line 548 |
| `description` | TEXT | NULL | 备注（选填）|
| `created_at` / `updated_at` | TIMESTAMPTZ | tz-aware 沿用 segment pattern（📊 `segment/models.py:103`）|
| `cancelled_at` / `completed_at` | TIMESTAMPTZ | NULL | 状态转换时填 |

**CHECK 约束**：`segment_id IS NOT NULL OR route_book_id IS NOT NULL`（路书必选 / 决策 6）

**索引**：`(status, start_time)` 列表查询 / `(creator_id, status)` "我发起的"

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
| `type` | VARCHAR(16) | CHECK IN ('image','video')|
| `url` | VARCHAR(512) | `app/storage/` 上传后 URL |
| `caption` | VARCHAR(128) | NULL |
| `seq` | INT | 显示顺序 |

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
| `source_activity_id` | INT | FK→activities.id NULL（从活动衍生时记录来源）|
| `city` | VARCHAR(32) | 沿用 📊 `segment/models.py:114-117` 7 城枚举 |
| `created_at` | TIMESTAMPTZ | tz-aware |

**关键产品定义**（Tim 2026-05-28 拍）：
- 路书 = "图纸"（用户主动定义"我打算骑哪")
- segment = 严格限制 + 排名的精选单元（管理员审核 / 不混 UGC）
- **路书 v1 不参与 segment 匹配算法**（防止野鸡 KOM 污染）

---

## 5. 状态机

```
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

**时间边界规则**（含 ±30 秒缓冲）：
- 截止报名 = `start_time - 30 min`
- 退出截止 = `start_time - 30 min`（同截止）
- 取消截止 = `start_time - 30 min`（发起人也不能临时甩袖子）
- COMPLETED 自动转 = cron 每 5 分钟扫一次 `WHERE status='OPEN' AND now() > estimated_end_time`

**参与者子状态**：JOINED ⇄ LEFT（LEFT = DELETE record，不留状态行）

---

## 6. 关键技术决策

### 6.1 并发控制（行级锁 FOR UPDATE）✅ Tim 拍

**复用项目 pattern**：CLAUDE.md 陷阱 #12 `.with_for_update().populate_existing().first()`（v5 task-0.2 Codex 抓的 Critical）+ [[feedback_savepoint_isolation_for_inner_modules]]

加入流程伪代码：
```python
with db.begin():
    meetup = db.query(Meetup).filter(id=meetup_id).with_for_update().populate_existing().first()
    if meetup.status != 'OPEN': raise 410
    if datetime.now(UTC) > meetup.start_time - timedelta(minutes=30, seconds=30): raise 410
    count = db.query(MeetupParticipant).filter(meetup_id=meetup_id).count()
    if count >= meetup.max_participants: raise 409
    if db.query(MeetupParticipant).filter_by(meetup_id=meetup_id, user_id=u.id).first(): raise 409
    db.add(MeetupParticipant(meetup_id, user_id, is_creator=False, joined_at=now))
    # commit on exit
```

错误码区分：满员 = 409 / 截止过期 = 410 / 已取消 = 410 / 已加入 = 409+already_joined。

### 6.2 用户删账号级联策略 ✅ Tim 拍

| 表 | 字段 | 策略 | 副作用 |
|---|---|---|---|
| `meetups` | `creator_id` | SET NULL + service 自动 cancel | 已发布约骑变 CANCELLED |
| `meetup_participants` | `user_id` | CASCADE 删 record | **名额自动空出 / 别人可补位** |
| `route_books` | `creator_id` | SET NULL | 路书保留供他人复用 |

### 6.3 微信小程序合规约束 ✅ Tim 拍

参考 [[feedback_wechat_miniprogram_no_direct_social]]：v1 砍所有"用户↔用户双向互动"：
- ⛔ 详情页点头像跳转私聊
- ⛔ 评论区 / 私信 / 点赞 / 打招呼
- ⛔ "@发起人" 提醒
- ⛔ 约骑群聊

允许的：
- ✅ 详情页单向看见昵称 / FTP / 均速 / 已加入列表
- ✅ 用户↔系统状态变更（join / leave / cancel / publish）

### 6.4 cron 调度 🔵

每 5 分钟扫 `meetups WHERE status='OPEN' AND now() > estimated_end_time` → UPDATE status='COMPLETED', completed_at=now()。复用项目现有 `rq-scheduler` pattern（参考 `app/strava/import_scheduler.py` 实现风格）。

---

## 7. API endpoint 清单（~16 个）🔵

### 约骑模块（app/meetup/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/meetups` | 列表（filter: status / city / date_range / pace / page）|
| GET | `/api/meetups/{id}` | 详情 |
| POST | `/api/meetups` | 创建（默认 status=DRAFT）|
| PATCH | `/api/meetups/{id}` | 修改（仅 DRAFT 可改 / OPEN 不允许）|
| POST | `/api/meetups/{id}/publish` | DRAFT → OPEN |
| POST | `/api/meetups/{id}/cancel` | OPEN → CANCELLED（出发前 30 min+）|
| POST | `/api/meetups/{id}/join` | 加入（行级锁）|
| DELETE | `/api/meetups/{id}/leave` | 退出（出发前 30 min+）|
| POST | `/api/meetups/{id}/media` | 上传媒体 |
| DELETE | `/api/meetups/{id}/media/{media_id}` | 删媒体 |
| GET | `/api/meetups/my-draft` | 获取我的草稿（每人最多 1）|

### 路书模块（app/route_book/router.py）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/route-books` | 列表（filter: mine=1 / city）|
| GET | `/api/route-books/{id}` | 详情 |
| POST | `/api/route-books` | 创建（gpx_upload 或 activity_derived）|
| DELETE | `/api/route-books/{id}` | 删除（仅 creator）|

### 现有模块扩展

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/segments/{id}/upcoming-meetups` | 路线详情页⑤卡片（新增到 app/segment/router.py）|

---

## 8. 数据流图（3 关键场景）

### 8.1 创建约骑

```
小程序点 FAB ➕ → 创建 sheet
  ↓
GET /api/segments (路线下拉数据)
GET /api/route-books?mine=1 (我的路书)
GET /api/activities?for_route_book=1 (我可衍生的活动)
  ↓
用户填字段 / 选媒体 → 上传媒体 POST /api/meetups/{id}/media
  ↓
保存草稿 POST /api/meetups (status=DRAFT)
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
check status='OPEN' / now()+30min < start_time / count < max / 用户未加入
INSERT meetup_participants
COMMIT
  ↓
返回 200 + 更新后 participants 列表
前端：按钮变"已加入 ✓" + 卡片右下角 count+1
```

### 8.3 取消约骑

```
发起人 → 详情 → 点取消
  ↓
POST /api/meetups/{id}/cancel
  ↓ (后端)
BEGIN
SELECT meetups WHERE id=? FOR UPDATE + populate_existing
check creator_id == current_user / status='OPEN' / now()+30min < start_time
UPDATE status='CANCELLED', cancelled_at=now()
COMMIT
  ↓
返回 200
v1 不发主动通知（用户自己刷新看到灰态）
```

---

## 9. 风险表（故障 5 维 / architect 信条 2）

| # | 维度 | 风险 | 严重度 | 对策 |
|---|---|---|---|---|
| 1 | 崩溃 | 加入后 worker 崩 / 用户没收到 200 | 中 | UNIQUE 约束 + 用户 retry 自然幂等 / 前端按钮防抖 |
| 2 | 崩溃 | cron 跑 COMPLETED 时崩 | 低 | 下一个 5 min cron 接着扫 / 状态机自然恢复 |
| 3 | 并发 | 满员抢位 | 高 | FOR UPDATE + populate_existing（§6.1）|
| 4 | 并发 | cancel race（cancel 同时有人 join）| 高 | 同 FOR UPDATE 互斥（cancel 也锁 meetup row）|
| 5 | 批量 | 用户 200 个约骑 / 单查询超慢 | 低 | (status, start_time) 索引 + 分页 |
| 6 | 边界 | 截止时间 ±30s 边界 | 中 | server-side 严格判 + 30 秒缓冲（Tim 拍）|
| 7 | 边界 | max_participants=2 / 发起即满员 | 低 | CHECK(≥2) / 发起人 +1 时自动 / 加入逻辑统一 |
| 8 | 边界 | 路书跨城市（路书 city=taiyuan / meetup 创建者在 chengdu）| 低 | 不限制 / 路书 city 仅元数据 / meeting_point 字符串自由 |
| 9 | 级联 | 用户删账号 | 高 | §6.2 三类策略 |
| 10 | 级联 | segment 被 admin 删 / 关联约骑 | 低 | SET NULL（约骑保留 / 显示"路线已删")|
| 11 | 级联 | route_book 被 creator 删 / 关联约骑 | 低 | SET NULL |

---

## 10. 测试策略

按 CLAUDE.md 原则 3 TDD 红→绿：
- **单元测试**（service 层）：状态机转换 / 并发 FOR UPDATE / 时间边界 / 级联策略 / 路书衍生算法
- **API 测试**（router 层）：每个 endpoint happy + 4 类错误码 / 权限检查 / 微信合规约束（评论字段不存在）
- **集成测试**：创建→加入→取消 全链路 / 用户删账号级联 / cron 自动 COMPLETED
- **避坑测试**：truthiness（CLAUDE.md 陷阱 #1）/ tz-aware（陷阱 #2）/ SAVEPOINT（陷阱 #13）/ SQLite vs PG dialect 守卫（陷阱 #15 — 路书 PostGIS 必须 PG 守卫）

**真用回归**（CLAUDE.md feedback_real_usage_vs_mock_blindspot 硬规则）：部署到生产 dev stack 后 Tim 手动跑一遍 happy path + 满员场景。

---

## 11. 任务拆解预估 🔵

| Task | 范围 | 工程量 |
|---|---|---|
| Task 1 | 数据模型 + Alembic 迁移（4 表）| 1 天 |
| Task 2 | 路书 service + API（创建 / 列表 / 详情 / 删除 + GPX 解析 + 活动衍生）| 2 天 |
| Task 3 | 约骑 service（CRUD + 状态机 + 时间边界）| 2 天 |
| Task 4 | 约骑 API（11 个 endpoint）| 1.5 天 |
| Task 5 | 加入 / 退出（FOR UPDATE + 并发测试）| 1 天 |
| Task 6 | 媒体上传（复用 app/storage）| 1 天 |
| Task 7 | cron auto-complete + 用户删账号级联 | 0.5 天 |
| Task 8 | segment router 扩展（upcoming-meetups）| 0.5 天 |
| Task 9 | 小程序前端 3 页（list / detail / create sheet）| 3 天 |
| Task 10 | 真用回归 + hotfix | 1 天 |

**总计**：~13.5 天 / 跨 3 个 sprint

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
| 7 | 跨城市约骑筛选 | 路书 city 仅元数据 / 不限制约骑跨城 |
| 8 | 修改已发布约骑 | OPEN 不可改 / 想改只能 cancel 重发 |

---

## 13. 验收清单（给 Tim · 8 条 yes/no）

Tim 逐条确认。任一 "不对" → 改 doc 再 review。

- [ ] **1**. 范围：v1 做 ① + ② + ③ + ⑤ + ⑦（约骑活动 + 路线下拉 + 路书 + 路线详情入口 + 媒体），④/⑥ 留 v6/v2，对吗？
- [ ] **2**. 路书定义：路书 = 用户自建图纸 / segment = 管理员精选排名单元 / 两者独立 / 路书不参与 KOM 排行，对吗？
- [ ] **3**. 路书 3 种创建方式：上传 GPX / 从我已骑活动衍生 / 选 segment 当路书（路书不复制 segment 仅引用） — 你拍 y/n
- [ ] **4**. 状态机：DRAFT → OPEN → (CANCELLED \| COMPLETED) / 出发前 30 min 截止报名+退出+取消 / 出发后所有操作锁死，对吗？
- [ ] **5**. 微信合规：v1 砍所有用户间直接互动（评论 / 私信 / 打招呼按钮 / 跳转私聊 / 关注），允许单向看见列表，对吗？
- [ ] **6**. 满员抢位：物理上不可能超员 / 满员后有人退出再开放报名（不是先到先得，是从那一刻起再点的人能加），对吗？
- [ ] **7**. 用户删账号：他发起的约骑 auto cancel / 他参与的约骑名额自动空出别人可补位 / 他创建的路书保留供他人复用，对吗？
- [ ] **8**. 工程量 ~13.5 天 / 跨 3 sprint 你能接受吗？还是想砍哪个 task 进一步压缩到 1-2 sprint？
- [ ] **9**. ⚠ 新发现待拍：路书默认**公开**（任何骑友都能在约骑创建表里看到 + 选你创建的路书）还是默认**私密**（只创建者自己能选）？默认公开 = 路书复利更强但创建者可能不愿暴露"我探的私路"/ 默认私密 = 安全但路书生态起不来。我推荐默认公开 + 后续 v2 给用户加一个"设为私密路书"的开关。你拍 y/n / 或者 v1 就直接两选项都给（多 0.5 天工程量）。

---

## 14. 链接索引

- 用户故事 HTML（visual companion）：`.superpowers/brainstorm/56665-1779953873/content/user-story.html`
- 微信合规 memory：[[feedback_wechat_miniprogram_no_direct_social]]
- 并发处理 memory：[[feedback_savepoint_isolation_for_inner_modules]]
- 战略 PRD：`docs/prd/velo-vision.md:355` / `docs/prd/velo-strategy.md:38-40` / `docs/prd/velo-product-spec.md:47`
- 现有代码事实：`app/segment/models.py:55-103` / `app/user/models.py:37-51`
