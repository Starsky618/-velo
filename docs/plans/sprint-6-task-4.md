# Sprint 6 Task-4 — 前端 profile 页改造

> 所属：Sprint 6（"我的"页基础落地 / 共 6 task）
> 这是第 4 个 task / 前端主体改造 / 依赖 task-1 / task-2 / task-3 全部 ship
> v0.2（2026-05-16）：修 endpoint 前缀 /api/user 单数（v0.1 用了复数 /api/users）/ 改 bio 走 PATCH /me / 改 nickname 走 PUT /profile / 城市勋章 6 格不是 7 格 / D-P08 描述精确
> 上下文：2026-05-15 brainstorm / Tim 拍三模块布局 + 数字 hero 化 + 复用首页大卡片 + 不写 NPC 文案

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
- current_month_summary 来自 GET /api/user/{user_id}/profile 看他人 endpoint（self stats 路径需确认）

### 页面布局（从上到下 4 块）

**块 1 - 头像区**：
```xml
<view class="hero-section">
  <image class="avatar" bindtap="onEditAvatar" />
  <view class="nickname" bindtap="onEditNickname">{{profile.nickname}}</view>
  <view class="city-row" wx:if="{{cityLabel}}">{{cityLabel}}</view>

  <!-- 新增：bio 签名（task-1）-->
  <view class="bio" wx:if="{{profile.bio}}" bindtap="onEditBio">{{profile.bio}}</view>
  <view class="bio-placeholder" wx:else bindtap="onEditBio">+ 添加签名</view>

  <!-- 新增：徽章行（task-2）-->
  <view class="badge-row" wx:if="{{profile.badges.length > 0}}">
    <view class="badge" wx:for="{{profile.badges}}" wx:key="type">
      {{item.label}}
    </view>
  </view>

  <!-- 右上角设置 icon → 跳 settings 子页 (task-5) -->
  <view class="settings-icon" bindtap="onTapSettings">⚙️</view>
</view>
```

**块 2 - 训练统计**：数字 hero 化（CSS 大字号 + 灰色小标签 + 2 列网格 + 留白）。含 current_month_summary.avg_power_w 渲染（P3 清掉 / wx:if 包裹避免 null）。

**块 3 - 热图 + 城市勋章墙**：
```xml
<!-- 热图（已有 / GET /api/user/me/heatmap）-->
<view class="heatmap-card">
  <heatmap-canvas />
</view>

<!-- 新增：城市勋章墙（task-3）-->
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

**块 4 - 活动列表**：复用首页同款大卡片。提取首页 `<view class="ride-card">...` 为公共 template 或 component：

```
miniprogram/components/ride-card/  ← 新建组件目录（如果首页是 inline / 这次提取）
miniprogram/pages/home/home.wxml   ← 改用 <ride-card />
miniprogram/pages/profile/profile.wxml ← 同款 <ride-card />
```

**复用要求**（防双 subagent 越界 / 见 memory `feedback_dual_subagent_shared_utils_ownership.md`）：
- 组件接口固定（rides 数组 + 点击事件）
- profile 不修改 ride-card 内部 / 只传 data + 监听事件

### onShow 拉数据（5 接口并发 / 4 个 setData + 1 个分页）

```javascript
onShow() {
  if (!app.globalData.token) {
    this.setData({ isLoggedIn: false, /* 重置 */ })
    return
  }
  this.setData({ isLoggedIn: true })

  // 并发拉 4 接口（endpoint 前缀 /api/user 单数 / v0.2 修）
  api.get('/api/user/profile').then(p => this.setData({ profile: p }))
  api.get('/api/user/stats?period=week').then(s => this.setData({ stats: s }))
  api.get('/api/user/me/heatmap').then(h => this.setData({ heatmap: h }))
  api.get('/api/user/me/city-medals').then(c => this.setData({ cityMedals: c }))

  // 活动列表分页（独立 / 不阻塞）
  this.fetchActivities(1)
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

### tech-debt P3 清理（顺手做）

```html
<!-- 训练统计卡内追加 / 包 wx:if 防 null -->
<view class="stat-cell" wx:if="{{stats.current_month_summary.avg_power_w}}">
  <view class="stat-number">{{stats.current_month_summary.avg_power_w}}</view>
  <view class="stat-label">本月平均功率 W</view>
</view>
```

完成后在 `docs/tech-debt.md` 删除 P3 这一条 + commit message 提一句"task-4 顺手清 P3"。

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
