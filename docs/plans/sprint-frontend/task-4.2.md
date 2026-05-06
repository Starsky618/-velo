# 任务 4.2：个人页内容塞入（批 1 内容 / 2 个 subagent 并行）

> **批 1 第二步**——4.1 框架 ship 后，4.2 把功率曲线 / 热力图真实显示塞进 4.1 留的 2 个槽位。**4.2.A 和 4.2.B 互不依赖，可以 2 个 subagent 并行**。

---

## 🎯 目标（一句话）

把 4.1 留的"功率曲线"+"热力图"两个槽位 placeholder 替换为真实数据渲染，调用 v5 Sprint 2 已 ship 的 `GET /api/user/me/power-curve` 和 `GET /api/user/me/heatmap` endpoint。

---

## ⛓ 前置依赖

- **task-4.1 已 ship**（profile 5 区块结构 + 2 槽位 placeholder + 占位 fetch 方法已就位）
- v5 Sprint 2 后端 endpoint 已 ship（`/api/user/me/power-curve` + `/api/user/me/heatmap`）

## 📥 输入契约

继承 4.1 的 profile.js / profile.wxml / profile.wxss 5 区块结构。

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| 功率曲线 canvas 渲染（4 段进步线 / 5s/30s/5min/1h）| 用户进个人页看见自己功率进步 |
| 热力图 map 渲染（用户全部历史骑行密度 / D13）| 用户看见自己骑过的区域 |
| utils/api.js 加 getMyPowerCurve / getMyHeatmap 方法 | 4.3 看他人 power-curve/heatmap 复用同结构 |

---

## 🧱 现状清单（subagent 必先 grep + Read 验证）

| 项 | grep 命令 | 期望结果 |
|---|---|---|
| utils/api.js 现有方法 | `grep -n "module.exports\|exports\." miniprogram/utils/api.js` | 应见现有 login / getProfile / getStats 等 |
| 后端 power-curve endpoint | `grep -n "me/power-curve" app/user/router.py` | 应见 line 126 `@router.get("/me/power-curve")` |
| 后端 heatmap endpoint | `grep -n "me/heatmap" app/user/router.py` | 应见 line 141 `@router.get("/me/heatmap")` |
| power-curve schema | `grep -n "PowerCurveResponse" app/user/schemas.py` | 字段：interval / max_power / created_at 等 |
| heatmap schema | `grep -n "HeatmapResponse" app/user/schemas.py` | 字段：grids / count / lat / lng 等 |
| 现有 canvas 用法参考 | `grep -rn "type=\"2d\"\|wx.createSelectorQuery" miniprogram/pages/detail/` | detail 页有 echart-canvas 样例可仿 |

**任一不符** → 停下报 Tim。

---

## 🛠 操作步骤

可拆 **2 个 subagent 并行**（A 功率曲线 + B 热力图）。两边独立 commit。

---

### 4.2.A 功率曲线 subagent

#### Step A.1 - 加 API 方法

- [ ] **A.1.1** 改 `miniprogram/utils/api.js` 加：

```js
// 我的功率曲线 / period: last3months(默认) / last6months / all
function getMyPowerCurve(period = 'last3months') {
  return request({
    url: `/api/user/me/power-curve?period=${period}`,
    method: 'GET'
  })
}
exports.getMyPowerCurve = getMyPowerCurve
```

#### Step A.2 - 改 profile.js fetchPowerCurve 真实实现

- [ ] **A.2.1** 替换占位方法：

```js
async fetchPowerCurve() {
  try {
    const data = await api.getMyPowerCurve('last3months')
    this.setData({ powerCurveData: data, powerCurveLoading: false })
  } catch (e) {
    console.error('fetchPowerCurve fail', e)
    this.setData({ powerCurveError: true, powerCurveLoading: false })
  }
}
```

- [ ] **A.2.2** onShow 在登录态触发 `this.fetchPowerCurve()`（独立 await / 不阻塞 fetchUserData）

#### Step A.3 - 改 profile.wxml 槽位接 canvas

- [ ] **A.3.1** 替换"功率曲线槽位 placeholder"为：

```xml
<view class="card power-curve-card">
  <text class="card-title">功率曲线</text>
  <text class="subtitle">最近 3 个月 / 5s · 30s · 5min · 1h 进步</text>

  <!-- loading -->
  <view wx:if="{{powerCurveLoading}}" class="loading-mini">加载中...</view>

  <!-- error -->
  <view wx:elif="{{powerCurveError}}" class="error-mini" bindtap="fetchPowerCurve">
    加载失败 · 点击重试
  </view>

  <!-- 数据空 -->
  <view wx:elif="{{!powerCurveData || powerCurveData.length === 0}}" class="empty-mini">
    还没数据，多骑几次就有了
  </view>

  <!-- canvas 容器 / 用 hidden 不用 wx:if（CLAUDE.md 陷阱 #17 + F1）-->
  <canvas type="2d" id="powerCurveCanvas" class="chart-canvas" hidden="{{!powerCurveData}}"></canvas>
</view>
```

#### Step A.4 - 渲染 canvas（参 detail 页 echart-canvas 模式）

- [ ] **A.4.1** profile.js 加 `renderPowerCurveCanvas()` 方法
- [ ] **A.4.2** 在 setData powerCurveData 的 callback 里用 `setTimeout(fn, 100)` 触发 render（**F1 陷阱**）
- [ ] **A.4.3** 渲染 4 条线（5s / 30s / 5min / 1h）

#### Step A.5 - 手工回归

- [ ] **A.5.1** 真机预览（iOS + Android 各 1 台）：
  - Tim 自己账号能看到 4 段折线
  - 数据空账号显示"还没数据"
  - 网络断开显示"加载失败 · 点击重试"

#### Step A.6 - 双审 + Codex 审 + commit

- [ ] **A.6.1** Claude 双审 + Codex 异源审（同 4.1 Step 7）
- [ ] **A.6.2** commit：

```bash
git add miniprogram/pages/profile/ miniprogram/utils/api.js
git commit -m "feat(miniprogram): 任务4.2.A 功率曲线接入个人页

- utils/api.js 加 getMyPowerCurve(period)
- profile.js fetchPowerCurve 替换为真实调用
- profile.wxml power-curve-card 4 状态（loading / error / empty / 渲染）
- canvas 用 hidden 不用 wx:if + setTimeout(100) 兜底（F1 陷阱）
- 渲染 4 条折线：5s / 30s / 5min / 1h 进步

来源：phase-4-prd.md §7 / 4.2.A
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### 4.2.B 热力图 subagent

#### Step B.1 - 加 API 方法

- [ ] **B.1.1** 改 `miniprogram/utils/api.js` 加：

```js
// 我的热力图 / city: auto(默认 / 自动用 profile.city) / 6 城枚举之一
function getMyHeatmap(city = 'auto') {
  return request({
    url: `/api/user/me/heatmap?city=${city}`,
    method: 'GET'
  })
}
exports.getMyHeatmap = getMyHeatmap
```

#### Step B.2 - 改 profile.js fetchHeatmap 真实实现（同 A.2 结构）

#### Step B.3 - 改 profile.wxml 槽位接 map（同 A.3 结构 / 但用 `<map>` 不是 `<canvas>`）

- [ ] **B.3.1** 决策：用小程序原生 `<map>` 组件 + markers（推荐 / 简单）vs 自定义 canvas 网格涂色（复杂）

推荐用 `<map>` + `markers`：

```xml
<view class="card heatmap-card">
  <text class="card-title">骑行热力图</text>
  <text class="subtitle">你骑过的全部区域 / 颜色越深 = 骑得越多</text>

  <view wx:if="{{heatmapLoading}}" class="loading-mini">加载中...</view>
  <view wx:elif="{{heatmapError}}" class="error-mini" bindtap="fetchHeatmap">加载失败 · 点击重试</view>
  <view wx:elif="{{!heatmapData || heatmapData.grids.length === 0}}" class="empty-mini">还没骑过任何路线</view>

  <map wx:else
       class="heatmap-map"
       latitude="{{heatmapCenter.lat}}"
       longitude="{{heatmapCenter.lng}}"
       markers="{{heatmapMarkers}}"
       scale="11"
       enable-rotate="{{false}}"
       enable-3D="{{false}}">
  </map>
</view>
```

#### Step B.4 - 数据转换 grid 为 markers

- [ ] **B.4.1** profile.js 加 `convertHeatmapToMarkers(grids)` 纯函数：
  - 按 count 排序 / count 越高 markers iconPath 颜色越深
  - 计算 center（grids 中位数）
- [ ] **B.4.2** 备 4 张 marker icon（grey / blue / orange / red）放 assets/icons/heatmap/

#### Step B.5 - 手工回归

- [ ] **B.5.1** 真机预览：
  - Tim 账号热力图显示北京区域
  - 数据空账号显示"还没骑过任何路线"
  - 网络断开显示重试

#### Step B.6 - 双审 + Codex + commit

- [ ] **B.6.1** 双审 + Codex 异源审
- [ ] **B.6.2** commit：

```bash
git add miniprogram/pages/profile/ miniprogram/utils/api.js miniprogram/assets/icons/heatmap/
git commit -m "feat(miniprogram): 任务4.2.B 热力图接入个人页

- utils/api.js 加 getMyHeatmap(city)
- profile.js fetchHeatmap + convertHeatmapToMarkers 纯函数
- profile.wxml heatmap-card 用 <map> + markers 实现
- 4 张 marker icon（grey/blue/orange/red 颜色密度梯度）
- 时间窗 = 全部历史（D13）

来源：phase-4-prd.md §7 / 4.2.B
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## ✅ 自检三问（每个 subagent commit 前必答）

1. **2 个槽位失败不互相影响？** 网络断开时 A 失败不挡 B 渲染（互不依赖）？
2. **canvas / map 渲染稳定？** F1 陷阱 hidden + setTimeout(100) 落实？
3. **数据空 / 网络断 / 加载中状态都有友好文案？** 不出现白屏 / "undefined" / 错误堆栈？

---

## ⚠️ 红线

- ❌ A 和 B 共用同一个 fetch / Promise.all（独立失败原则）
- ❌ canvas 用 wx:if（必须 hidden）
- ❌ city 字段引导设置弹窗（D9）
- ❌ heatmap 时间窗用"半年内"（必须全部历史 / D13）

---

**END task-4.2**
