# velo Sprint 6 战术 PRD —— "我的"页基础落地

> **本文件性质**：Sprint 6 战术 PRD，给执行 spec subagent 看的执行手册。
>
> **写作规范**（沿用 phase-5-prd.md / Tim 2026-04-28 拍）：每子任务严格 **9 章节**（用户目标 / 使用场景 / 功能范围 / 用户流程 / 页面&状态 / 数据需求 / 异常情况 / 验收标准 / 不做项）+ 来源追溯一行。
> - PRD 不写具体数据库表结构 / API 路径（放 plans/task 卡）
> - PRD 可写必要技术约束（小程序 / 后端约束 / 性能要求）
> - UI/UX 只写页面结构 / 信息优先级 / 流程 / 状态，**不写视觉参数**
>
> **维护**：Tim + Claude 协作。版本 **v0.3**（2026-05-16 / 第二轮双审收尾 / 修 5 处新引入 Critical：NULL 语义对齐 / unbind strava_imports 暂停 / D-P08 diff 脚本 / cities.py 归属 + 单一真相源 / 加 FTP 脏数据下界）。

---

## 0. Sprint 6 north star

**1 主轴（独立 / 全做）**：

让用户在 velo 上看到"我是谁"——把 `pages/profile` 从"字段表格"升级为"骑手身份名片"。用户每天打开"我的"页都能看见自己的成长、足迹、身份标签。

**6 个子任务**：

- **后端 task-1**：User 加签名字段（bio），让用户能一行话告诉骑友"我是谁"
- **后端 task-2**：数据徽章规则模块，把真实骑行数据自动算成 2-3 个身份徽章（FTP / 累计里程 / 山名常客）
- **后端 task-3**：城市勋章——**新增 `activities.city` 字段 + worker hook 写入 + 旧数据 backfill + 聚合 endpoint**（v0.2 改：activities 表原无 city 字段 / 路 B 落地）
- **前端 task-4**：profile 页全面改造（头像+签名+徽章 / 训练统计 / 热图+城市勋章墙 / 活动列表）
- **前端 task-5**：settings 子页（FTP 编辑 / 退出登录 / 解绑 Strava + 后端新增 unbind endpoint）
- **task-6**：真用回归（注册到查看 profile 全链路）

**1 个跨子任务软目标**：profile 页打开后端聚合 < 800ms / 前端首屏渲染 < 1s。

**预估工期**：**7-10 天**（v0.2 改：task-3 0.5 天 → 1-1.5 天 / 加迁移 + worker hook + backfill 工作量）。

**前置依赖**：无 P1 tech-debt 阻塞。P3 一条（`current_month_summary.avg_power_w` 前端不渲染）在 task-4 顺手清。

**Sprint 范围外（明确延后）**：

- **NPC 文案系统**（数字英雄化 + 拟人化祝贺 + 黑色幽默 + Persona 宪法 + LLM 触发器）→ 延后到 **Persona Engine Sprint**（独立大型 Sprint / 见 memory `project_velo_persona_engine_sprint_seed.md`）
- **关注/粉丝/单向关系/feed 流**（社交关系层 / Sprint 4 D7 已推到 v6）
- **地图叙事化详情页**（路线赛段着色 + 徽章贴地图位置 + Strava 风格 → 未来大工程）
- **装备身份认同区**（车 / 码表 / 鞋 → 未拍）
- **多行长简介**（本 Sprint 只做短签名）
- **用户手填徽章 / 自定义徽章** → **永不做**（破坏"真实数据驱动 = 不可造假"护城河）

---

## 0.1 真实代码事实表（grep 实证 / spec subagent 起手必读）

> v0.1 双审抓 5 处事实错（凭印象写）触发 v0.2 重审。本表所有 [file:line] 已亲 Read 实证。
> spec subagent 实施前必须重新 grep 验证一遍（防 stale / 见 memory `feedback_phase5_task_card_grep_stale.md`）。

### User 字段（`app/user/models.py:27-119`）

| 字段 | 真值 | 注 |
|---|---|---|
| id / openid / nickname / avatar_url | ✓ 已有 | - |
| ftp / weight / bike_type / weekly_goal | ✓ 已有 | - |
| **strava_athlete_id** | BigInteger / unique / nullable | ⚠️ 不是 strava_user_id |
| strava_access_token / strava_refresh_token / strava_token_expires_at | ✓ 已有 | - |
| mute_notifications / is_admin | ✓ 已有 | - |
| city | String(32) / NULL OR 6 城+unknown | `ck_users_city` CHECK |
| created_at / updated_at | tz-aware UTC | - |

**city CHECK 约束** [`app/user/models.py:115-118`]：`NULL OR ('beijing','shanghai','hangzhou','shenzhen','chengdu','taiyuan','unknown')`

### Activity 字段（`app/activity/models.py:42-164`）

| 字段 | 真值 | 注 |
|---|---|---|
| **distance** | Float / 米 | ⚠️ 不是 distance_m |
| **elevation_gain** | Float / 米 | ⚠️ 不是 elevation_gain_m |
| duration / moving_time | Integer / 秒 | - |
| avg_speed / max_speed / avg_power / max_power / avg_hr / max_hr / avg_cadence / calories / normalized_power | Float | - |
| started_at / finished_at / created_at / updated_at | tz-aware UTC | - |
| activity_type | "cycling" default | - |
| duplicate_of | dedupe FK (set null) | - |
| simplified_track / splits / power_zones | JSONB | - |
| **没有 city 字段** | - | ⚠️ task-3 路 B 必须新加 |

### Router 前缀（`app/user/router.py:23` / `app/strava/router.py:40`）

- **`/api/user`** 单数（Tim 2026-04-30 拍 A / 注释 L116-117 实证）
- `/api/strava`

**已有 user endpoint**：
- POST /api/user/login
- GET /api/user/profile（self / 含 ftp/weight）
- PUT /api/user/profile（body 接受 nickname/avatar_url/ftp/weight/bike_type/weekly_goal / **不含 city**）
- GET /api/user/stats
- GET /api/user/active
- GET /api/user/me/power-curve
- GET /api/user/me/heatmap
- PATCH /api/user/me（body **目前只 city** / 未来扩 settings 类）
- GET /api/user/{user_id}/profile（others / 严格白名单）
- GET /api/user/{user_id}/power-curve
- GET /api/user/{user_id}/heatmap

**已有 strava endpoint**：authorize / callback / **status**（已有 / 看 bound 状态）/ webhook / sync / import-progress。**没有 unbind endpoint** → task-5 必须新增。

### 看他人白名单 `_PROFILE_RESPONSE_KEYS`（`app/user/service_social.py:71-75`）

真值 **9 字段**：
```
{"id", "nickname", "avatar_url", "city", "bike_type",
 "total_distance_km", "total_elevation_m", "activity_count",
 "current_month_summary"}
```

**严格不返**：ftp / weight / strava_* / openid / mute_notifications / token / efforts / activities / heatmap。

**D-P08 真值**（v0.1 误解纠正）：
- self profile (`UserProfile`) 含 ftp / weight / weekly_goal / created_at
- others profile (`UserProfileResponse`) **故意不返** ftp / weight 等敏感字段（Sprint 4 codex P1-4 砍）
- D-P08 = "看自己 vs 看他人不区分隐私开关 / 但**字段集本身故意不对称**"
- **Sprint 6 适用版**：本次**新增**字段（bio / badges / city-medals）必须自他对称；**既有**字段集差异保留不动

### Schemas 关键 model（`app/user/schemas.py`）

- `UserProfile`（self / GET /profile / L46-56）：含 ftp / weight / weekly_goal / created_at
- `UserProfileUpdate`（PUT /profile body / L62-77）：nickname / avatar_url / ftp / weight / bike_type / weekly_goal （**不含 city**）
- `UserPatchRequest`（PATCH /me body / L171-182）：**目前只 city**
- `UserProfileResponse`（others / L192-212）：9 字段（同白名单）
- `UserCity` enum（L132-140）：6 城 + unknown

### 最新 Alembic 迁移头（`migrations/versions/sprint5_activity_privacy.py:12-13`）

- 当前 head = `sprint5_activity_privacy`
- → sprint6 新迁移的 `down_revision` 都应写 `sprint5_activity_privacy`

### geo.py 6 城（`app/common/geo.py:29-36`）

`_CITY_BOUNDS` 6 城 box：beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan
+ `infer_city_from_coords(lat, lon) -> str`：返 6 城之一 或 `'unknown'`

**v5 期 worker 已用此函数写 `user.city`**（用户主城）/ 本 Sprint 改造让 worker 同时写 `activity.city`（活动起点城市）。

---

## 1. 共用规范引用（spec subagent 必读）

### 1.1 语言风格

参 `docs/agent-rules/product-decisions.md` § 7 禁用词清单。

**Sprint 6 特殊**：**本 Sprint 不写任何 NPC 拟人化文案 / 数字祝贺语 / 黑色幽默**。所有面向用户的文字保持 v5 期现有调性（"累计骑行 / 本周里程 / FTP" 等纯陈述式）。NPC 文案延后到 Persona Engine Sprint 统一改造。

理由：本 Sprint 是基础设施 Sprint / NPC 文案需配套 Persona 宪法 + 双标尺 + 反例库系统化输出 / 散在本 Sprint 做必导致 NPC 调性提前漂移。

### 1.2 技术栈

参 `CLAUDE.md` "技术栈"章节（FastAPI 同步 / SQLAlchemy 2.0 / PostgreSQL + PostGIS / 微信小程序 / 禁止 async def）。

### 1.3 边界（INV / D-P）

参 `docs/agent-rules/product-decisions.md` § 1（INV-P01 ~ P06）+ § 5（D-P01 ~ D-P10）。任何 spec 决策违反 → REJECT escalate Tim。

**Sprint 6 强相关边界**：

- **D-P08（v0.2 重述精确版）**：D-P08 是"看自己 vs 看他人**不区分隐私开关**"（路径层 / 任意登录用户都能看他人 profile）。**字段集本身故意不对称**（others 不返 ftp / weight / token / openid 等敏感字段）。
  - **Sprint 6 落地**：本次**新增字段**（bio / badges / city-medals）必须自他对称——self 和 others 都能看到。**既有字段集差异**（ftp / weight 只在 self / 不在 others）**保留不动**。
- **D7 决策**（Sprint 4）：profile 默认公开 / 无隐私开关 / requester_user_id 留 v6 隐私开关预留位 → Sprint 6 沿用 / **不加新隐私字段**。

### 1.4 规则界限

- **防火墙式扩展（v0.2 改 / 破例 2 处）**：
  - 修 `users` 表加 bio 字段（task-1）
  - 修 `activities` 表加 city 字段（task-3）
  理由：bio 是 profile 一级字段 / city 是活动起点元数据 / 都属于"加房间"级新字段 / 不影响既有列。Tim 拍。
- **数据徽章规则**：放新模块 `app/user/badges.py` 纯函数 / 不动 ORM
- **强制检查清单 + 技术栈陷阱清单**：CLAUDE.md
- **部署纪律**：CLAUDE.md "部署经验"

---

## 2. task 概览

| # | task | 模块 | 估时 | 依赖 |
|---|---|---|---|---|
| 1 | User.bio 字段 + 迁移 + schema 更新 | 后端 user | 0.5 天 | - |
| 2 | 数据徽章规则模块（badges.py 纯函数）+ profile 集成 | 后端 user | 1 天 | task-1 |
| 3 | **activities.city 字段 + worker hook + backfill + 城市勋章 endpoint** | 后端 activity + user | **1-1.5 天** | **弱依赖 task-2 cities.py** |
| 4 | profile 页改造（头像+签名+徽章 / 三模块布局 / 顺手清 P3）| 前端 miniprogram | 2-3 天 | task-1 / task-2 / task-3 |
| 5 | settings 子页 + 后端 unbind endpoint | 前端 miniprogram + 后端 strava | 1-2 天 | - |
| 6 | 真用回归（注册到查看 profile 全链路）| 双方 | 1 天 | task-1 ~ task-5 |

**串并顺序**：task-1 / task-5 无依赖可并行起草；task-2 等 task-1；**task-3 弱依赖 task-2 cities.py 文件先 merge**（v0.4 修 / 否则 task-3 单跑 ImportError）；task-4 等 task-1/2/3 全完；task-6 等全部。

**部署顺序**：Alembic 链强制串行 / sprint5_activity_privacy → sprint6_user_bio (task-1) → sprint6_activity_city (task-3) / 部署 `alembic upgrade head` 自动按链跑。

**合计 7-10 天**（单人估算 / 三人协作可压到 4-5 天）。

---

## 3. task 详情

### 3.1 task-1 - 后端 - User.bio 字段 + 迁移 + schema 更新

**用户目标**：让用户能在 profile 页编辑一行短签名，5 秒告诉骑友"我是谁"。

**使用场景**：小明骑完车打开"我的"页 / 头像下方除了昵称 + 城市 / 还能写一行短签名"成都老登 / 公路党 / FTP 220W"。点编辑改完保存。陌生骑友点他头像进 user 页 / 第一眼看到这行字 / 5 秒判断"这是个 220W 的成都本地老炮"。

**功能范围**：
- User 表加 bio 字段（短签名 / 公开字段 / 可选）
- profile 相关 schemas 更新（`UserProfile` self + `UserProfileResponse` others 都加 bio）
- request body schemas（`UserProfileUpdate` PUT /profile + `UserPatchRequest` PATCH /me）都加 bio
- 看他人白名单 `_PROFILE_RESPONSE_KEYS` 加 bio（自他对称 / 新字段强制一致）
- 长度上限：≤ 30 字符（按 Unicode codepoint）
- 默认 NULL / 旧用户不强制填

**用户流程**：
1. 用户开 profile 页 → 后端返 bio（可能 NULL）
2. 点编辑按钮 → 弹输入框 → 输 ≤ 30 字
3. 保存 → 后端校验长度 + 单行 → 写 DB
4. profile 页刷新 → 显示新签名

**页面&状态**：本 task 不涉及前端 UI（见 task-4）。后端只需保证：
- bio = NULL → API 返 null（前端 wx:if 不渲染整块）
- bio = "" 等价 NULL（避免空字符串污染）

**数据需求**：
- 字段类型：`String(60)` / nullable / default NULL（60 字节容量留足 30 中文 utf-8mb4 冗余）
- Pydantic validator：`max_length=30`（按 Unicode codepoint）+ `field_validator` 拒收换行 / 控制字符
- **两个 request schema 都要挂同一 field_validator**（防一边漏护 / Codex 抓的）：
  - `UserProfileUpdate.bio`（PUT /profile）
  - `UserPatchRequest.bio`（PATCH /me）
- 不涉及其他表 / 不涉及索引

**异常情况**：
- 长度超 30 → 422 + "签名不能超过 30 个字符"
- bio 含换行 / 控制字符（\n \r \t \x00）→ 422 拒收（强制单行）
- 兼容旧用户 bio = NULL → GET 不报错 / PATCH 不强制
- Alembic 迁移在 PostgreSQL + SQLite 都跑通

**验收标准**：
- pytest：PATCH /me 入 bio = "成都老登" → 200 + DB 写入 + GET /profile 返 bio
- pytest：PUT /profile 入 bio = "..." → 同上效果
- pytest：PATCH 入 31 字 bio → 422
- pytest：PATCH 入 bio = "line1\nline2" → 422（PUT 同测）
- pytest：PATCH 入 bio = "" → DB 写 NULL → GET 返 null
- pytest：GET /api/user/{user_id}/profile（看他人）→ 返 bio
- Alembic upgrade head + downgrade -1 在 PG + SQLite 都跑通
- 不破坏既有 profile 相关 pytest（≥ 既有 case 数）

**不做项**：
- 多行长简介（≥ 30 字 / Markdown / 多行）→ 永不做（短签名定位）
- @ 用户 / 表情图标渲染规则 → 不做（前端原样显示）
- 敏感词过滤 → 暂不做（100 用户量级）
- bio 历史版本 / 编辑日志 → 不做

**来源追溯**：本对话 2026-05-15 brainstorm / Tim 拍签名 = 一行短签名 ≤ 30 字 / 公开字段 / 新字段自他对称。

---

### 3.2 task-2 - 后端 - 数据徽章规则模块

**用户目标**：用户头像旁自动挂 2-3 个**真实骑行数据徽章**，让骑友 0.5 秒识别身份。徽章无法手填 / 反"打肿脸"= 骑行社区独有的高信任护城河。

**使用场景**：小明在赛段榜看到"老王"排第 2 / 点头像进 user 页 / 头像旁挂着 🏔️ FTP 240W / 📏 累计 8500km / 🏆 雀儿山常客 三个徽章。决策"约骑 / 关注"瞬间完成。

**功能范围**：
- 新建模块 `app/user/badges.py` 纯函数 / 不碰 DB（按 CLAUDE.md "纯函数规则"）
- 输入：user_id + 已聚合的用户数据 dict（FTP / 累计 distance / 累计 elevation_gain / 用户骑过的赛段 + 频次 / city）
- 输出：徽章列表（每个徽章含 `type` / `label`）
- profile endpoint（GET /profile + GET /{user_id}/profile）返回字段加 `badges`（最多 3 个 / 按优先级排序）
- 看他人白名单 `_PROFILE_RESPONSE_KEYS` **追加** badges（用 `|= {"badges"}` 不要整体覆写既有 9 字段）
- 数据聚合由 service 层完成 / 调 badges.py 算

**徽章规则（v0.2 / 5 种 / 按优先级降序）**：

| 徽章 | 触发条件 | label 示例 |
|---|---|---|
| FTP 徽章 | `user.ftp is not None and user.ftp >= 50`（v0.3 加脏数据下界 / 与 PUT /profile 范围 50-500 一致 / 防历史脏数据 ftp=10 等渲染怪 label）| "FTP 220W" |
| 累计里程徽章 | 累计 `Activity.distance` 阶梯：1000 / 3000 / 5000 / 8000 / 10000+ km | "累计 8500km" |
| 累计爬升徽章 | 累计 `Activity.elevation_gain` 阶梯：5000 / 10000 / 30000 / 50000 / 100000+ m | "爬升 50000m" |
| 山名常客徽章 | 同一 segment_id 骑过 ≥ 5 次 / 取频次最高一条 | "雀儿山常客" |
| 城市本地徽章 | `user.city is not None and city in 6城枚举` | "成都骑友" |

**优先级**：FTP > 山名常客 > 累计里程 > 累计爬升 > 城市本地（top 3 上展示）。

**用户流程**：
1. 用户 / 别人开 profile 页 → 后端聚合徽章数据 → 调 badges.py 算 → 返 ≤ 3 个徽章
2. 前端原样展示（task-4 负责 icon / 排版）

**页面&状态**：本 task 不涉及前端 UI。后端保证：
- badges 字段永不为 null / 至少返空数组 []
- 字段顺序固定（按优先级）

**数据需求**：
- 聚合源：users 表（ftp / city）+ activities 表（distance / elevation_gain / status='completed' / duplicate_of IS NULL）+ segment_efforts 频次
- 不加新字段 / 不加新表（city-medals 加字段在 task-3）
- 计算性能：单次聚合 < 200ms（top-N 简单 SQL / 不引入 N+1）

**异常情况**：
- 用户无任何活动 → 返 []
- ftp = NULL → 跳过 FTP 徽章 / 不报错
- city = NULL / 'unknown' → 跳过城市本地徽章
- 阶梯计算遇负数 / NaN → 防御性归 0 / 不抛异常
- 山名常客频次并列 → 取 segment_id 最小一条（稳定排序）

**验收标准**：
- pytest 纯函数：badges.py 给定 dict 输入 → 返预期徽章数组（覆盖 5 种规则 + 边界）
- pytest 集成：用户骑过雀儿山 6 次 → GET /profile.badges 含 "雀儿山常客"
- pytest 集成：用户 ftp = NULL → badges 不含 FTP 徽章
- pytest 性能：100 条 activities 用户聚合 + 算 badges < 200ms
- 自他对称：GET /api/user/profile.badges 与 GET /api/user/{user_id}/profile.badges 字段集 + 排序完全一致
- 白名单回归：`_PROFILE_RESPONSE_KEYS` 追加 badges 后 / 既有 9 字段仍透出（不允许覆写丢字段）

**不做项**：
- 徽章动画 / 视觉特效 → 不做（前端简洁）
- **用户手填徽章 / 自定义徽章** → **永不做**（破坏护城河）
- 历史徽章解锁日期 / 通知 → 不做
- W/kg 徽章（weight 字段 NULL 多）→ 不做
- 速度俱乐部徽章 → 不做（噪声大）

**来源追溯**：本对话 2026-05-15 brainstorm 创新 1 / Tim 拍。

---

### 3.3 task-3 - 后端 - activities.city 字段 + worker hook + 城市勋章 endpoint（v0.2 路 B 重写）

**用户目标**：用户看自己已经在多少城市骑过车。把"我去过哪儿"从静态展示升级成"游戏化驱动"——骑游党看到 3/6 会想下次出差去解锁第 4 城。

**使用场景**：小明打开"我的"页 → 看到热图 → 旁边一块"城市勋章墙" → 显示 6 城每城一格 → 已骑过的 3 城点亮（北京/上海/杭州）/ 其余 3 城灰色（深圳/成都/太原）→ 标题"城市征服：3/6"。下次小明去成都骑一次 → 第 4 格点亮。

**功能范围**（v0.2 修：原 PRD 假设 activities.city 存在 / 真相是不存在 / 走路 B）：

1. **加 `activities.city` 字段 + Alembic 迁移**：
   - 类型 String(32) / nullable / CHECK 约束 7 枚举（与 users.city 一致：6 城 + unknown）
   - 加索引 `idx_activities_user_city`（user_id + city / partial WHERE status='completed' AND city IS NOT NULL）

2. **worker hook 写入路径**：所有 activity 上传完成解析时（GPX / FIT / Strava）调 `infer_city_from_coords` 传 `simplified_track` 起点经纬度 / 写 `activity.city`。

3. **旧活动 backfill**：写一次性脚本 `scripts/backfill_activity_city.py`：
   - 遍历所有 `simplified_track is not None` 的 activity
   - 取轨迹起点 [lon, lat] / 调 `infer_city_from_coords`
   - UPDATE `activity.city`（限速节流 / 防 DB 风暴）

4. **城市勋章 endpoint**：新增 GET /api/user/me/city-medals + GET /api/user/{user_id}/city-medals
   - 返：unlocked（已点亮城市 list）+ unlocked_count + total（=6）+ medals（全 6 城 + label / unlocked flag）
   - 聚合规则：`activity.city IN 6城 AND duplicate_of IS NULL AND status='completed'` GROUP BY city
   - 自他对称（新字段强制一致）

**6 城枚举来源**（与 users.city CHECK 约束 + geo.py `_CITY_BOUNDS` 完全对齐）：
`beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan`
+ `unknown` 兜底（不计入解锁集合 / 仅用于 worker 写入兜底）

**用户流程**：
1. 用户 / 别人开 profile 页 → 前端调 GET /city-medals
2. 后端 GROUP BY activity.city → 排除 NULL / 排除 'unknown' / 取 6 城交集 → 输出已解锁集
3. 前端展示勋章墙（已点亮 / 灰色 / 进度数字）

**页面&状态**：本 task 不涉及前端 UI。后端保证：
- 用户无任何活动 → unlocked = [] / unlocked_count = 0 / total = 6
- 全 6 城均有活动 → unlocked_count = 6

**数据需求**：
- 新字段：`activities.city`（与 users.city 类型 / CHECK 完全一致）
- 共享枚举常量：抽 `app/user/cities.py` 或同位 / badges.py 和 service_social.py 共用（v0.2 修 / Important #2 双真相源）
- 聚合 SQL：单条 GROUP BY / 1000 条 activities 用户 < 100ms

**异常情况**：
- 用户活动 city 全 NULL → unlocked = []
- 用户活动 city = 'unknown' → 不计入（unknown 不是真城市）
- 看不存在用户 → 404
- 旧活动 simplified_track = NULL → backfill 时跳过 / city 保持 NULL
- worker hook 写入失败 → 不阻断 activity 创建（city 留 NULL / 后续 backfill 兜底）

**验收标准**：
- pytest：用户骑过 beijing + shanghai → unlocked = ['beijing', 'shanghai'] / count = 2
- pytest：用户无活动 → unlocked = [] / count = 0 / total = 6
- pytest：用户活动 city = 'unknown' → 不计入
- pytest：activity.city CHECK 约束拒收 'nanjing' 等 7 城外值
- pytest：worker hook 写入 city（GPX/FIT/Strava 三路径都测）
- pytest：自他对称（GET /me/city-medals === GET /{user_id}/city-medals）
- 性能：1000 条 activities 用户聚合 < 100ms
- backfill 脚本干跑 + 真跑（生产 100 用户量级 / 限速 5 条/秒）

**不做项**：
- 城市勋章动画 / 解锁特效 → 不做
- "首次解锁城市"通知 push → 不做
- 用户自定义城市 / 海外城市 → 永不做（unknown 兜底即可）
- 解锁日期 / 解锁顺序 → 不做（本 Sprint 只关心解锁集合）
- 按城市筛 feed / 按城市排行榜 → 未来 Sprint（city 字段加上是基础设施 / 服务多个未来功能）

**来源追溯**：本对话 2026-05-15 brainstorm 创新 3 / Tim 2026-05-16 拍路 B（保留功能 + 加字段）。

---

### 3.4 task-4 - 前端 - profile 页改造

**用户目标**：让用户打开"我的"页第一屏就能感受到自己的骑手身份——头像 + 一行签名 + 自动徽章 + 训练统计 + 骑行足迹 + 历史活动。**视觉密度有冲击 + 数字 hero 化**（但不加 NPC 拟人化文案）。

**使用场景**：小明每天打开 velo "我的"页 → 第一眼看到自己头像 + "成都老登 / 公路党 / FTP 220W" 签名 + 三个徽章 → 往下滑看到本周 / 累计训练统计（大数字 + 留白 + 2 列网格）→ 再往下是热图 + 城市勋章墙（3/6 已解锁）→ 最下方历史活动列表（首页同款大卡片 / 可点开详情）。

**功能范围**（按页面从上到下）：

1. **头像区**：头像 + 昵称 + 城市标签（沿用 v5 D9 fallback）+ **新增 bio 短签名**（NULL 整块隐藏）+ **新增徽章行**（top 3 横排 / 空时整行隐藏）

2. **C 训练统计模块**：本周 / 累计里程 / 爬升 / FTP 等（已有）/ **改造方向：数字 hero 化（大字号 + 灰小标签 + 2 列网格 + 留白）**/ 顺手清 P3：`current_month_summary.avg_power_w` 渲染

3. **B 热图 + 城市勋章墙**：热图（已有 GET /me/heatmap）+ **新增城市勋章墙**（紧邻热图 / 6 格勋章 / 已解锁/灰色 / 标题"城市征服：3/6"）

4. **A 活动列表**：复用首页同款大卡片组件 / 拉 GET /api/activities（已有）/ 分页加载 / 卡片点击进 detail 页

5. **编辑入口**：头像 / 昵称 / bio 点击 → PATCH /me（PATCH 仅接受 bio + city / 改 nickname / avatar_url / ftp 走 PUT /profile）+ 头部右上角"设置"icon 进 settings 子页

**用户流程**：
1. tab "我的" → onShow → 并发拉接口：
   - GET /api/user/profile（self / 含新 bio + badges）
   - GET /api/user/stats?period=week
   - GET /api/user/me/heatmap
   - GET /api/user/me/city-medals（task-3 新增）
   - GET /api/activities?page=1（独立分页 / 不阻塞）
2. 头像区先渲染（profile 数据最快回）
3. 各模块按数据回包陆续渲染
4. 用户改 bio → PATCH /me / 改 nickname/avatar_url → PUT /profile → setData → 视觉刷新

**页面&状态**：
- **未登录**：显示登录按钮（沿用现状）
- **数据全有**：完整四模块
- **bio = NULL**：bio 整块隐藏 + 可点"添加签名"占位
- **徽章 = []**：徽章行整行隐藏
- **无活动**：A 列表空状态 / 城市勋章墙 0/6 全灰 / 热图空
- **API 失败**：每模块独立 fallback

**数据需求**：
- 后端字段已有：nickname / avatar_url / city / ftp / stats / heatmap
- 后端字段新增（本 Sprint）：bio (task-1) / badges (task-2) / city-medals (task-3)
- endpoint 前缀全部 `/api/user`（单数）+ `/api/activities`

**异常情况**：
- bio 含 emoji → 前端按字符串展示（后端不过滤）
- 徽章 < 3 → 布局自然收缩 / 不留空格
- 城市勋章 unlocked = [] → 勋章墙全灰 / 不报错
- 任何模块接口 404 / 失败 → 整块隐藏 / 不破坏其他
- "-" 占位符规则（按 memory `feedback_no_dash_placeholder.md`）：字段缺失整块隐藏 / 禁止显示 "-"

**验收标准**：
- 真机测试：打开"我的"页 / 4 模块全部正确渲染
- bio 编辑：输入 / 保存 / 刷新可见
- 徽章自动从后端拉 / 按优先级排序展示
- 城市勋章墙：解锁城市点亮 / 未解锁灰色 / 进度数字"3 / 6"正确
- 活动列表与首页样式一致（复用同一卡片组件）
- P3 清掉：current_month_summary.avg_power_w 渲染（tech-debt 一条）
- 新字段自他对称：在 user 页看别人 profile 也能看到对方 bio / badges / city-medals
- 性能：profile 页首屏渲染 < 1s

**不做项**：
- NPC 拟人化文案（"恭喜你" / "今天嗑药了？" / 数字祝贺）→ 延后 Persona Engine Sprint
- 数字英雄化对比文案（"等于绕地球 1/5 圈"）→ 同上
- 路线赛段着色 / 徽章贴地图 → 未来"地图叙事化"
- 装备身份认同区 → 未拍
- 长简介 / Markdown → 永不做
- 隐私开关 → 隐私 Sprint
- 关注/粉丝/点赞 → 社交 Sprint

**来源追溯**：本对话 2026-05-15 brainstorm / Tim 拍三模块布局 + 数字 hero 化 + 复用首页大卡片 + 不写 NPC 文案。

---

### 3.5 task-5 - 前端 settings 子页 + 后端 unbind endpoint

**用户目标**：让用户在一个集中位置完成 FTP 编辑 / 退出登录 / 解绑 Strava——这些每天不点 / 但出问题时一定要能点到。

**使用场景**：小明做完正式 FTP 测试测出 235W → 进 settings → 改 FTP → 保存。或想换 Strava 账号 → 解绑 → 重新绑定。或借手机给颜颜 → 退出登录。

**功能范围**：

- 改造现有 `pages/settings`（v5 期空架子 / 38 行 js + 16 行 wxml）
- 三个区块：
  1. **账号资料**：FTP 编辑（数字输入 / 50-500 范围 / 走 PUT /api/user/profile）
  2. **第三方绑定**：Strava 解绑（**后端新增 POST /api/strava/unbind endpoint** / 前端走二次确认）
  3. **登录态**：退出登录（清 token / 切回未登录态）
- 入口：profile 页右上角"设置"icon
- 看 Strava 绑定状态：复用已有 GET /api/strava/status（返 bound 字段）

**用户流程**：
1. profile 页点设置 icon → 进 settings
2. 看三区块（账号资料 / 第三方绑定 / 登录态）
3. 改 FTP → 数字输入 → 保存 → 后端 PUT /profile / 范围校验
4. 解绑 Strava → 二次确认 → POST /api/strava/unbind → 显示已解绑
5. 退出登录 → 二次确认 → 清 token → 跳回首页

**页面&状态**：
- 三区块从上到下排列
- 危险按钮（解绑 / 退出）高对比 + **强制二次确认**
- 退出 / 解绑成功 toast + 自动刷新

**数据需求**：
- FTP：PUT /api/user/profile（已有）/ FTP 范围 50-500（schemas L74 已实证）
- Strava 绑定状态：GET /api/strava/status（已有 / 返 bound）
- Strava 解绑：**POST /api/strava/unbind**（**后端本 task 新增**）
  - 清 `User.strava_athlete_id` / `strava_access_token` / `strava_refresh_token` / `strava_token_expires_at`（4 字段 / 实证 user/models.py:79-84）
  - 已导入 activities **不删除**（按既有 strava_imports 设计）
- 退出登录：前端清 token / `wx.removeStorageSync('token')` / `app.globalData.token = null`

**异常情况**：
- FTP 输入非数字 → 提示"请输入数字"
- FTP 超 50-500 → 提示"FTP 范围 50-500"
- 解绑后 user 表 4 字段全 NULL / strava_imports 历史记录保留 / 重新绑定时 dedupe 防重导入
- 解绑 / 退出弹窗取消 → 不执行 / 留当前页
- worker 并发场景（解绑时 worker 正用旧 token 同步）→ token 清后下次调用 401 / worker 容错跳过（已知 edge case / 不在 Sprint scope）

**验收标准**：
- 真机测试：打开 settings → 三区块正确显示
- FTP 编辑：改 220 → 保存 → 返 profile 可见
- FTP 边界：输 49 / 501 → 拒收
- POST /api/strava/unbind：DB 验证 4 个 strava_* 字段全 NULL / activities 表行数不变
- 解绑前端：弹二次确认 → 确认后 stravaBound 变 false / 页面显示"未绑定"+ 绑定按钮
- 退出登录：弹二次确认 → token 清 / 跳回 profile 显示登录按钮

**不做项**：
- 注销账号 / 删除账号 → 不做
- 隐私设置 / 通知免打扰 → 推到隐私 Sprint
- 多设备登录管理 → 不做（小程序天然单设备）
- 数据导出 / GDPR → 不做
- weight / 车辆 / 装备编辑 → 不做
- 解绑时主动撤销 Strava OAuth 授权（调 Strava API）→ 不做（仅清本地 token / Strava 端用户自行去后台撤销）

**来源追溯**：本对话 2026-05-15 brainstorm / Tim 拍 E/F 进 settings / FTP 敏感不公开主页（Sprint 4 codex P1-4）/ unbind endpoint 本 Sprint 新增。

---

### 3.6 task-6 - 真用回归

**用户目标**：保证 Sprint 6 上线后 Tim / 颜颜 / CCF 在真实小程序 + 真实账号 + 真实骑行数据下能跑完整链路。

**使用场景**：Sprint 6 task-1 ~ task-5 全部 commit + 部署到生产 → Tim 拿小程序全场景跑一遍。

**功能范围**（按 memory `feedback_real_usage_vs_mock_blindspot.md` 5 类盲区 + memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md` 5 步部署 SOP）：

1. **新用户首次注册** → wx.login → POST /api/user/login → 检查 token 拿到 / profile 默认值
2. **改昵称 / 头像 / bio / 城市 / FTP** → 各字段调对应 endpoint（PUT /profile 改 nickname/avatar_url/ftp / PATCH /me 改 bio/city）→ 刷新 profile 可见
3. **上传几次活动**（不同城市 / 不同距离 / 同山 ≥ 5 次）→ 看 stats 更新 / 徽章自动出现 / 城市勋章解锁
4. **新字段自他对称验证**（D-P08 落地版）→ Tim 看自己 profile vs 颜颜看 Tim profile → diff 检查 **新增字段**（bio / badges / city-medals）完全一致 / **既有字段差异**（ftp / weight 自有他无）符合预期
5. **解绑 Strava** → POST /api/strava/unbind → 已导入活动保留 / 重新绑定 OK
6. **退出登录** → token 清 / 重新微信登录恢复

**用户流程**：
1. Sprint 6 task-1 ~ task-5 全部 ship + Codex 三审过 + commit + 部署生产
2. **部署后必跑 5 步 SOP**：本地 git push + 远端 git pull + Redis 清缓存 + `docker compose up -d --build` + curl verify
3. Tim 拿小程序 → 6 场景全跑 → bug 清单 → 起 hotfix → 修完再跑
4. 直到 bug 列表清空

**页面&状态**：无新页面 / 全用既有。

**数据需求**：
- Tim + 颜颜 + CCF 账号互看 profile（验自他对称）
- ≥ 10 条不同活动（不同城市 / 不同山）测徽章 + 勋章 + 统计

**异常情况**（5 类盲区）：
- mock 断言绿但真路径挂
- 进程独立 import（worker / scheduler 没同步 deploy）
- SQLite vs PG（CHECK 约束 / 索引在 PG 才生效）
- 单线程 vs 容器集群（pgbouncer / Redis 缓存）
- 第三方依赖激活状态（Strava 实际可解绑吗 / unbind endpoint 真生效）

**验收标准**：
- 6 场景全跑通 / 没有 500 / 没有不渲染字段
- **D-P08 落地验证**：diff Tim 自己 GET /api/user/profile vs 颜颜 GET /api/user/{Tim_id}/profile JSON 字段：
  - **新增字段 bio / badges / city_medals 必须完全一致**
  - **既有 ftp / weight / weekly_goal / created_at 只在 self / 不在 others**（符合预期 / 不算 bug）
- 性能：profile 页打开 < 1s / 后端聚合 < 800ms
- bug 列表清空 → Sprint 6 ship

**不做项**：
- 多用户压测 / 性能瓶颈分析 → 100 用户量级不做
- 自动化 e2e 测试脚本 → 不做
- A/B 灰度发布 → 不做（团队 < 5）

**来源追溯**：CLAUDE.md 真用回归原则 / memory `feedback_real_usage_vs_mock_blindspot.md` 5 类盲区 + `feedback_deploy_must_curl_verify_not_just_docker_ps.md` 5 步 SOP。

---

## 4. 不做项汇总（Sprint 范围外 / 防 scope creep）

| 不做项 | 延后到 |
|---|---|
| NPC 拟人化文案 / 老登 NPC / 信息密度公式 | Persona Engine Sprint |
| 数字英雄化对比文案（"等于绕地球 1/5 圈"）| 同上 |
| 跨时间镜像 / 年度回顾文案 | 同上 |
| 关注/粉丝/单向关系 / feed 流 / 点赞 / 评论 | 社交关系 Sprint |
| 路线地图叙事化 / 赛段着色 / 徽章贴地图 | 地图叙事 Sprint（远期） |
| 装备身份认同区（车 / 码表 / 鞋） | 未拍 |
| 长简介 / Markdown 简介 | 永不做（短签名定位） |
| 隐私开关 / "仅自己可见" | 隐私 Sprint |
| 用户手填徽章 / 自定义徽章 | **永不做**（破坏护城河） |
| 按城市筛 feed / 按城市排行榜 | 未来 Sprint（activities.city 是基础设施） |
| 注销账号 / GDPR 合规 | 未拍（100 用户量级不优先） |
| 多设备 / A/B / 灰度 / 压测 | 100 用户量级不做 |

---

> **v0.2 修订摘要**：
> - 加 § 0.1 真实代码事实表（grep 实证 / spec subagent 起手必读 / 防再凭印象）
> - 修 § 1.3 D-P08 表述：既有字段差异保留 + 本次新增字段强制自他对称
> - 修 § 1.4 防火墙：activities 加 city 字段 = 破例 2 处
> - 修 § 3.1：field_validator 同时挂 UpdateProfile + PatchMeRequest
> - 修 § 3.2：字段名 distance / elevation_gain / 白名单 `|=` 追加
> - **§ 3.3 重写**：activities 表原无 city 字段 / 路 B 加字段 + 迁移 + worker hook + backfill / 6 城枚举（不是 7 城）/ 估时 0.5 → 1-1.5 天
> - 修 § 3.4：endpoint 前缀 /api/user 单数 / 改 bio 走 PATCH /me / 改 nickname 走 PUT /profile
> - 修 § 3.5：strava_athlete_id（不是 strava_user_id）/ unbind endpoint 后端新增
> - 修 § 3.6：D-P08 验收只对**新增**字段强制一致 / 既有字段差异符合预期
> - 总估时 6-9 天 → 7-10 天（task-3 工作量增加）

> **v0.4 修订摘要**（2026-05-16 / 第三轮双审收尾 / Critical=0 可 commit）：
> - **task-3 backfill 脚本空 track / 坐标缺失 → 保持 NULL**（与 worker hook 对齐 / 不再写 'unknown' / 第三轮唯一 Critical）
> - **task-3 Strava 导入路径 worker hook 实施时锁定具体行**（spec 加 grep 命令 + 测试 case 验证从 import_scheduler 起跑）
> - **承认维护城市真实 3 处**：geo.py + users.city CHECK + activities.city CHECK（Alembic 迁移不能 import 应用代码 / 这是工程不可避免约束）
> - **task-6 场景 3 描述层同步分两步**（profile / city-medals 独立 endpoint）
> - **PRD § 2 task-3 标注弱依赖 task-2 cities.py**（之前 stale 写"无依赖可并行"）

> **v0.3 修订摘要**（2026-05-16 / 第二轮双审收尾）：
> - **§ 3.2 FTP 徽章加脏数据下界 `>= 50`**（与 PUT /profile 范围一致 / 防 ftp=10 渲染怪 label）
> - **task-3 worker hook NULL 语义对齐**：空轨迹 / 异常时**不写值**（DB 保持 NULL）/ 只有 `infer_city_from_coords` 真返 'unknown' 时才写 'unknown' / 区分 NULL（从未推断过）vs 'unknown'（推断过但不在 6 城）
> - **task-3 partial index 加 SQLite dialect 守卫**（CLAUDE.md 陷阱 #15）
> - **task-3 worker hook 定位 worker.py（不是 service.py）+ FIT 路径测试补充 + conftest._activities_table 加 city 列提醒**
> - **task-2 cities.py 归属明确**：task-2 起手建 / task-3 弱依赖 / cities.py 从 geo.py `_CITY_BOUNDS` 派生（单一真相源 / 不重复列 6 城）
> - **task-5 unbind 同事务追加 UPDATE strava_imports active → paused**（与 `_handle_athlete_deauthorize` 行为对齐 / 防调度器空转）
> - **task-6 D-P08 diff 脚本分两步**：profile（bio/badges）+ city-medals 独立 endpoint（city_medals 不是 profile 字段）
