# 任务 4.1：个人页框架改造（批 1 容器 / 第一步独立 ship）

> **批 1 根任务**——4.2 / 4.3 都依赖个人页的"框架 + 槽位"结构，本任务必须先 ship 验证稳定再进 4.2 / 4.3。

---

## 🎯 目标（一句话）

把现有 `pages/profile/profile.wxml`（180+ 行）拆成"框架 + 槽位"结构（5 区块）。框架先独立 ship，登录 / 累计统计 / 我的荣誉跳转 / 设置跳转 / 退出登录全部行为**完全保持**；新增 city 自动渲染 fallback + 2 个槽位 placeholder（"功能加载中"），**不实现**功率曲线 / 热力图真显示（留 4.2）。

---

## ⛓ 前置依赖

无（v5 Sprint 0/1/2/3 全部 ship）。

## 📥 输入契约

无新输入。沿用现有 `GET /api/user/profile` + `GET /api/user/stats`。

## 📤 输出契约（4.2 / 4.3 依赖）

| 产出 | 用途 | 被谁依赖 |
|------|------|---------|
| profile.wxml 5 区块结构（含 2 槽位 placeholder） | 4.2 往槽位塞功率曲线 + 热力图 | 4.2 / 4.3 |
| profile.js fetchPowerCurve / fetchHeatmap 占位方法 | 4.2 替换为真实调用 | 4.2 |
| city badge fallback 渲染（city 有值显示 / 无值不显示）| 4.3 用户详情页同款逻辑复用 | 4.3 |
| profile.wxss city-badge 样式 | 4.3 用户详情页 import | 4.3 |

---

## 🧱 现状清单（subagent 必先 grep + Read 验证后再动手）

### 文件清单

```bash
ls miniprogram/pages/profile/
# 应见：profile.js / profile.wxml / profile.wxss / profile.json
```

### 关键现状（grep 实证）

| 项 | grep 命令 | 期望结果 |
|---|---|---|
| profile.wxml 行数 | `wc -l miniprogram/pages/profile/profile.wxml` | 当前约 180 行（黄灯阈值 300） |
| 现有 fetch 方法 | `grep -n "fetchUserData\|fetchStats" miniprogram/pages/profile/profile.js` | 应见 fetchUserData + 累计统计 fetch |
| 现有跳转 | `grep -n "navigator\|switchTab" miniprogram/pages/profile/profile.wxml` | 应见 navigator → /pages/honor/honor 和 /pages/settings/settings |
| profile.city 字段 | `grep -n "city" app/user/schemas.py` | UserProfile 必须含 `city: Optional[str] = None`（**Sprint 4 baseline 加 / D18 codex 异源审 / 之前 v5 没加导致 4.1 city badge fallback 拿不到值**） |
| 全局 token | `grep -n "globalData.token" miniprogram/app.js` | 应见登录后写 token |

**任一不符** → 停下报 Tim，不擅自修复。

---

## 🛠 操作步骤

### Step 1：Read 现状 4 文件（不允许凭印象）

- [ ] **1.1** Read `miniprogram/pages/profile/profile.wxml`（全文）
- [ ] **1.2** Read `miniprogram/pages/profile/profile.js`（全文）
- [ ] **1.3** Read `miniprogram/pages/profile/profile.wxss`（全文）
- [ ] **1.4** Read `miniprogram/pages/profile/profile.json`

### Step 2：先写测试（TDD）

- [ ] **2.1** 写测试 `tests/miniprogram/test_profile_framework.py`（如果项目无小程序单测，跳过 + 写"手工回归 checklist"代替）

手工回归 checklist（5 项）：

```markdown
## 4.1 框架改造手工回归 checklist
- [ ] 未登录态：登录卡片显示 / 点击登录正常
- [ ] 已登录态：用户信息名片 + 累计统计 + 2 槽位 placeholder + 导航卡片显示
- [ ] city 有值（如"北京"）：名片角落显示 city badge
- [ ] city 无值（null）：名片角落不显示 / 不弹引导
- [ ] 跳转：荣誉 / 设置 / 退出登录全部正常
```

### Step 3：改造 profile.wxml（5 区块）

- [ ] **3.1** 拆成 5 区块结构：

```xml
<!-- 1. 用户信息名片（含 city 自动渲染） -->
<view class="user-card card" wx:if="{{isLoggedIn}}">
  <view class="user-header">
    <view class="avatar"><text class="avatar-text">{{...}}</text></view>
    <view class="user-info">
      <text class="user-name">{{profile.nickname}}</text>
      <text class="user-id">ID: {{profile.id}}</text>
    </view>
    <!-- city badge 自动渲染 / D9 / 无值不显示 -->
    <view class="city-badge" wx:if="{{profile.city && profile.city !== 'unknown'}}">
      <text>{{cityLabel}}</text>
    </view>
  </view>
  <view class="params-row" wx:if="{{profile.ftp || profile.weight}}">...</view>
</view>

<!-- 2. 累计骑行卡片（不变 / 沿用现有） -->
<view class="stats-card card">...</view>

<!-- 3. 功率曲线槽位（4.2 塞内容） -->
<view class="card power-curve-slot">
  <text class="slot-placeholder">功率曲线 — 功能加载中</text>
</view>

<!-- 4. 骑行热力图槽位（4.2 塞内容） -->
<view class="card heatmap-slot">
  <text class="slot-placeholder">骑行热力图 — 功能加载中</text>
</view>

<!-- 5. 导航卡片（不变） -->
<view class="menu-card card">...</view>
```

- [ ] **3.2** 未登录状态保持现状（登录卡片不动）

### Step 4：改造 profile.js（加 city 显示逻辑 + 占位 fetch 方法）

- [ ] **4.1** data 加 `cityLabel: ''`（用于 wxml 显示中文）
- [ ] **4.2** 加 city 中文映射常量：

```js
const CITY_LABELS = {
  beijing: '北京', shanghai: '上海', hangzhou: '杭州',
  shenzhen: '深圳', chengdu: '成都', taiyuan: '太原'
}
```

- [ ] **4.3** 在 fetchUserData 拿到 profile 后 setData cityLabel：

```js
const cityLabel = profile.city && profile.city !== 'unknown'
  ? CITY_LABELS[profile.city] || ''
  : ''
this.setData({ profile, cityLabel })
```

- [ ] **4.4** 加 2 个占位方法（4.2 替换为真实调用）：

```js
fetchPowerCurve() {
  // 4.2 task 替换为真实 GET /api/user/me/power-curve
  return Promise.resolve(null)
},
fetchHeatmap() {
  // 4.2 task 替换为真实 GET /api/user/me/heatmap
  return Promise.resolve(null)
}
```

- [ ] **4.5** **不在 onShow 调用 fetchPowerCurve / fetchHeatmap**（占位 / 留 4.2 实现 + 调用时机）

### Step 5：改造 profile.wxss（加 city badge + 槽位 placeholder 样式）

- [ ] **5.1** 加 `.city-badge` 样式（圆角小标签 / 主色 #FF2D55 / 字号 11px）
- [ ] **5.2** 加 `.power-curve-slot` / `.heatmap-slot` 容器样式（最小高度 200rpx / 内置 placeholder 居中）
- [ ] **5.3** 加 `.slot-placeholder` 文案样式（灰色 / 字号 13px）

### Step 6：手工回归（在微信开发者工具）

- [ ] **6.1** 跑 5 项手工 checklist（Step 2.1）
- [ ] **6.2** 真机预览（扫码 / iOS + Android 各 1 台）
- [ ] **6.3** 检查 profile.wxml 行数 ≤ 300（黄灯阈值）

### Step 7：双审 + Codex 异源审

- [ ] **7.1** Claude A 忠 spec 审：核对 §6 PRD 任务卡 vs 实现（5 区块 / city fallback / 2 槽位 placeholder / 不破现有）
- [ ] **7.2** Claude B 集成审：检查跟现有 home / detail / notification 等页面无破坏（grep `pages/profile` 引用）
- [ ] **7.3** Codex 异源审（调 `codex:codex-rescue` subagent / prompt 按 `agent-collaboration.md §4 场景 B`）
- [ ] **7.4** 三审 Critical/Important 全收敛后才 commit

### Step 8：commit

- [ ] **8.1** 

```bash
git add miniprogram/pages/profile/
git commit -m "feat(miniprogram): 任务4.1 个人页框架改造（5 区块 + city badge fallback + 2 槽位 placeholder）

- profile.wxml 拆 5 区块（用户信息名片 + 累计 + 2 功能槽位 + 导航）
- city 自动渲染 fallback（D9 / 有值显示 / 无值不显示 / 不弹引导）
- 占位 fetchPowerCurve / fetchHeatmap（4.2 task 替换为真实调用）
- 行为完全保持：登录 / 累计 / 跳转 / 退出登录

来源：phase-4-prd.md §6 / D4 + D9
Sprint: sprint-frontend 批 1 第一步（独立 ship 验证稳定）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## ✅ 自检三问（commit 前必答）

1. **profile.wxml 5 区块结构清晰？** 5 个 `<view class="card">` 各自独立 / 不相互依赖布局 / 拆 component 容易？
2. **city badge fallback 严格遵守 D9？** profile.city = null / "unknown" / "" 三种 case 都不显示 badge / 不弹引导？
3. **现有 5 项行为零破坏？** 手工跑了未登录 / 已登录 / city 有值 / city 无值 / 跳转 5 项？

任一不满意 → 不交付 / 报 Tim。

---

## ⚠️ 红线（违反 = 直接 reject）

- ❌ 在本 task 实现功率曲线 / 热力图真显示（必须留 4.2）
- ❌ 在本 task 调用 me/power-curve / me/heatmap endpoint
- ❌ 修改 onShow 主流程导致登录态 / fetchUserData 顺序变化
- ❌ city 无值时显示"未设置"或弹引导设置（D9 明确禁止）

---

**END task-4.1**
