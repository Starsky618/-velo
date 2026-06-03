# 发起约骑新原型 → 前后端接口 / JSON schema / 架构改动设计

> **本文档是什么**：把 Codex 做的两张高保真原型（四步向导发布页 + 发布前总览确认页）背后的前后端连接设计清楚。**不重做 UI**，只设计接口、数据结构、状态机、草稿/发布/照片流程、架构改动。
>
> **上游**：`docs/superpowers/specs/2026-05-28-meetup-module-design.md`（约骑模块 v1 已 ship）/ 原型在 `exports/meetup-create-prototype-handoff/prototypes/`
>
> **scope 已和 Tim 拍定（2026-06-03）**：
> - 邀请 = 微信原生转发分享（`wx.shareAppMessage`），不做站内定向邀请，无需好友关系链
> - 可见范围 = `visibility` 列：`public`(本城可见) / `invite_only`(私圈可见，不进公开列表，凭分享链接进入)
> - 适合谁 = 入库标签数组（组织者勾选）
> - 报名门槛 = 发起人自填文案，纯展示，**后端不做任何报名筛选**
>
> **标注约定**：[已有]=后端现有代码已支持 / [前端派生]=前端算即可不入库 / [需新增]=要改后端 / [前端新增]=要改小程序 / 📊=grep 实证带 file:line
>
> **状态**：设计稿待 Tim 审阅 → 三审 → 才进 plans。**未开写代码**。

---

## 0. 一句话结论

第一张图（四步向导）后端基本够用，照着连就行；第二张图（发布前总览）新增 5 个组织者自填字段（补给点 / 适合谁标签 / 可见范围 / 报名门槛 / 安全提示）+ 1 个系统分享口令 `share_token` 要加进 `meetups` 表，再补 1 个"已加入骑友列表"接口；剩下一大半视觉元素（预计时长 / 推荐功率 / 预计均速 / 报名截止 / 地图缩略图）都是前端自己算，不动后端。**两处要补的真逻辑：① 发布时拒绝出发时间已过期的草稿（当前 publish 没这关）；② invite_only 私圈靠 `share_token` 口令防猜 id（当前是假私圈，连号 id 谁都能进）。**

---

## 1. 两张图分别是什么（用户故事先行）

**第一张图（`meetup-create-wizard-publish-clone.html`）= 四步向导的最后一步「发布」。**
陈哥走完路线、时间、照片，来到第 4 步。屏幕上是一张可逐行点改的清单：路线、出发时间、集合地点、人数（带加减）、骑行节奏、补给点、活动说明、已加的照片。底部两个按钮——"保存草稿"或"发布约骑"。他点"发布约骑"，进入第二张图。

**第二张图（`meetup-create-visual-clone.html`）= 发布前总览确认页。**
陈哥现在看到的是"别人将会看到的约骑卡片长什么样"：带地图缩略图的路线卡、这条路多远多陡多久、适合谁（一排可勾的标签）、节奏门槛（强度/推荐功率/预计均速）、他自己写的报名门槛、报名规则（人数/可见范围/截止/安全提示/集合）、已加入的骑友头像、底部"VELO 反骚扰机制"提示。他确认无误，点"确认并发布约骑"，约骑正式上线。

> **UX 顺序（Tim 2026-06-03 已确认）**：两张图是**两个先后衔接的最终屏**——向导第 4 步（图一，改 logistics）点"发布约骑" → 跳到发布前总览（图二，设 social 字段 + 真发布）。理由：图二里"适合谁/可见范围/报名门槛"这三样只在图二出现，所以它们在图二被设置；图二的"确认并发布"才是真正触发 publish 的动作。若 Tim 想要别的顺序（如图二是图一的只读预览、social 字段在别处设），状态机里这一段可平移调整，不影响接口设计。

---

## 2. 三桶分类：每个视觉元素归哪、动不动后端

### 桶 1️⃣ 后端现在就能直接喂（0 代码改动）

| 视觉元素 | 后端来源 | 实证 |
|---|---|---|
| 路线名 / 距离 / 爬升 / 城市 | `meetups.snapshot_*` 4 字段 | 📊 `app/meetup/models.py:38-41` |
| 距离单位（图显 km） | API 已 `/1000` 转 km | 📊 `app/meetup/router.py:39` |
| 出发时间 / 预计结束 | `start_time` / `estimated_end_time` | 📊 `models.py:42-43` |
| 集合地点 | `meeting_point` | 📊 `models.py:44` |
| 人数上限 / 已报名人数 | `max_participants` / `participants_count` | 📊 `schemas.py:67,69` |
| 骑行节奏 | `pace_level` | 📊 `models.py:45` |
| 活动说明 | `description` | 📊 `models.py:47` |
| 照片墙 | `meetup_media` 表 + media 接口 | 📊 `media_service.py` 全套 |
| 组织者标记 | `participants.is_creator` + 响应 `is_creator` | 📊 `schemas.py:73` |

### 桶 2️⃣ 前端自己算（0 后端改动）

| 视觉元素 | 怎么算 |
|---|---|
| **预计时长 3:45** | `estimated_end_time − start_time`，前端格式化 |
| **推荐功率 FTP 160W+** | 按 `pace_level` 查一张写死的对照表（见 §6.3） |
| **预计均速 17–22 km/h** | 同上，查 `pace_level → 速度区间` 对照表 |
| **报名截止 周五 20:00** | `start_time − 30min`（项目既有截止线 📊 `service.py:135`） |
| **反骚扰提示"VELO 反骚扰机制已开启"** | 平台固定文案，写死前端常量（安全提示已改为可编辑字段，移到桶 3） |
| **地图缩略图（红线）** | 用 `route_book.preview_points` 画（详情页/创建页现有 `buildRoutePreview`） 📊 `meetup-create.js:45` |
| **路线"已生成"状态徽标** | 选中路线即"已生成"，前端常量文案 |
| **"发布前检查"行（图一 663-670）/ "确认信息准确"** | 前端写死静态文案，箭头 v1 不接跳转 |
| **"为保障安全与体验…"门槛小字（图二 .gate-sub）** | 前端写死静态文案 |
| **"最近同行"骑友标签** | v1 **不做**（需要共同骑行历史计算），只显示"组织者"标签，详 §6.5 |

### 桶 3️⃣ 需要改后端（6 列 + 1 接口 + 几处逻辑）

| 视觉元素 | 改动 |
|---|---|
| **补给点** | `meetups` 加 `supply_point` 列（图一 logistics 字段，create 时可填） |
| **适合谁标签** | `meetups` 加 `audience_tags` 列（`sa.JSON` 数组，详 §7.4） |
| **可见范围（本城/私圈）** | `meetups` 加 `visibility` 列 + 公开列表过滤 + 私圈靠 `share_token`（详 §5） |
| **报名门槛文案** | `meetups` 加 `eligibility_note` 列（纯展示，join 不校验） |
| **安全提示** | `meetups` 加 `safety_note` 列（发起人写 / 选 velo 模板 / 改模板，纯展示） |
| **私圈分享口令** | `meetups` 加 `share_token` 列（系统 create 时生成，invite_only 凭它校验） |
| **已加入骑友列表（头像/昵称）** | 新增 `GET /api/meetups/{id}/participants` 接口 |
| **邀请骑友（继续邀请）** | `wx.shareAppMessage` 原生转发（前端）；invite_only 分享链接带 `share_token` |
| **发布拒绝过期草稿** | publish 加 `start_time` cutoff 校验（当前缺，详 §5） |

---

## 3. 页面状态机

> **人话**：从陈哥点开"发起约骑"到约骑上线，页面在 5 个状态间走；草稿在数据库里全程是 `DRAFT`，只有最后一下"确认并发布"才变 `OPEN`。

### 3.1 页面状态流转图

```
 ┌────────┐  选了路线   ┌─────────┐  填完详情(POST 创建DRAFT,拿id)  ┌────────┐
 │ route  │ ─────────→ │ details │ ──────────────────────────────→ │ media  │
 └────────┘            └─────────┘                                 └────┬───┘
   选路线(4来源)          时间/集合/人数/                              可选传图(挂id)
                         节奏/补给点/说明                                  │
                                                                          ↓
                          保存草稿(PATCH,退出向导)  ┌──────────────────┐
                              ┌──────────────────→ │ publish (图一)    │
                              │                     │ 可编辑logistics   │
                              │                     │ 保存草稿/发布约骑 │
                              │                     └────────┬─────────┘
                              │                       发布约骑(PATCH logistics)
                              │                              ↓
                              │                     ┌──────────────────┐
                              └──────保存草稿────── │ preview (图二)    │
                                                    │ 设适合谁/可见/门槛│
                                                    │ 确认并发布约骑    │
                                                    └────────┬─────────┘
                                          确认(PATCH social + POST publish)
                                                             ↓
                                          后端 DRAFT ──publish──→ OPEN → 跳详情页
```

后端 `meetups.status` 全程 `DRAFT`，最后一步 publish 才 `DRAFT→OPEN`（📊 `service.py:227`）。

### 3.2 四步向导何时做什么（关键时序）

| 时机 | 动作 | 为什么 |
|---|---|---|
| `route → details` | 仅前端切屏，**不落库** | 路线只是选中，还没必要建草稿 |
| `details → media` | **首次 POST /api/meetups 创建 DRAFT**，拿 `meetup_id` | 照片接口是 `/api/meetups/{id}/media`，必须先有 id（现有设计 📊 `meetup-create.js:355`） |
| `media` 步 | 逐张 POST/DELETE media | 照片挂在草稿 id 上 |
| `publish(图一)` 改字段 | PATCH /api/meetups/{id} | 复用同一草稿，不重复建 |
| `publish → preview` | PATCH 同步 logistics 改动 | 进总览前存一次 |
| `preview` 设 social | PATCH（适合谁/可见/门槛/安全提示） | 这 4 字段在图二设置（补给点在 details 步已填，见 §6.7 字段分配表） |
| `preview` 确认并发布 | POST /api/meetups/{id}/publish | DRAFT→OPEN + freeze snapshot + 组织者占位 |
| 任意步"保存草稿" | PATCH（无 id 则先 POST）后退出 | 草稿留在"我发起的"，下次恢复 |

### 3.3 返回 / 刷新 / 退出重进的恢复

> **人话**：陈哥孩子哭了退出去，半小时后重新点开"发起约骑"，得看到他没填完的草稿，不能从零开始。

- **返回上一步**（prevStep）：纯前端 `currentStep` 回退，表单状态留内存（现有逻辑 📊 `meetup-create.js:366`）。
- **退出重进 / 冷启动恢复**（**需补的逻辑**）：`onLoad` 调 `GET /api/meetups/my-draft`（每用户唯一草稿，partial unique 保证 📊 `models.py:56-61`）：
  - 有草稿 → 回填 `form` + `meetup_id` + 新 5 字段（补给点/标签/可见/门槛/安全提示）；调 `loadMedia()` 回显照片；用 `route_book_id` 调 `GET /api/route-books/{id}` 拉 `preview_points` 重画地图缩略图。
  - 无草稿 → `initDefaultTime()` 空白起步（现有逻辑）。
  - ⚠️ 现有 `onLoad` 只 `initDefaultTime + loadRoutes`，**没调 my-draft**（📊 `meetup-create.js:140-143`）——这是本轮要补的恢复逻辑。
- **草稿被删/不存在**：my-draft 返回 `null` → 当新建处理；PATCH/publish 一个不存在的 id → 404 → 前端提示"草稿已失效"重新开始。

---

## 4. 前后端接口表

> 按页面动作排列。**状态**列：[已有]=直接用 / [改]=要加字段或逻辑 / [新增]=全新接口 / [前端]=纯小程序。

| # | 动作 | Method / Path | 触发 | 请求字段 | 响应字段 | 错误态 | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | 进向导拉草稿 | `GET /api/meetups/my-draft` | onLoad | — | `MeetupResponse \| null` | 401 | [已有] 📊`router.py:115` |
| 2 | 拉赛段 | `GET /api/segments` | route 步 | page,page_size | 赛段列表 | — | [已有] |
| 3 | 拉我的路书 | `GET /api/route-books?mine=1` | route 步 | mine,city | 含 `preview_points` | 401 | [已有] 📊`route_book/router.py:26` |
| 4 | 拉活动候选 | `GET /api/route-books/activity-candidates` | route 步 | — | 候选列表 | 401 | [已有] |
| 5 | 从活动生成路书 | `POST /api/route-books` | 选"从骑行生成"存草稿时 | name,source=activity_derived,source_activity_id | `RouteBookResponse` | 403/404/422 | [已有] |
| 6 | 腾讯生成路书 | `POST /api/route-books/tencent-direction` | route 步 | name,from/to lat/lon | `RouteBookResponse`(含 preview_points) | 422/503 | [已有] |
| 7 | 创建草稿 | `POST /api/meetups` | details→media | `MeetupCreateRequest`(+4 新字段) | `MeetupResponse` | 409 draft_exists / 422 / 401 | **[改]** 加字段 |
| 8 | 更新草稿 | `PATCH /api/meetups/{id}` | 改 logistics / 设 social / 存草稿 | `MeetupPatchRequest`(+4 新字段) | `MeetupResponse` | 403/404/409/422 | **[改]** 加字段 |
| 9 | 拉草稿照片 | `GET /api/meetups/{id}/media` | 进 media 步 | — | `MeetupMediaItem[]` | — | [已有] |
| 10 | 传照片 | `POST /api/meetups/{id}/media` | media 步 | multipart file + caption | `MeetupMediaItem` | 403/413/415/422 | [已有] |
| 11 | 删照片 | `DELETE /api/meetups/{id}/media/{mid}` | media 步 | — | 204 | 403/404 | [已有] |
| 12 | 拉已加入骑友 | `GET /api/meetups/{id}/participants` | preview 步 / 详情页 | — | `InviteeSummary[]` | 401/404 | **[新增]** |
| 13 | 发布 | `POST /api/meetups/{id}/publish` | preview 确认 | — | `MeetupResponse` | 403/404/409/**410(过期)** | **[改]** 加过期校验 |
| 14 | 放弃草稿 | `DELETE /api/meetups/{id}` | 用户主动删 | — | 204 | 403/404/409 | [已有] |
| 15 | 公开列表 | `GET /api/meetups` | 约骑 tab | status/city/pace/date_range/page | 列表（**排除 invite_only**） | — | **[改]** visibility 过滤 |
| 16 | 邀请转发 | `wx.shareAppMessage` | "继续邀请"按钮 | path=`/pages/meetup-detail?id=X`（invite_only 追加 `&token=<share_token>`） | — | — | **[前端]** |

> **没有新增"发布前总览 preview 聚合接口"**——理由见 §7。图二的数据 = 当前草稿表单（前端内存已有）+ 接口 12（骑友列表）+ 接口 3/6 已带的 `preview_points`，前端组装即可。
>
> **invite_only 口令门禁（详 §5）**：`GET /api/meetups/{id}`、`GET /api/meetups/{id}/participants`、`POST /api/meetups/{id}/join` 三个端点对 `visibility=invite_only` 的约骑要求 query `token` 匹配 `share_token`（creator 本人 / 已加入者豁免）；不匹配返回 **404**（不泄露存在性）。`public` 约骑不需要 token。这几个端点在"分享链接 → 详情页 → 报名"链路被调用（在 meetup-detail 页，不在 create 页），随约骑模块一起改。

---

## 5. 错误态和校验（逐项覆盖 handoff 要求）

> **人话**：每一种"用户可能搞砸"的情况，都得有一个清楚的拦截点，不能让脏数据流到约骑卡片上。

| 场景 | 当前是否已防 | 处理 |
|---|---|---|
| **没有路线不能发布** | ✅ 已防 | 创建草稿时 `_snapshot_from_route` 强制 segment_id/route_book_id 二选一，否则 422（📊`service.py:70-71`）；草稿一旦建成必有路线快照。前端 route 步未选不让进 details（📊`meetup-create.js:338`）。 |
| **出发时间太近不能发布** | ❌ **未防（gap）** | 当前 `publish_meetup` 只校验权限+DRAFT，**不校验 start_time**（📊`service.py:219-233`）→ 能发布一个出发时间已过的草稿。**本轮要补**：publish 时若 `now > start_time − 30min`（同截止线）返回 410 `cutoff passed`。复用 `_load_and_authorize_meetup(check_time_cutoff=True)` 已有的 cutoff 逻辑（📊`service.py:134-137`）。 |
| **人数上限范围** | ✅ 已防 | DB CHECK 2≤n≤20（📊`models.py:70-73`）+ schema `ge=2,le=20`（📊`schemas.py:30`）。图一的加减 stepper 前端也夹在 2..20。 |
| **照片上传失败后恢复** | ✅ 已防 | 上传失败回滚 DB record + storage 补偿删除（📊`media_service.py:81-96`）；前端 `Promise.all` 各自 catch + "部分上传失败" toast，不卡 loading（📊`meetup-create.js:517-526`）。失败后重选重传即可。 |
| **draft 被删 / 不存在** | ✅ 已防 | my-draft 返回 null → 新建；PATCH/publish/media 不存在 id → 404（📊`service.py:126`）。前端捕获 404 提示"草稿已失效"。 |
| **route_book 被删但已有 snapshot** | ✅ 已防 | snapshot_* 已冻结在 meetups 行（📊`models.py:38-41`）；`route_book_id` ON DELETE SET NULL（📊`models.py:37`）。图二地图缩略图拉不到 `preview_points` 时前端降级隐藏地图块（守"不显示占位符"规则 [[feedback_no_dash_placeholder]]），文字信息照常显示。 |
| **publish 并发点击** | ✅ 已防 | `publish_meetup` 走 `_load_and_authorize_meetup(... with_for_update().populate_existing())`（📊`service.py:119-125`）+ `require_status=['DRAFT']`；第二次点击时 status 已 OPEN → 409。前端 `submitting` 标记防连点（📊`meetup-create.js:442`）。 |
| **登录过期** | ✅ 已防 | 401 → 前端 `wx.login()` 静默续期（JWT 7 天，CLAUDE.md 约定）。所有写接口走 `get_current_user`。 |
| **invite_only 私圈防猜 id**（三审 Critical）| ❌ **新增** | invite_only 约骑的 `GET /{id}` / `join` / `participants` 必须带 query `token` == `share_token`（creator 本人 / 已加入者豁免），不匹配返回 **404**（不泄露存在性）。防连号 int id 被猜到后任意登录用户进私圈报名。`public` 约骑不校验 token。 |

**新增字段的校验规则**（schema 层，全部 `extra="forbid"` 防误传）：

- `visibility`：`Literal["public","invite_only"]`，缺省 `public`（理由见 §6.2）。
- `audience_tags`：`list[str]`，每项必须在 6 枚举白名单内（service 层校验，非法值 422），去重，**上限 6 个**。
- `eligibility_note`：`str | None`，`max_length=100`（纯展示文案）。
- `supply_point`：`str | None`，`max_length=128`。
- `safety_note`：`str | None`，`max_length=200`（发起人自填，或选 velo 模板后再改；模板列表是前端常量，存的永远是最终文本）。
- `share_token`：**不在请求 schema 里**——后端 create 时 `secrets.token_urlsafe(32)` 自生成，不接受前端传入；`MeetupResponse` 仅在 `is_creator` 时回填（防泄露给非组织者）。

---

## 6. JSON Schema（前端核心数据结构）

> 每个字段标来源：`[已有]` 后端现有 / `[前端派生]` 前端算 / `[需新增]` 要改后端 / `[mock]` 暂时写死。

### 6.1 `MeetupVisibility`（枚举）[需新增]
```json
"public" | "invite_only"
// public      = 本城可见，进公开约骑列表（按 snapshot_city 筛选）；详情/报名不需 token
// invite_only = 私圈可见，不进公开列表；详情/报名/骑友列表必须带 share_token 口令
//               （creator 本人 / 已加入者豁免）；防连号 id 被猜到后任意人进私圈
```

### 6.2 `MeetupPaceLevel`（枚举）[已有]
```json
"relaxed" | "cruise" | "training" | "race"
// 📊 app/meetup/schemas.py:15 现有
```

### 6.3 `MeetupDraftViewModel`（向导工作态 / 前端内存 + 草稿回填）
```jsonc
{
  "meetup_id": 123,                 // [已有] details→media 创建后拿到；草稿恢复用
  "status": "DRAFT",                // [已有]
  // —— 路线（snapshot 来自所选 segment/route_book） ——
  "route_book_id": 45,              // [已有]
  "segment_id": null,               // [已有] 与 route_book_id 二选一
  "route_title": "天龙山西线路书",   // [已有] snapshot_route_name
  "route_source_label": "腾讯地图生成", // [前端派生] 据所选来源映射文案
  "distance_km": 62.3,             // [已有] snapshot_distance(API已/1000)
  "elevation_gain_m": 1280,        // [已有] snapshot_climb
  "preview_points": [[112.5,37.8]],// [已有] route_book.preview_points 画缩略图
  "estimated_duration_minutes": 225,// [前端派生] (end-start)/60，显示 3:45
  // —— 时间 / 集合 / 人数 / 节奏（图一 logistics） ——
  "start_time": "2026-06-06T23:30:00Z",      // [已有] 存UTC
  "estimated_end_time": "2026-06-07T03:15:00Z",// [已有]
  "start_time_label": "周六 07:30",           // [前端派生] 本地时区格式化
  "meeting_point": "晋祠公园北门",            // [已有]
  "max_participants": 8,                       // [已有]
  "pace_level": "cruise",                      // [已有]
  "pace_label": "稳爬不竞速",                  // [前端派生] pace_level→中文
  "recommended_power_label": "FTP 160W+",      // [前端派生] 见下方对照表
  "average_speed_range": "17–22 km/h",         // [前端派生] 见下方对照表
  "supply_point": "天龙山景区口",              // [需新增]
  "description": "预计4.5小时，头盔必戴",       // [已有]
  // —— 图二 social 字段 ——
  "audience_tags": ["climb_steady","female_friendly"], // [需新增] 见 6.7
  "visibility": "invite_only",                 // [需新增] 默认 public
  "eligibility_note": "报名需有5次骑行记录",    // [需新增] 发起人自填，纯展示
  "safety_note": "头盔必戴 · 遵守交规 · 量力而行", // [需新增] 发起人写/选velo模板/改模板
  "share_token": "k3n8...x9",                  // [需新增] 系统 create 时生成，仅 creator 拿到；拼 invite_only 分享链接
  // —— 照片 ——
  "media_items": [ /* MeetupMediaItem[] */ ]   // [已有]
}
```

**`pace_level` → 推荐功率 / 均速 对照表（前端写死常量 / 桶 2）**：
| pace_level | pace_label | recommended_power_label | average_speed_range |
|---|---|---|---|
| relaxed | 轻松慢骑 | 不限功率 | 15–18 km/h |
| cruise | 稳爬不竞速 | FTP 160W+ 更舒服 | 17–22 km/h |
| training | 高强度拉练 | FTP 220W+ | 25–30 km/h |
| race | 竞速冲刺 | FTP 280W+ | 30+ km/h |
> 数值为占位区间，Tim 可在审阅时按真实骑行经验调；这是纯展示文案，不入库、不参与任何筛选。

### 6.4 `RouteBookSummary`（路线卡数据 / `RouteBookResponse` 子集）[已有]
```jsonc
{
  "id": 45,                         // 📊 route_book/schemas.py:20
  "name": "天龙山西线路书",
  "distance": 62300,               // 米；前端 /1000 显示 km
  "climb": 1280,
  "city": "taiyuan",
  "source": "tencent_direction",   // 📊 已支持 file_upload/activity_derived/tencent_direction
  "preview_points": [[112.5,37.8]] // 画地图缩略图红线
}
```

### 6.5 `InviteeSummary`（已加入骑友 / 接口 12 返回）[需新增]
```jsonc
{
  "user_id": 7,                    // [已有] participants.user_id
  "nickname": "阿泽",               // [需新增] JOIN users.nickname 📊 user/models.py:44
  "avatar_url": "https://...",     // [需新增] JOIN users.avatar_url 📊 user/models.py:45
  "is_creator": true,              // [已有] participants.is_creator → 显示"组织者"标签
  "joined_at": "2026-06-03T10:00:00Z" // [已有]
  // 注：原型标题"已邀请骑友（4）"的数字 = 前端取本接口返回数组 .length（或用 MeetupResponse.participants_count）
  // 注：原型的"最近同行"标签 v1 不返回（需共同骑行历史计算，见下方决策）
}
```
> **接口 12 visibility 门禁**：invite_only 约骑的本接口同样要求 `token == share_token`（creator/已加入者豁免），否则 404——否则猜 id 就能看到私圈约骑的参与者名单。
> **"最近同行"标签 v1 不做**：要算"这个人最近和组织者一起骑过"需要查共同约骑/共同赛段历史，是独立特性，留 v2。v1 只显示 `is_creator` → "组织者"标签，其余骑友不带标签。**这是单向看见（合规）**，不是用户互动。
> **原型"+邀请"占位头像 v1 隐藏**（`wx:if="{{false}}"`）：邀请动作统一走顶部"继续邀请" → `wx.shareAppMessage`，不用这个占位（避免和顶部按钮重复）。

### 6.6 `MeetupMediaItem`（= 现有 `MeetupMediaResponse` 📊 `schemas.py:91`，不新建，仅前端别名）[已有]
```jsonc
{
  "id": 1, "meetup_id": 123,        // 📊 meetup/schemas.py:96-104
  "type": "image",                  // image|video
  "file_id": "meetup_media/xxx.jpg",// 前端拼 baseUrl+/uploads/+file_id
  "caption": null, "seq": 0,
  "created_at": "..."
}
```

### 6.7 `MeetupPublishRequest`（发布前最终 PATCH + publish）
> publish 端点本身**无 body**（📊`router.py:195-198`）。"发布请求"实际是图二确认时的两步：先 PATCH 把 social 字段写入草稿，再 POST publish。这里给的是**那次 PATCH 的 payload**（= `MeetupPatchRequest` 的子集）：
```jsonc
// 图二「确认并发布」前的 PATCH（supply_point 已在 details 步设过，不在此）
// PATCH /api/meetups/{id}
{
  "audience_tags": ["climb_steady"],       // [需新增] 白名单内，去重，≤6
  "visibility": "invite_only",             // [需新增]
  "eligibility_note": "报名需有5次骑行记录", // [需新增] ≤100 字，纯展示
  "safety_note": "头盔必戴 · 遵守交规 · 量力而行" // [需新增] ≤200 字，发起人写/选velo模板/改
}
// 然后 POST /api/meetups/{id}/publish （无 body / share_token 不在请求里，create 时已生成）
```

**`audience_tags` 白名单（6 枚举 / service 层校验）**：
```
climb_steady    稳爬不竞速
high_intensity  高强度拉练
leisure         休闲骑游
photography     摄影打卡
female_friendly 女性友好
newbie_caution  新手慎选
```

**字段分配（CreateRequest vs PatchRequest）** —— 解决"哪些字段创建时传、哪些只 PATCH"的歧义：

| 字段 | MeetupCreateRequest | MeetupPatchRequest | 设置时机 |
|---|---|---|---|
| `supply_point` | ✅ 可选 | ✅ 可选 | 图一 details 步 |
| `audience_tags` / `visibility` / `eligibility_note` / `safety_note` | ✅ 可选（有默认） | ✅ 可选 | 图二 preview 步（也允许更早传） |
| `share_token` | ❌ 不接受传入（系统生成） | ❌ 不接受 | create 时后端 `secrets.token_urlsafe(32)` 生成 |

> `visibility` 不传 → DB 默认 `public`；`audience_tags` 不传 → 默认 `[]`。**实现红线**：`update_meetup` 的字段白名单（📊 `service.py:204` 现写死 6 项）必须把这 5 个自填字段全加进去，否则 PATCH 静默丢弃（三审 Critical）。

### 6.8 `MeetupPublishPreview`（图二渲染数据 / 前端组装，非单一接口）
> **没有专用接口**。图二所需 = `MeetupDraftViewModel`（前端已有，含 safety_note）+ `InviteeSummary[]`（接口 12）+ 平台固定文案（反骚扰提示）。结构上等于：
```jsonc
{
  "meetup": { /* MeetupDraftViewModel 全部字段（含 safety_note） */ },
  "invitees": [ /* InviteeSummary[]，接口 12 */ ],
  "participant_count": 4,                  // [已有] participants_count
  "registration_deadline_label": "周五 20:00 截止", // [前端派生] start-30min
  "safety_note": "头盔必戴 · 遵守交规 · 量力而行",   // [需新增] 来自 meetup.safety_note（发起人写/选模板）
  "anti_harass_notice": "VELO 反骚扰机制已开启…"     // [mock] 平台固定常量
}
```
> **安全提示 = 发起人可编辑字段 + velo 模板**（Tim 2026-06-03 拍）：存进 `meetups.safety_note`。发起人可①直接用 velo 现成模板、②空白自己写、③在模板基础上改。**velo 模板是前端常量列表**（见下），选中即填入 `safety_note` 后仍可继续编辑——模板只是快捷填充，存的永远是最终文本。图二那行小箭头接"编辑 / 选模板"弹层。
>
> **velo 安全提示模板（前端常量 / Tim 可增删）**：
> - `头盔必戴 · 遵守交规 · 量力而行`
> - `新手友好 · 全程收队 · 不拉爆`
> - `强度拉练 · 请自备补给 · 跟不上自行返回`
> - `山路多弯 · 控制下坡车速 · 保持车距`
>
> **报名门槛 eligibility_note 的编辑入口**：图二"节奏与门槛"卡里的"修改门槛 →"（原型 line 877-884）点开一个和安全提示同款的编辑弹层，发起人自由填文案（≤100 字，纯展示，后端 join 不校验）。其下方小字"为保障安全与体验，满足条件方可报名"（原型 `.gate-sub`）= 前端写死常量。

---

## 7. 架构改动判断（逐项回答 handoff）

### 7.1 现有 `meetup` API 够支撑两个页面吗？
**图一够**（logistics 全有）。**图二缺**：① 5 个组织者自填字段（补给点/适合谁/可见/门槛/安全提示）+ 系统 `share_token`；② 已加入骑友列表接口；③ 公开列表按 visibility 过滤 + invite_only 靠 `share_token` 防猜 id。另有 2 个既有代码 gap：publish 不校验出发时间过期；`update_meetup` 字段白名单写死 6 项、新字段会被静默丢弃（📊 `service.py:204`）。

### 7.2 哪些字段只是前端展示、不入库？
预计时长、推荐功率、预计均速、报名截止、反骚扰提示、地图缩略图、"已生成"徽标、"最近同行"标签——全部前端派生或固定常量（桶 2）。（安全提示原型里看着像固定文案，但 Tim 拍了要可编辑，已挪进入库字段，见 §7.3。）

### 7.3 哪些字段要加进 `meetups` 表？
**5 个组织者自填** + **1 个系统字段**：`supply_point` / `audience_tags` / `visibility` / `eligibility_note` / `safety_note`（自填）+ `share_token`（系统 create 时生成，私圈分享口令，§5）。
> **防火墙合规**：`meetups` 本身是约骑功能的非核心新表（不是 users/activities/segments），在它上面加列符合"新功能放新表/新模块"原则——未来想砍约骑，连表一起 drop（spec §15.3 删除 SOP 不变）。

### 7.4 哪些放 JSON / 枚举 / 派生？
| 字段 | 类型 | 理由 |
|---|---|---|
| `supply_point` | `VARCHAR(128) NULL` | 简单短文本（图一 logistics 字段，create 时可填） |
| `audience_tags` | `sa.JSON NOT NULL DEFAULT '[]'` | Tim 要"数组语义"；6 枚举白名单 service 层校验。**项目已有 JSONB 先例**（📊 `app/activity/models.py` simplified_track/splits/power_zones + `app/notification/models.py`，conftest 用 Text 替换跑 SQLite）。但 audience_tags 只做数组存取 + 白名单校验、不用 JSONB 运算符，**推荐用 `sa.JSON`（SQLAlchemy 通用类型）而非 pg `JSONB`**——SQLite 原生兼容、省掉 conftest dialect 分支。`NOT NULL DEFAULT '[]'` 避免给前端传 null。 |
| `visibility` | `VARCHAR(16) NOT NULL DEFAULT 'public'` + CHECK | 固定二枚举，CHECK 兜底（对齐项目所有枚举列写法 📊`models.py:62-77`） |
| `eligibility_note` | `VARCHAR(100) NULL` | 自由文案，纯展示 |
| `safety_note` | `VARCHAR(200) NULL` | 发起人写 / 选 velo 模板（前端常量）/ 改模板，纯展示 |
| `share_token` | `VARCHAR(43) NULL` | 私圈分享口令（`secrets.token_urlsafe(32)` ≈ 43 字符）。**create 时为每条约骑生成**；invite_only 的详情/报名/骑友列表凭它校验（§5）。MeetupResponse 只在 is_creator 时回填（防泄露）。存量 public 约骑该列 NULL 无妨（它们不需要口令）。 |

迁移：在 `migrations/versions/` 新建一条，`down_revision = "20260602_tencent_route_book"`（⚠ 用 **revision id 不是文件名** 📊 `migrations/versions/20260602_route_book_tencent_direction.py:12`），用 `op.add_column` ×6（5 自填 + share_token）+ `op.create_check_constraint`（visibility）。改的是已存在的 `meetups` 表（`20260528_meetup_route_book.py` 建的）。**同步**：`tests/conftest.py` 手写的 `_meetups_table`（📊 line 262）必须加这 6 列，否则现有约骑测试在 SQLite 建表阶段就炸。

### 7.5 要新增"发布前总览 preview"接口吗？
**不要。** 图二数据前端能自己组装（§6.8）：草稿表单在内存、骑友列表用接口 12、路线点用接口 3/6 已带的。新开聚合接口 = 多一个维护点 + 和详情接口字段漂移风险（违反"少增加文档/接口"精神）。**唯一真缺的是骑友列表（接口 12），它详情页也要用**，所以独立成接口而非塞进 preview 专用接口。

### 7.6 route_book 要加腾讯地图来源字段吗？
**不要，已经有了。** `source` 已含 `tencent_direction`（📊`route_book/models.py:51-53` CHECK + `schemas.py:11`），`POST /api/route-books/tencent-direction` 端点已上线（📊`route_book/router.py:69`）。图一/图二的"腾讯地图生成"路线卡直接用现有数据。

### 7.7 改动清单总览（防火墙视角）
```
后端（都在 app/meetup/ 内，不碰核心表）：
  models.py     +6 列（5 自填 + share_token）+ visibility CHECK
  schemas.py    Create/Patch +新字段；MeetupResponse +新字段 + share_token（仅回 creator）
                ⚠ MeetupResponse 是 extra="forbid"，新字段必须同步加否则序列化 500
  service.py    create 生成 share_token + 接新字段；
                ⚠ update_meetup 硬编码白名单（📊 service.py:204 仅 6 字段）必须扩展，
                  否则 PATCH 新字段被静默丢弃（建议改成从已知列集动态处理）；
                list_meetups 加 visibility='public' 过滤（owner 视角 /mine /my-draft 不过滤）；
                publish 加 start_time cutoff 校验；
                新增 list_participants()（+ from app.user.models import User 正向依赖 JOIN nickname/avatar）；
                invite_only 的 详情/join/participants 加 share_token 校验
  router.py     新增 GET /{id}/participants；详情/join 接 token 参数
  migrations/   1 条新迁移（meetups 加 6 列 / down_revision 用 revision id 不是文件名）
  conftest.py   _meetups_table 手写表同步加 6 列（audience_tags 用 Text/JSON 兼容）
前端（miniprogram/pages/meetup-create/）：
  onLoad 补 getMyMeetupDraft 恢复（含新字段）；图二渲染 social 字段 + 骑友列表 + 派生展示；
  onShareAppMessage 转发邀请（invite_only 链接带 share_token）；pace→功率/均速对照表常量
```
> 跨模块新依赖：接口 12 要 JOIN `users`（读 nickname/avatar）——这是**正向**读取（meetup → user），符合单向依赖链 `User ← … ← Meetup`，不引入反向 hook。

---

## 8. 测试清单

> **人话**：测的是"真实字段和状态对不对"，不是只跑一遍 happy path。

### 8.1 后端 API 测试（`tests/test_meetup_api.py` 等）
- **新字段 round-trip**：create/patch 写入 supply_point/audience_tags/visibility/eligibility_note/safety_note → response 原样返回。
- **audience_tags 白名单**：传非法标签 → 422；传重复 → 去重；传 >6 个 → 422。
- **visibility 过滤**：建 1 个 public + 1 个 invite_only 的 OPEN 约骑 → `GET /api/meetups` 只返回 public；owner 的 `GET /api/meetups/mine?role=created` 两个都在、`/my-draft` 不被过滤。
- **invite_only 口令门禁（三审 Critical）**：invite_only 约骑 → 不带 token `GET /{id}` / `join` / `participants` → 404；带正确 token → 200；creator 本人不带 token → 200（豁免）；已加入者不带 token → 200；public 约骑不带 token → 200。
- **share_token 生成**：create 后 `MeetupResponse` 给 creator 返回非空 share_token；非 creator 视角该字段为 null。
- **participants 接口**：happy（返回 nickname/avatar/is_creator，组织者 is_creator=true）；不存在 meetup → 404；未登录 → 401。
- **publish 过期校验（新 gap 修复）**：与 join/cancel 同截止线 `start_time − 30min30s`。边界三组：`now+29min → 410`、`now+31min → 200`、`now+2h → 200`。
- **update_meetup 白名单（三审 Critical 回归）**：PATCH 写 5 个自填字段后再 GET，确认值真的变了（防只验 status code、漏掉 silent discard）。
- **extra=forbid**：PATCH 传未知字段 → 422；传 share_token → 422（不接受前端传入）。
- **eligibility_note/supply_point/safety_note 长度**：超长 → 422。
- **回归既有**：draft_exists 409、time_order 422、media 上传补偿、IDOR 等既有测试不被破坏。

### 8.2 小程序静态测试（`tests/test_meetup_miniprogram_static.py`）
- wxml ↔ js 函数名对得上（图二新增的 toggle/share handler）。
- 新 social 字段 setData ↔ wxml 渲染字段一致。
- `onShareAppMessage` 存在且返回正确 path。
- onLoad 调 `getMyMeetupDraft`（恢复逻辑 📊 api.js:375 真名，不是 getMyDraft）。
- pace→功率/均速对照表覆盖 4 个档位。

### 8.3 关键真用路径测试（真机 / 真 PG，mock 覆盖不到）
1. **草稿恢复全链路**：填到一半退出 → 重进看到草稿回填（含照片 + 地图缩略图）→ 改 social → 发布 → 跳详情。
2. **私圈分享邀请**：建 invite_only 约骑 → 转发给微信好友（链接带 share_token）→ 好友打开详情 → 加入成功；另一账号不带 token 直接猜 id 访问 → 404；同时确认它**不出现**在公开约骑列表。
3. **route_book 删后降级**：删掉草稿引用的路书 → 图二地图块隐藏，文字快照仍显示（不出现坏链/占位符）。
4. **publish 并发**：两次快速点"确认并发布" → 第二次 409，不产生双发布。
5. **发布过期草稿**：放一个出发时间已过的草稿点发布 → 被 410 拦。

---

## 9. Tim 已拍定（2026-06-03）

1. **UX 顺序**（§1）：✅ 图一"发布约骑" → 图二"确认并发布"，两屏先后衔接。
2. **安全提示**（§6.8）：✅ 发起人可自己写 / 可用 velo 现成模板 / 可在模板上改 → 入库 `meetups.safety_note`，模板是前端常量。
3. **visibility 默认值**（§6.2）：✅ 默认 `public`（全城可见，利于冷启动被刷到），`invite_only`（私圈）保留——两个都做。

## 9.5 三审整合记录（2026-06-03 Round 1）

3 reviewer（Claude 忠 spec / Claude 集成 grep / Codex 异源）并行审，高度收敛（2 条 Critical 被多人独立抓到）。本版已全修：

| 编号 | 来源 | 问题 | 处理 |
|---|---|---|---|
| C1 | 集成+Codex | invite_only 靠"不进列表"挡人，但连号 int id 可猜 → 任意登录用户进私圈报名（假私圈，撞原型"仅被邀请人可见"承诺）| ✅ Tim 拍**加 share_token 口令**；详情/join/participants 对 invite_only 校验 token（§5/§6.1/§6.8/§7） |
| C2 | 集成+Codex | 迁移 `down_revision` 写成文件名，真 revision id 是 `20260602_tencent_route_book`（照抄断 Alembic 链）| ✅ §7.4 改正 |
| C3 | 集成 | `update_meetup` 字段白名单写死 6 项（📊 service.py:204），新字段 PATCH 被静默丢弃 | ✅ §6.7/§7.7 标注必须扩展 + 加回归测试 |
| C4 | 忠 spec | 补给点归错层（图一 logistics、不是图二 social）| ✅ §0/§3.2/§6.7 改正 |
| I1 | 忠 spec | "修改门槛"编辑入口 + `.gate-sub` 静态文案无归属 | ✅ §6.8 补编辑弹层 + §2 桶2 标静态 |
| I2 | 集成+Codex | "项目无 JSONB 先例"错（activity/notification 已有）；JSONB 在 SQLite conftest 要同步 | ✅ §7.4 改用 `sa.JSON` + conftest 同步注 |
| I3 | 忠 spec+集成 | CreateRequest vs PatchRequest 字段分配不清 | ✅ §6.7 加分配表 |
| I4 | 集成 | api helper 真名 `getMyMeetupDraft`（非 getMyDraft）| ✅ §3.3/§8.2 改正 |
| I5 | 忠 spec | "已邀请骑友（4）"计数来源 / "+邀请"占位 / "发布前检查"行无归属 | ✅ §6.5 补计数注 + 占位 v1 隐藏 / §2 桶2 标静态 |
| I6 | 忠 spec+Codex | publish cutoff 语义/测试边界太宽 | ✅ §5/§8 明确复用 join/cancel 同截止线 + 边界三组测试 |
| M | 集成+Codex | router.py:38→39 行号 / `MeetupMediaItem`=现有 `MeetupMediaResponse` / §0 "4个"→"5个" | ✅ 全改 |

**收敛**：Critical 4 → 0 / Important 6 → 0 / **进 plans gate 达成**（待 Tim 终审本版）。无 scope creep。

下一步 → Tim 终审本版 → 进 writing-plans 拆 task → 才写代码。

---

## 10. 链接索引
- 约骑模块 v1 设计：`docs/superpowers/specs/2026-05-28-meetup-module-design.md`
- 原型 + 字段清单：`exports/meetup-create-prototype-handoff/`
- 微信合规（转发分享 vs 站内互动）：[[feedback_wechat_miniprogram_no_direct_social]]
- 不显示占位符规则：[[feedback_no_dash_placeholder]]
- 现有代码事实：`app/meetup/{models,schemas,service,router,media_service}.py` / `app/route_book/{models,schemas,service}.py` / `app/user/models.py:44-45` / `miniprogram/pages/meetup-create/meetup-create.js`
