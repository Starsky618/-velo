# 任务 4.2：个人页内容塞入（批 1 内容 / 2 个 subagent 并行 / component 化）

> **批 1 第二步**——4.1 框架 ship 后，4.2 把功率曲线 / 热力图真实显示塞进 4.1 留的 2 个槽位。**4.2.A 和 4.2.B 互不依赖，可以 2 个 subagent 并行**。
>
> ---
>
> **task-4.2 v2 polish**（2026-05-08 / 真机回归后 polish / 跟 v1 同一 task / 不另开任务）：
> - **D26 power-curve 7 档**：`[0, 3, 30, 60, 300, 1200, 3600]`（0s 瞬时最大 + 3s/30s/1min/5min/20min/1h）替换原 6 档；前端折线图 7 个数据点连线（不再跳过 / 全部展示）
> - **D27 heatmap markers→polylines**：后端 schema multipoint→tracks（保留 activity 边界 list of list）；前端 `<map polyline>` 黄色 #FFD700 + 80% alpha / 多条重叠自然热力效果 / 视觉接近 ride.fitcard.app 80%；删 4 张 PNG marker icon
> - **D28 修订**：未来地图 tab 用高德地图（不是 Leaflet+OSM / 测绘法合规要求）/ Sprint 5/6 实施 / 当前 task-4.2 v2 仍用腾讯地图 polyline 撑过
> - **D29 双 component 路线**：当前 `heatmap-card`（小卡片 / 腾讯 native）+ 未来 `heatmap-fullscreen-card`（全屏 / 高德 webview）/ 共享 props 接口 / 内部渲染各自最优
>
> ---
>
> **task-pre-4.2 已升级**（2026-05-08）：
> 1. 后端 power-curve period 改滚动窗口（5 档：`last_30_days / last_90_days / last_180_days / last_365_days / all_time`，default `last_30_days`）
> 2. **component 化方向**（D21 决策 / 模块化哲学）：本任务建 `power-curve-card` + `heatmap-card` 两个独立 component / profile.wxml 一行引入 / **未来地图 tab 上线**：`<heatmap-card />` 整体复制过去 = 0 拆代码 / **task-4.3 看他人 profile 复用**：用 `<power-curve-card userId="42" />` 一行引入 + component 内部分流（`userId !== 0` 调 task-4.3 新加的 `api.getUserPowerCurve(userId, period)`）= 少量 API 分支不动 wxml/wxss

---

## 🎯 目标（一句话）

把 4.1 留的"功率曲线"+"热力图"两个槽位 placeholder 替换为**两个独立 component**（`power-curve-card` + `heatmap-card`）的真实数据渲染，调用 v5 Sprint 2 已 ship 的 `GET /api/user/me/power-curve` 和 `GET /api/user/me/heatmap` endpoint。

---

## ⛓ 前置依赖

- **task-4.1 已 ship**（profile 5 区块结构 + 2 槽位 placeholder + 占位 fetch 方法已就位 / commit `1fd0c43`）
- **task-pre-4.2 已 ship**（后端 period 改滚动窗口 + 文档 4 处同步）
- v5 Sprint 2 后端 endpoint 已 ship（`/api/user/me/power-curve` + `/api/user/me/heatmap`）

## 📥 输入契约

继承 4.1 的 profile.js / profile.wxml / profile.wxss 5 区块结构 + 占位 `fetchPowerCurve` / `fetchHeatmap` 方法。

## 📤 输出契约（4.3 / 未来地图 tab 依赖）

| 产出 | 用途 | 被谁依赖 |
|------|------|---------|
| `miniprogram/components/power-curve-card/` 独立 component（4 文件 / wxml + wxss + js + json）| 4.3 看他人 power-curve 直接复用 / 未来想搬别处也方便 | 4.3 / 未来 |
| `miniprogram/components/heatmap-card/` 独立 component（4 文件）| 4.3 看他人 heatmap 直接复用 / 未来地图 tab 上线时整个搬过去 | 4.3 / 未来地图 tab |
| **utils/api.js 不加 wrapper**（component 内部直接 `api.get(url)` + `userId !== 0` 分流 / 详 Step A.1+B.1）| 4.3 看他人时 component 内部分流即可 | 4.3 |
| profile.wxml + profile.json 引入 2 component（一行 `<power-curve-card />` / `<heatmap-card />`）| 个人页真实展示 | profile |

### Component props 设计（4.3 复用关键）

**`<power-curve-card>`**：
- `userId`：number / 默认 0（看自己 / 调 `/api/user/me/power-curve`）/ 非 0 = 看他人（4.3 时调 `/api/user/{userId}/power-curve` / 该 endpoint 4.3 前置后端补）
- `period`：string / 默认 `last_30_days` / 可选 5 档（`last_30_days / last_90_days / last_180_days / last_365_days / all_time`）

**`<heatmap-card>`**：
- `userId`：number / 默认 0（看自己）/ 非 0 看他人
- `city`：string / 可选 / 默认用 component 内部读取调用方 profile.city（fallback `unknown`）

---

## 🧱 现状清单（subagent 必先 grep + Read 验证）

| 项 | grep 命令 | 期望结果 |
|---|---|---|
| utils/api.js 现有方法 | `grep -n "module.exports\|exports\." miniprogram/utils/api.js` | 应见现有 login / getProfile / getStats 等 |
| 后端 power-curve endpoint | `grep -n "me/power-curve" app/user/router.py` | 应见 `@router.get("/me/power-curve")` + `period: schemas.PowerCurvePeriod = schemas.PowerCurvePeriod.last_30_days`（task-pre-4.2 升级） |
| 后端 heatmap endpoint | `grep -n "me/heatmap" app/user/router.py` | 应见 `@router.get("/me/heatmap")` + `city: schemas.UserCity` 必填 |
| power-curve schema | `grep -n "PowerCurveResponse\|PowerCurvePeriod" app/user/schemas.py` | period 5 档 `last_30_days / last_90_days / last_180_days / last_365_days / all_time` |
| heatmap schema | `grep -n "HeatmapResponse" app/user/schemas.py` | 字段：city / tracks（list of list / D27 v2 polish）/ activity_count |
| 现有 component 用法参考 | `ls miniprogram/components/ 2>/dev/null` | 当前可能没有 components 目录 / 4.2 是首批 component |
| 现有 canvas 用法参考 | `grep -rn "type=\"2d\"\|wx.createSelectorQuery" miniprogram/pages/detail/` | detail 页有 echart-canvas 样例可仿 |

**任一不符** → 停下报 Tim。

---

## 🛠 操作步骤

可拆 **2 个 subagent 并行**（A 功率曲线 + B 热力图）。两边独立 commit。

---

### 4.2.A 功率曲线 subagent

#### Step A.1 — API 调用方式（实际 ship 时已接受 direct `api.get` / 不加 wrapper）

> **2026-05-08 ship 时决策**：原 task 卡说"在 utils/api.js 加 getMyPowerCurve(period) 封装方法"，实际 component 内部直接调 `api.get(url)`，不加 wrapper。理由：(1) component 已用 `userId !== 0` 内部分流 self vs other 路径 / wrapper 没有去重价值；(2) 加 wrapper = 多一层抽象，违背 D21 "组件自治"哲学；(3) Codex 异源审 A1 advisory 接受。

component 内部直接调用：
```js
// component 内
const api = require('../../utils/api')
const url = this.data.userId === 0
  ? '/api/user/me/power-curve?period=' + this.data.period
  : '/api/user/' + this.data.userId + '/power-curve?period=' + this.data.period
api.get(url)
```

#### Step A.2 — 建 `power-curve-card` component（D21 模块化）

- [ ] **A.2.1** 新建 4 文件：
  - `miniprogram/components/power-curve-card/power-curve-card.json` — 含 `"component": true`
  - `miniprogram/components/power-curve-card/power-curve-card.js` — 含 props（userId / period）+ attached 触发 fetch + canvas 渲染
  - `miniprogram/components/power-curve-card/power-curve-card.wxml` — 4 状态（loading / error / empty / 渲染）+ canvas
  - `miniprogram/components/power-curve-card/power-curve-card.wxss` — card 样式

- [ ] **A.2.2** component js properties 定义：

```js
properties: {
  userId: { type: Number, value: 0 },        // 0 = 看自己 / 非 0 = 看他人（4.3 用 / 内部分流到不同 endpoint）
  period: { type: String, value: 'last_30_days' }  // 5 档可选
}
```

- [ ] **A.2.3** component lifetimes 在 attached 时触发 fetch（不在 page onShow 触发 / component 自治）：

```js
lifetimes: {
  attached() {
    this._fetchAndRender()
  }
}
```

- [ ] **A.2.4** `_fetchAndRender` 内部走分支（直接 `api.get` 拼 URL / 不走 wrapper）：
  - `userId === 0` → `api.get('/api/user/me/power-curve?period=' + period)`
  - `userId !== 0` → `api.get('/api/user/' + userId + '/power-curve?period=' + period)`（4.3 才补此 endpoint）

#### Step A.3 — wxml 4 状态 + canvas（用 hidden 不用 wx:if / F1 陷阱）

- [ ] **A.3.1** `power-curve-card.wxml`（D26 v2 polish 7 档展示）：

```xml
<view class="card power-curve-card">
  <text class="card-title">功率曲线</text>
  <text class="subtitle">最近 30 天 · 瞬时 / 3s / 30s / 1min / 5min / 20min / 1h</text>

  <view wx:if="{{loading}}" class="loading-mini">加载中...</view>
  <view wx:elif="{{error}}" class="error-mini" bindtap="_retryFetch">加载失败 · 点击重试</view>
  <view wx:elif="{{isEmpty}}" class="empty-mini">还没数据，多骑几次就有了</view>

  <!-- canvas 用 hidden 不用 wx:if（CLAUDE.md 陷阱 #17 + F1）-->
  <canvas type="2d" id="powerCurveCanvas" class="chart-canvas" hidden="{{loading || error || isEmpty}}"></canvas>
</view>
```

#### Step A.4 — 渲染 canvas（参 detail 页 echart-canvas 模式）

- [ ] **A.4.1** component js 加 `_renderCanvas()` 方法
- [ ] **A.4.2** 在 setData 数据 callback 里用 `setTimeout(fn, 100)` 触发 render（**F1 陷阱兜底**）
- [ ] **A.4.3** 渲染 1 条折线连 7 个点（瞬时 / 3s / 30s / 1min / 5min / 20min / 1h / D26 v2 polish）

#### Step A.5 — profile 引入 component

- [ ] **A.5.1** `miniprogram/pages/profile/profile.json` 加：

```json
{
  "navigationBarTitleText": "我的",
  "usingComponents": {
    "power-curve-card": "/components/power-curve-card/power-curve-card"
  }
}
```

- [ ] **A.5.2** `profile.wxml` 把"功率曲线槽位 placeholder"替换为 `<power-curve-card />`（不传 props 全用默认 / userId=0 看自己 / period=last_30_days）

- [ ] **A.5.3** `profile.js` 删除 `fetchPowerCurve` 占位方法（component 自治触发 fetch / page 不再管 power-curve 数据流）

#### Step A.6 — 手工回归

- [ ] **A.6.1** 真机预览（iOS + Android 各 1 台）：
  - Tim 自己账号能看到 4 段折线（最近 30 天数据）
  - 数据空账号显示"还没数据"
  - 网络断开显示"加载失败 · 点击重试"

#### Step A.7 — 双审 + Codex 异源审 + commit

- [ ] **A.7.1** Claude 双审 + Codex 异源审（同 4.1 Step 7）
- [ ] **A.7.2** commit：

```bash
git add miniprogram/components/power-curve-card/ miniprogram/pages/profile/ miniprogram/utils/api.js
git commit -m "feat(miniprogram): 任务4.2.A 功率曲线 component 化（D21 模块化）

- 新建 components/power-curve-card/（4 文件 / 自治 fetch + canvas 渲染）
- props 设计：userId（默认 0 看自己 / 非 0 看他人 / 4.3 复用）+ period（默认 last_30_days）
- utils/api.js 不动（component 内部直接 api.get(url) / 不加 wrapper）
- profile.json + profile.wxml 引入 component 一行 <power-curve-card />
- profile.js 删除 fetchPowerCurve 占位（component 自治）
- 4 状态（loading / error / empty / 渲染）/ canvas hidden + setTimeout(100) 兜底（F1）
- 渲染 4 条折线：5s / 30s / 5min / 1h 进步

来源：phase-4-prd.md §7 / 4.2.A / D21 component 化哲学
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### 4.2.B 热力图 subagent

#### Step B.1 — API 调用方式（同 Step A.1 / 不加 wrapper / 直接 `api.get(url)`）

component 内部直接调用：
```js
// component 内
const api = require('../../utils/api')
const cityToUse = this.data.city || 'unknown'
const url = this.data.userId === 0
  ? '/api/user/me/heatmap?city=' + cityToUse
  : '/api/user/' + this.data.userId + '/heatmap?city=' + cityToUse
api.get(url)
```

#### Step B.2 — 建 `heatmap-card` component（D21 模块化 / 未来地图 tab 整体搬过去）

- [ ] **B.2.1** 新建 4 文件：
  - `miniprogram/components/heatmap-card/heatmap-card.json`
  - `miniprogram/components/heatmap-card/heatmap-card.js`
  - `miniprogram/components/heatmap-card/heatmap-card.wxml`
  - `miniprogram/components/heatmap-card/heatmap-card.wxss`

- [ ] **B.2.2** component js properties：

```js
properties: {
  userId: { type: Number, value: 0 },     // 0 = 看自己 / 非 0 = 看他人
  city: { type: String, value: '' }       // '' = component 内部从 profile 读 fallback unknown
}
```

- [ ] **B.2.3** component attached 触发 fetch + 内部 tracks → polylines 转换（D27 v2 polish）

#### Step B.3 — wxml 4 状态 + map（D27 v2 polish / 用原生 `<map>` 组件 + polyline 路径线）

- [ ] **B.3.1** `heatmap-card.wxml`（D27 polyline 替代 markers）：

```xml
<view class="card heatmap-card">
  <text class="card-title">骑行热力图</text>
  <text class="subtitle">你骑过的全部区域</text>

  <view wx:if="{{loading}}" class="loading-mini">加载中...</view>
  <view wx:elif="{{error}}" class="error-mini" bindtap="_retryFetch">加载失败 · 点击重试</view>
  <view wx:elif="{{isEmpty}}" class="empty-mini">还没骑过任何路线</view>

  <map wx:else
       class="heatmap-map"
       latitude="{{center.lat}}"
       longitude="{{center.lng}}"
       polyline="{{polylines}}"
       scale="11"
       enable-rotate="{{false}}"
       enable-3D="{{false}}">
  </map>
</view>
```

#### Step B.4 — 数据转换 tracks 为 polylines（D27 v2 polish）

- [ ] **B.4.1** component js 加 `_convertToPolylines(tracks)` 纯函数：
  - 每个 activity 一条 polyline / 黄色 #FFD700CC（80% alpha）
  - width: 4 / 多条重叠时 opacity 自然叠加 → 骑得越多越亮（自然热力效果）
  - 跳过单点 activity（track.length < 2 / polyline 至少 2 点）
- [ ] **B.4.2** component js 加 `_computeCenter(tracks)` 纯函数：扁平所有点取经纬度均值 / 空时 fallback CITY_DEFAULT_CENTER（7 城映射）
- [ ] **B.4.3** **不需 marker icon 资源**（D27 改用 polyline / 不再用 markers / 删除 v1 时的 icons/ 目录）

#### Step B.5 — profile 引入 component

- [ ] **B.5.1** `miniprogram/pages/profile/profile.json` 加 `usingComponents.heatmap-card`
- [ ] **B.5.2** `profile.wxml` 把"骑行热力图槽位 placeholder"替换为 `<heatmap-card city="{{profile.city}}" />`（city 由 profile 拿 / component 内 fallback `unknown`）
- [ ] **B.5.3** `profile.js` 删除 `fetchHeatmap` 占位方法

#### Step B.6 — 手工回归

- [ ] **B.6.1** 真机预览：
  - Tim 账号热力图显示北京区域
  - 数据空账号显示"还没骑过任何路线"
  - 网络断开显示重试

#### Step B.7 — 双审 + Codex + commit

- [ ] **B.7.1** 双审 + Codex 异源审
- [ ] **B.7.2** commit：

```bash
git add miniprogram/components/heatmap-card/ miniprogram/pages/profile/ miniprogram/utils/api.js
git commit -m "feat(miniprogram): 任务4.2.B 热力图 component 化（D21 模块化 / 未来地图 tab 整搬）

- 新建 components/heatmap-card/（4 文件 + icons/ / 自治 fetch + grid→markers 转换）
- props 设计：userId（默认 0 看自己 / 非 0 看他人）+ city（'' = 内部 fallback unknown）
- utils/api.js 不动（component 内部直接 api.get(url) / 不加 wrapper）
- profile.json + profile.wxml 引入 <heatmap-card city='{{profile.city}}' />
- profile.js 删除 fetchHeatmap 占位
- 4 状态 + <map> + markers / 4 张 icon（grey/blue/orange/red 密度梯度）
- 时间窗 = 全部历史（D13）

来源：phase-4-prd.md §7 / 4.2.B / D21 component 化哲学
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## ✅ 自检三问（每个 subagent commit 前必答）

1. **2 个 component 完全独立？** 网络断开时 A 失败不挡 B 渲染（profile.js 不持有任何 power-curve / heatmap 数据 / 全在 component 内自治）？
2. **canvas / map 渲染稳定？** F1 陷阱 hidden + setTimeout(100) 落实？
3. **数据空 / 网络断 / 加载中状态都有友好文案？** 不出现白屏 / "undefined" / 错误堆栈？
4. **component props 设计真"4.3 可复用"？** userId=0 看自己 / userId=42 看他人，4.3 时改 endpoint 路径就够，不用动 component 内部逻辑？

---

## ⚠️ 红线

- ❌ profile.js 持有 power-curve / heatmap 数据（必须 component 内部自治）
- ❌ canvas 用 wx:if（必须 hidden）
- ❌ city 字段引导设置弹窗（D9）
- ❌ heatmap 时间窗用"半年内"（必须全部历史 / D13）
- ❌ component 把 icon 放 `miniprogram/assets/`（必须放 component 目录内 / D21 模块化 / 整搬时 icon 跟着走）

---

**END task-4.2**
