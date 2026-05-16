# Sprint 6 Task-4 — 前端 profile 页改造

> 所属：Sprint 6（"我的"页基础落地 / 共 6 task）
> 这是第 4 个 task / 前端主体改造 / 依赖 task-1 / task-2 / task-3 全部 ship
> v0.2（2026-05-16）：修 endpoint 前缀 /api/user 单数（v0.1 用了复数 /api/users）/ 改 bio 走 PATCH /me / 改 nickname 走 PUT /profile / 城市勋章 6 格不是 7 格 / D-P08 描述精确
> v0.3（2026-05-16 续工）：字段名校准到真 schema（distance / rides / elevation_gain / duration / medals[].label / 无 icon 字段）/ ride-card 字段对齐 ActivitySummary（id 不是 activity_id / distance 公里不是米 / avg_speed 已是 km/h）/ self stats endpoint 不返 avg_power_w → task-4 self 视图也不渲染（P3 改写不删 / 见 tech-debt）
> 上下文：2026-05-15 brainstorm / Tim 拍三模块布局 + 数字 hero 化 + 复用首页大卡片 + 不写 NPC 文案

> **⚠️ 字段名以 `app/user/schemas.py` + `app/activity/schemas.py` 真 schema 为准——本卡内 wxml/js 示例若与代码事实有差异以代码为准。spec subagent 起手必读 PRD §0.1 真实代码事实表 + grep schemas.py。**

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

把"我的"页（profile 页）整体重写——从现在 132 行 js + 111 行 wxml 的字段表格 / 升级成**骑手身份名片**。视觉密度有冲击 / 数字字号变大 + 留白 / 但**不写老登 NPC 文案**（那是下一个独立 Sprint）。

顺手清一条 tech-debt P3：current_month_summary.avg_power_w 字段后端返但前端不渲染。

### 用户故事

**故事 A — 完整身份名片**
小明每天打开 velo "我的"页 → 第一眼看到自己头像 + "成都老登 / 公路党 / FTP 220W" 签名 + 三个徽章（FTP 220W / 累计 8500km / 雀儿山常客）→ 往下滑看到本周 / 累计训练统计（数字超大 + 灰小标签 + 2 列网格）→ 再往下是热图 + 城市勋章墙（3 / 6 已解锁）→ 最下方是历史活动列表（和首页同款大卡片）→ 点活动卡进 detail 页（沿用首页交互）。

**故事 B — 看别人**
CCF 点小明的头像 → 进 user 页 → 看到同款身份名片（bio / 徽章 / 勋章墙跟小明自己看的完全一样）。**但是**——CCF 看不到小明的 ftp / weight（既有隐私字段集差异保留 / 看自己时才有）。

**故事 C — 数字 hero 化**
现在"累计 8500km"是一行小字。改造后是一个超大的"8500"配下方灰色小字"km"。一眼扫到。视觉冲击大。但**没有"绕地球 1/5 圈"那种祝贺文案**（那是 Persona Sprint 的事）。

**故事 D — 萌新空状态**
新用户没上传过活动 / 没填签名 → 头像区只有头像 + 昵称 + 城市 / 签名整块隐藏 + 徽章行整行隐藏 → 中部统计全是 0 / 热图空 / 城市勋章 0 / 6 全灰 / 活动列表显示"还没活动 / 上传第一条" → 不报错 / 不残破。

**故事 E — 编辑入口**
点头像 / 昵称 → 走 PUT /api/user/profile（v5 期既有路径 / 改主资料字段）。点签名（bio）/ 城市 → 走 PATCH /api/user/me（v5 期既有路径 / 改 settings 类字段 / task-1 新加 bio 到此处）。点头部右上角"设置"icon → 进 settings 子页（task-5 做）。

### 怎么算做对了

- ✓ 真机测试：打开"我的"页 / 4 模块全部正确渲染（头像区 / 训练统计 / 热图+勋章墙 / 活动列表）
- ✓ bio 编辑：输入 / 保存 / 刷新可见
- ✓ 徽章自动从后端拉 / 按优先级排序展示
- ✓ 城市勋章墙：已解锁点亮 / 未解锁灰色 / 进度数字"3 / 6"正确（6 城不是 7 城）
- ✓ 活动列表与首页样式一致（**复用同一卡片组件 / 不再 copy paste**）
- ✓ P3 清掉：current_month_summary.avg_power_w 在训练统计卡渲染
- ✓ **新增字段自他对称**：在 user 页看别人 profile / bio / badges / city-medals 字段一致
- ✓ 既有字段差异保留：他人 profile 不返 ftp / weight（符合预期 / 不是 bug）
- ✓ 性能：首屏渲染 < 1s（4 接口并发 + 头像区先 paint）
- ✗ 任何 "-" 占位符出现在画面里 / 是 bug（永久规则 / 见 memory `feedback_no_dash_placeholder.md`）
- ✗ 写了任何 "恭喜你 / 棒棒哒 / 加油" 类拟人化文案 / 是 bug（NPC 文案延后）

### 这次**不做**的事

- **NPC 拟人化文案**（"今天嗑药了？" / 数字祝贺 / 黑色幽默 / 跨时间镜像）→ Persona Engine Sprint
- 数字英雄化的"换算成珠峰/绕地球"对比文案 → 同上延后
- 路线赛段着色 / 徽章贴在地图上 → 未来"地图叙事化"大工程
- 装备身份认同区（车 / 码表 / 鞋）→ 未拍
- 长简介 / Markdown 渲染 → 永不做
- 隐私开关 / "仅自己可见"按钮 → 隐私 Sprint
- 关注 / 粉丝 / 点赞 / 评论 → 社交 Sprint

### 估时

2-3 天（含双审 + 真机测试）

---

## ─────── 折叠：执行 subagent 看的技术细节 ───────

<details>
<summary>展开</summary>

### 起手必跑：现状 grep

```bash
# profile 现状
wc -l miniprogram/pages/profile/profile.*

# 首页大卡片当前结构（复用基础）
rg "ride|fetchRides|/api/activities" miniprogram/pages/home/home.js

# 现有 endpoint 调用集合
rg "api\.get|api\.put|api\.patch" miniprogram/pages/profile/profile.js

# tech-debt P3 字段位置
rg "current_month_summary" miniprogram/pages/

# 永久规则：禁止 "-" 占位符
rg "'-'|\"-\"" miniprogram/pages/profile/profile.wxml
```

**事实表实证（PRD § 0.1）**：
- profile.js 132 行 / wxml 111 行 / wxss 222 行（v0.1 grep）
- endpoint 前缀 `/api/user`（单数）+ `/api/activities`
- v5 期 home.js 拉 `GET /api/activities?page=1&page_size=20`（大卡片）
- current_month_summary 来自 GET /api/user/{user_id}/profile 看他人 endpoint（v0.3 grep 实证 self stats `StatsResponse` 无 avg_power_w）

### 页面布局（从上到下 4 块）

**块 1 - 头像区**（字段名 = `UserProfile` 真 schema / Badge 无 icon 字段）：
```xml
<view class="hero-section">
  <image class="avatar" src="{{profile.avatar_url}}" bindtap="onEditAvatar" />
  <view class="nickname" bindtap="onEditNickname">{{profile.nickname}}</view>
  <!-- city 来自 profile.city（v5 D9 fallback / 不是 cityLabel 那种独立映射）-->
  <view class="city-row" wx:if="{{profile.city}}">{{profile.city}}</view>

  <!-- 新增：bio 签名（task-1 / 字段 = profile.bio / NULL 整块隐藏）-->
  <view class="bio" wx:if="{{profile.bio}}" bindtap="onEditBio">{{profile.bio}}</view>
  <view class="bio-placeholder" wx:else bindtap="onEditBio">+ 添加签名</view>

  <!-- 新增：徽章行（task-2 / Badge schema = type + label / 无 icon 字段）-->
  <view class="badge-row" wx:if="{{profile.badges.length > 0}}">
    <view class="badge" wx:for="{{profile.badges}}" wx:key="type">
      {{item.label}}
    </view>
  </view>

  <!-- 右上角设置 icon → 跳 settings 子页 (task-5) -->
  <view class="settings-icon" bindtap="onTapSettings">⚙️</view>
</view>
```

**块 2 - 训练统计**：数字 hero 化（CSS 大字号 + 灰色小标签 + 2 列网格 + 留白）。

字段口径（`StatsResponse` 真返）：`stats.distance`（公里 float / wxs km() 显示 2 位小数）/ `stats.rides`（int）/ `stats.elevation_gain`（米 int）/ `stats.duration`（秒 / wxs secToHm() 转 "Xh Ymin"）/ `stats.goal_percent`。

⚠️ **不渲染 avg_power_w**：v0.3 grep 实证 self stats endpoint 不返此字段 / 看他人路径才返 / 详 tech-debt P3。

**块 3 - 热图 + 城市勋章墙**（CityMedal schema = `city` / `label` / `unlocked` / 无 icon 字段）：
```xml
<!-- 热图（已有 / GET /api/user/me/heatmap → tracks: list[list[list[float]]] / activity_count）-->
<view class="heatmap-card">
  <heatmap-canvas />
</view>

<!-- 新增：城市勋章墙（task-3 / cityMedals.total = 6 / 不是 total_count）-->
<view class="city-medals-wall">
  <view class="medals-title">城市征服：{{cityMedals.unlocked_count}} / {{cityMedals.total}}</view>
  <view class="medals-grid">
    <view class="medal {{item.unlocked ? 'unlocked' : 'locked'}}"
          wx:for="{{cityMedals.medals}}" wx:key="city">
      {{item.label}}
    </view>
  </view>
</view>
```

**块 4 - 活动列表**：复用 `<ride-card />` 组件（profile 引入 + 透传 ActivitySummary）。

**v0.3 复用范围修订**：home.wxml 当前 inline 卡片含 home 专属字段（头像 / nickname / segments / initial / status pending 态）→ task 卡 v0.2 "home 单人不接头像跳转，未来开放 task-4.3 多人 home 流时一起做"明确推迟。本 task **只让 profile 用 ride-card**，**不动 home.wxml**（避免破坏首页 segments 异步加载 / status pending 态等成熟逻辑）。

```
miniprogram/components/ride-card/  ← 新建组件目录（task-4 落地）
miniprogram/pages/profile/profile.wxml ← 引入 <ride-card />（本 task）
miniprogram/pages/home/home.wxml ← 维持 inline 卡片（推迟 / 等 task-4.3 多人流再迁移）
```

**字段契约**（ride-card 接 ActivitySummary 真 schema 字段 / wxs 内部格式化）：
- `id`（不是 `activity_id`）/ `title` / `distance`（公里）/ `duration`（秒）/ `elevation_gain`（米）/ `avg_speed`（km/h）/ `started_at`
- 父页面可选补 `startedAtDisplay`（已格式化"今天 09:30"字符串）作为 subtitle 槽位
- wxml 用 `utils/format.wxs` 的 `km()` / `secToHm()` / `roundInt()` 显示层格式化

**复用要求**（防双 subagent 越界 / 见 memory `feedback_dual_subagent_shared_utils_ownership.md`）：
- 组件接口固定（rides 数组 + tap-ride 事件）/ 字段名 = ActivitySummary 真 schema
- profile 不修改 ride-card 内部 / 只传 data + 监听事件
- ride-card 不脑补字段映射（不再有 distance_km / duration_display / activity_id 那种映射层）

### onShow 拉数据（5 接口并发 / 4 个 setData + 1 个分页）

字段口径（v0.3 grep 实证 / `app/user/schemas.py` + `app/activity/schemas.py`）：
- `GET /api/user/profile` → `UserProfile`: `id` / `nickname` / `avatar_url` / `city` / `bio` / `ftp` / `weight` / `bike_type` / `weekly_goal` / `created_at` / `badges[]`
- `GET /api/user/stats?period=week` → `StatsResponse`: `period` / `distance`（公里 float）/ `rides`（int）/ `elevation_gain`（米 int）/ `duration`（秒 int）/ `weekly_goal` / `goal_percent`
- `GET /api/user/me/heatmap` → `HeatmapResponse`: `city` / `tracks: list[list[list[float]]]` / `activity_count`
- `GET /api/user/me/city-medals` → `CityMedalsResponse`: `unlocked: list[str]` / `unlocked_count` / `total` / `medals: list[CityMedal]`；CityMedal = `city` / `label` / `unlocked`（**无 icon 字段**）
- `GET /api/activities?page=N&page_size=N` → `ActivityListResponse`: `items: list[ActivitySummary]` / `total` / `page` / `page_size`；ActivitySummary = `id` / `title` / `status` / `distance`（公里 / service 已转）/ `duration`（秒）/ `elevation_gain`（米）/ `avg_speed`（km/h / worker 已转）/ `avg_power` / `avg_hr` / `started_at` / `created_at`
- Badge schema = `type` / `label`（**无 icon 字段**）

```javascript
onShow() {
  if (!app.globalData.token) {
    this.setData({ isLoggedIn: false, /* 重置 */ })
    return
  }
  this.setData({ isLoggedIn: true })

  // 并发拉 4 接口（endpoint 前缀 /api/user 单数 / v0.2 修）
  api.get('/api/user/profile').then(p => this.setData({ profile: p }))
  api.get('/api/user/stats', { period: 'week' }).then(s => this.setData({ stats: s }))
  api.get('/api/user/me/heatmap').then(h => this.setData({ heatmap: h }))
  api.get('/api/user/me/city-medals').then(c => this.setData({ cityMedals: c }))

  // 活动列表分页（独立 / 不阻塞）/ GET /api/activities?page=1&page_size=10
  this.fetchRides(true)
}
```

### 编辑入口（**bio 走 PATCH /me / nickname 走 PUT /profile**）

```javascript
onEditBio() {
  wx.showModal({
    title: '签名',
    editable: true,
    placeholderText: '一句话告诉骑友你是谁',
    success: (res) => {
      if (!res.confirm) return
      if (res.content && res.content.length > 30) {
        wx.showToast({ title: '签名不能超过 30 字', icon: 'none' })
        return
      }
      // bio 走 PATCH /me（同 city / settings 类）/ v0.2 修
      api.patch('/api/user/me', { bio: res.content || null })
        .then(() => this.refresh())
    },
  })
}

onEditNickname() {
  // nickname 走 PUT /profile（主资料字段 / v5 期分工 / v0.2 修）
  wx.showModal({
    title: '昵称',
    editable: true,
    success: (res) => {
      if (!res.confirm) return
      api.put('/api/user/profile', { nickname: res.content })
        .then(() => this.refresh())
    },
  })
}

onTapSettings() {
  wx.navigateTo({ url: '/pages/settings/settings' })
}
```

### tech-debt P3 处理（v0.3 续工修订 / 不删 / 改写描述）

**真 schema 校准（v0.3 必读）**：
- `GET /api/user/stats?period=week` 返 `StatsResponse`——字段 = `distance` / `rides` / `elevation_gain` / `duration` / `weekly_goal` / `goal_percent` —— **不返 avg_power_w**
- `avg_power_w` 只在 `GET /api/user/{user_id}/profile` → `UserProfileResponse.current_month_summary._MonthSummary` 看他人路径返
- self 视图想渲染 → 要么改 self stats schema 加派生字段（动核心 endpoint 风险大）/ 要么 self 页多调一次 `/{me_id}/profile`（浪费 endpoint）
- **task-4 决策**：self 视图不渲染 avg_power_w / P3 不删 / 改写为"等后端 stats endpoint 加派生字段再清"
- commit message 说明"P3 改写描述 / self stats endpoint 不返此字段 / 等扩展 schema 再清"

### "-" 占位符永久规则

按 memory `feedback_no_dash_placeholder.md`：

- ❌ `<text>{{x || '-'}}</text>`
- ✅ `<text wx:if="{{x}}">{{x}}</text>`
- 字段缺失整块隐藏 / 不显示 "-" 也不显示"暂无 XX"

### 前端协议自校验（commit 前必跑 / 见 memory `feedback_frontend_protocol_self_check.md`）

```bash
# 1. wxml ↔ js 函数名一致
rg "bindtap=\"on" miniprogram/pages/profile/profile.wxml
rg "^\s+(on[A-Z]\w+)\(" miniprogram/pages/profile/profile.js

# 2. js ↔ api helper 参数对齐
rg "api\.(get|patch|put)\(" miniprogram/pages/profile/profile.js
# 对照 utils/api.js 是否签名一致

# 3. setData 字段 ↔ wxml 渲染
rg "this\.setData" miniprogram/pages/profile/profile.js
# 对照 wxml 是否真的渲染了这些字段
```

### 测试要求

- 真机测试小程序 / 跑 5 个故事场景全过
- **自他对称 diff（新字段）**：自己看自己 vs 别人看我 / bio / badges / city_medals 完全一致 / ftp / weight 差异符合预期（既有字段集故意不对称）
- P3 清理后 `docs/tech-debt.md` 更新

### 双审顺序

1. **Claude A 忠 PRD**：4 块布局完整 / 字段来源对应 / 不出现 NPC 文案 / endpoint 前缀 /api/user 单数
2. **Claude B 集成审**：复用 ride-card 组件是否破坏首页 / 新字段自他对称是否真一致 / 既有字段差异是否保留
3. **Codex 异源审**：调用 `codex:codex-rescue` / 重点扫"wxml 协议三层一致性" + "tech-debt P3 清理是否真的渲染了" + "bio 编辑路径调对（PATCH /me）/ nickname 调对（PUT /profile）"

### 依赖 / 顺序

- 依赖：task-1（bio）/ task-2（badges）/ task-3（city-medals）全部 ship
- 阻塞：task-6 真用回归

### 部署 SOP

5 步 SOP / 前端发版还需小程序后台审核（内测无需）。真机预览测试。

</details>
