# 任务 4.3：用户详情页新建（批 1 看他人 / 含前置后端补 2 endpoint）

> **批 1 第三步**——4.1 框架 ship 后可启动。**先做前置后端补 endpoint（4.3.0）**，再做小程序新页（4.3.1）。

---

## 🎯 目标（一句话）

新建小程序"看他人"用户详情页 `pages/user/`，从动态 / 通知中心点击骑友头像跳进。展示对方头像 / 昵称 / city / 累计 / 功率曲线 / 热力图，**严格隐私白名单**（看不到手机 / openid / Strava token / FTP / 体重 / W·kg）。

前置补 2 个后端 endpoint：`GET /api/user/{user_id}/power-curve` + `/api/user/{user_id}/heatmap`。

---

## ⛓ 前置依赖

- task-4.1 已 ship（个人页框架已就位 / city badge fallback 逻辑可复用）
- v5 Sprint 2 后端 `GET /api/user/{user_id}/profile` 已 ship（D-P08 严格白名单）

## 📥 输入契约

- 现有 `GET /api/user/{user_id}/profile`（白名单字段：id / nickname / city / 累计统计等）
- service 层 `get_user_power_curve(db, user_id, period)` 和 `get_user_heatmap(db, user_id, city)` 已支持任意 user_id 参数（v5 Sprint 2 实现）

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| 后端 `GET /api/user/{user_id}/power-curve` endpoint | 看他人功率曲线 |
| 后端 `GET /api/user/{user_id}/heatmap` endpoint | 看他人热力图 |
| 小程序 `pages/user/` 完整页面 | 用户详情独立页 |
| home / notification 头像点击跳转改向 user/[id] | 入口接通 |

---

## 🧱 现状清单（subagent 必先 grep + Read 验证）

| 项 | grep 命令 | 期望结果 |
|---|---|---|
| 后端 user_id profile endpoint | `grep -n "user_id.*profile\|{user_id}/profile" app/user/router.py` | 应见 line 193 |
| service 层是否支持任意 user_id | `grep -n "def get_user_power_curve\|def get_user_heatmap" app/user/service.py` | 应见两个函数签名第一参 db / 第二参 user_id |
| FastAPI 路由匹配优先级 | `grep -n "/me/.*静态\|静态路径.*优先" app/user/router.py` | 应见 line 123 注释说明 |
| 现有头像点击跳转 | `grep -rn "navigator.*user\|navigateTo.*user" miniprogram/pages/home/ miniprogram/pages/notification/` | 当前可能直接展示无跳转 / 需要新加 |

---

## 🛠 操作步骤

### 4.3.0 前置后端任务（必须先做 / 工作量 < 60 行 + 8 单测）

#### Step 0.1 - 加 2 个 endpoint 到 user/router.py

- [ ] **0.1.1** Read `app/user/router.py` 现状（特别是 line 121-155 的 me/power-curve + me/heatmap 实现作参考）
- [ ] **0.1.2** 在 `/me/heatmap` endpoint 之后（约 line 156 处）追加：

```python
@router.get("/{user_id}/power-curve", response_model=schemas.PowerCurveResponse)
def get_user_power_curve_for_others(
    user_id: int,
    period: schemas.PowerCurvePeriod = schemas.PowerCurvePeriod.last_30_days,
    requester_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """看他人功率曲线

    权限：任意登录用户（D-P08 / 看他人主页默认公开）
    路由匹配：FastAPI /me/... 静态路径优先 / 本动态路径 /{user_id}/... 后置不冲突
    user 不存在 → service.get_user_by_id 抛 ValueError → 翻 404
    （跟 router.py L220-223 /{user_id}/profile 同 pattern）
    """
    try:
        service.get_user_by_id(db, user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return service.get_user_power_curve(db, user_id, period.value)


@router.get("/{user_id}/heatmap", response_model=schemas.HeatmapResponse)
def get_user_heatmap_for_others(
    user_id: int,
    city: schemas.UserCity | None = None,  # D30 v3 polish 改可选 / 跟 /me/heatmap 同款
    requester_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """看他人热力图（同上，权限 + 路由匹配 + 404 翻译说明）

    city 可选（D30）：不传 = 看 ta 全部足迹 / 传 = 按城市筛。
    跟 /me/heatmap 写法一致（详 router.py L144-164 / schemas.py L156-166）。
    """
    try:
        service.get_user_by_id(db, user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return service.get_user_heatmap(db, user_id, city.value if city else None)
```

> **关键 pattern 说明**：`service.get_user_by_id`（service.py L133-141）找不到 user 时**抛 ValueError 不返 None**。所以必须 try/except / 不能写 `if user is None` 判断（永远不触发 → 真路径 500）。Sprint 4 task-4.3.0 Claude 综合审 Critical-1 已抓此盲区。

#### Step 0.2 - 写测试

- [ ] **0.2.1** 在 `tests/test_user_router_v5.py` 加 8 个 case：
  - power-curve：看他人（200 / 数据齐）/ 404 不存在用户 / 401 未登录 / 看自己用 user_id 路径（200 / 验证不撞 /me/）
  - heatmap：看他人**不传 city**（200 / 全部足迹 / D30）/ 看他人传 city（200 / 按城市筛）/ 404 / 401

#### Step 0.3 - 跑测试

- [ ] **0.3.1** `pytest tests/test_user_router_v5.py -v -k "power_curve or heatmap"`
- [ ] **0.3.2** 期望全 passed（含原有 me/... 测试 + 新增 8 个）

#### Step 0.4 - 双审 + Codex 异源审 + commit（后端独立 commit）

- [ ] **0.4.1** Claude 双审 + Codex 异源审（小改动可能跳过 Codex / 但需写 commit message 理由）
- [ ] **0.4.2** commit：

```bash
git add app/user/router.py tests/test_user_router_v5.py
git commit -m "feat(user): 任务4.3.0 加看他人 power-curve + heatmap endpoint

- GET /api/user/{user_id}/power-curve（任意登录用户）
- GET /api/user/{user_id}/heatmap（任意登录用户）
- 复用 service.get_user_power_curve / get_user_heatmap（已支持 user_id 参数）
- 路由匹配 /me/... 静态路径优先（不跟动态 /{user_id}/... 冲突）
- 8 单测覆盖（自己 / 他人 / 404 / 401 各 2）

来源：phase-4-prd.md §8 前置后端任务
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### 4.3.1 小程序新建用户详情页

#### Step 1.1 - 创建 pages/user/ 目录

- [ ] **1.1.1** mkdir `miniprogram/pages/user/`
- [ ] **1.1.2** 创建 4 个文件：user.wxml / user.js / user.wxss / user.json

#### Step 1.2 - 注册到 app.json

- [ ] **1.2.1** `miniprogram/app.json` pages 数组追加 `"pages/user/user"`（**不在 tabBar**）

#### Step 1.3 - 实现 user.wxml（仿 profile.wxml 但只读 + 去敏感字段）

- [ ] **1.3.1** 结构：

```xml
<!-- 加载中 -->
<view wx:if="{{loading}}" class="loading">加载中...</view>

<!-- 404 -->
<view wx:elif="{{notFound}}" class="error-page">
  <text>用户不存在</text>
  <view class="btn" bindtap="goBack">返回</view>
</view>

<!-- 数据 -->
<view wx:else>
  <!-- 用户信息名片（只读 / 不显示 FTP / 体重 / W·kg） -->
  <view class="user-card card">
    <view class="user-header">
      <view class="avatar"><text class="avatar-text">{{...}}</text></view>
      <view class="user-info">
        <text class="user-name">{{profile.nickname}}</text>
        <text class="user-id">ID: {{profile.id}}</text>
      </view>
      <view class="city-badge" wx:if="{{profile.city && profile.city !== 'unknown'}}">
        <text>{{cityLabel}}</text>
      </view>
    </view>
  </view>

  <!-- 累计骑行（只读） -->
  <view class="stats-card card">
    <text class="stats-title">累计骑行</text>
    <!-- 总里程 / 总次数 / 总爬升 -->
  </view>

  <!-- 功率曲线（看 ta 的 / D21 component 复用 / 内部 props.userId !== 0 自动切到 /api/user/{userId}/power-curve）-->
  <power-curve-card userId="{{userId}}" />

  <!-- 骑行热力图（看 ta 的 / D21 component 复用 / 内部 props.userId !== 0 自动切到 /api/user/{userId}/heatmap / city 不传走全部足迹 D30）-->
  <heatmap-card userId="{{userId}}" />

  <!-- ❌ 不展示：导航卡片(我的荣誉 / 设置) / FTP / 体重 / W·kg -->
</view>
```

**对应 user.json**（usingComponents 注册 / D21）：

```json
{
  "usingComponents": {
    "power-curve-card": "/components/power-curve-card/power-curve-card",
    "heatmap-card": "/components/heatmap-card/heatmap-card"
  }
}
```

> **D21 + D29 component 化哲学**：4.3 不重写功率曲线 / 热力图渲染逻辑。component 已建好（357 + 313 行 / 见 `miniprogram/components/power-curve-card/` 和 `heatmap-card/`），props.userId 分流逻辑也写好了（详 power-curve-card.js L70-180 / heatmap-card.js L52-114 注释明确写"task-4.3 才补 endpoint"）。本 task 只补后端 endpoint + page 引入 component 即生效。

#### Step 1.4 - 实现 user.js

- [ ] **1.4.1** onLoad 接受 query `?id=xxx`：

```js
onLoad(options) {
  const userId = parseInt(options.id, 10)
  if (!userId || isNaN(userId)) {
    wx.showToast({ title: '无效用户', icon: 'none' })
    setTimeout(() => wx.navigateBack(), 1500)
    return
  }
  
  // 看自己 → 直接跳到个人 tab（避免双视图混淆）
  const app = getApp()
  if (app.globalData.token && this.isMyId(userId)) {
    wx.switchTab({ url: '/pages/profile/profile' })
    return
  }
  
  this.setData({ userId, loading: true })
  this.fetchAllData(userId)
}
```

- [ ] **1.4.2** 加 fetchProfile（D21：page 只拉 profile / power-curve+heatmap 由 component 自带数据流）：

```js
async fetchProfile(userId) {
  try {
    const profile = await api.getUserProfile(userId)
    // city label 转换（沿用 4.1 同款 CITY_LABELS / 抽到 utils/city.js — 起手 grep 确认 4.1 现状）
    const cityLabel = CITY_LABELS[profile.city] || ''
    this.setData({ profile, cityLabel, loading: false })
    // power-curve / heatmap 不在这拉 — component 内部基于 props.userId 自动 fetch（D21 自治数据流）
    // 互不影响：profile 失败 → 全页错误 / power-curve 失败 → 该卡片自己显示加载失败 / heatmap 同
  } catch (e) {
    if (e.statusCode === 404) {
      this.setData({ notFound: true, loading: false })
    } else {
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false })
    }
  }
}
```

> **isMyId 实现**：`app.globalData.userId` 是登录后存的自己 user_id（subagent 起手 grep `globalData.userId\|globalData.user_id` 确认字段名 / 不脑补）。比较：`if (app.globalData.userId && app.globalData.userId === userId) { switchTab(...) }`。

#### Step 1.5 - 加 utils/api.js 1 个新方法

- [ ] **1.5.1** `utils/api.js` 加 `getUserProfile(userId)` 一个方法（GET `/api/user/{userId}/profile`）
- [ ] **1.5.2** ❌ 不需要加 `getUserPowerCurve` / `getUserHeatmap`：component 内部直接 wx.request 调（详 `power-curve-card.js` L175-185 / `heatmap-card.js` L107-115）

#### Step 1.6 - CITY_LABELS 公共常量处理（subagent 起手核实）

- [ ] **1.6.1** **先 grep**：`grep -rn "CITY_LABELS\|cityLabels" miniprogram/` 看现有定义在哪几处
- [ ] **1.6.2** 如果 4.1 profile.js 内联了 CITY_LABELS → 抽 `miniprogram/utils/city.js` + 同步改 4.1 引用
- [ ] **1.6.3** 如果 4.1 已用别的公共方案（如 settings.js / app.js / 已有 utils）→ 复用现有，不新建
- [ ] **1.6.4** 如果完全没定义 → 新建 utils/city.js + 4.3 直接用

#### Step 1.7 - 接入头像点击跳转

- [ ] **1.7.1** grep 全代码 `bindtap.*avatar` 找现有头像点击：

```bash
grep -rn "avatar\|head" miniprogram/pages/home/ miniprogram/pages/notification/
```

- [ ] **1.7.2** home 动态 / notification 通知里的骑友头像加 `bindtap="goUserDetail"` data-id="{{item.user_id}}"
- [ ] **1.7.3** 各页面加 `goUserDetail(e)` 方法 → `wx.navigateTo({ url: '/pages/user/user?id=' + e.currentTarget.dataset.id })`

#### Step 1.8 - 手工回归

- [ ] **1.8.1** 真机：
  - 进 home 点 CCF 头像 → 跳到 CCF 详情页
  - 看到 CCF 的 profile + 功率曲线 + 热力图
  - 看不到 CCF 的 FTP / 体重 / 手机号
  - 点不存在用户 ID → 显示"用户不存在" + 返回
  - 点自己头像 → 跳到个人 tab

#### Step 1.9 - 双审 + Codex + commit

- [ ] **1.9.1** Claude 双审 + Codex 异源审（重点关注隐私白名单 / D-P08）
- [ ] **1.9.2** commit：

```bash
git add miniprogram/pages/user/ miniprogram/utils/ miniprogram/app.json \
        miniprogram/pages/home/ miniprogram/pages/notification/
git commit -m "feat(miniprogram): 任务4.3.1 用户详情页新建 + 头像跳转接入

- 新建 pages/user/（注册 app.json pages / 不在 tabBar）
- 隐私白名单（D-P08）：不显示 FTP / 体重 / W·kg / 我的荣誉 / 设置
- 4 状态：loading / 404 / 数据齐 / 看自己跳个人 tab
- utils/city.js 抽公共 CITY_LABELS（4.1 + 4.3 复用）
- home + notification 头像点击跳转改向 /pages/user/user?id=...
- 真机回归 5 path 全过

来源：phase-4-prd.md §8 / 4.3.1
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## ✅ 自检三问

1. **D-P08 隐私白名单严格执行？** 后端返回的字段全是公开字段 / 前端展示也只展示公开字段 / 看他人时尝试拼接 GET /api/user/me 拿不到敏感数据？
2. **看自己 → 跳个人 tab 逻辑对？** 避免双视图混淆 / 不出现"个人 tab + 用户详情页同时显示自己"的奇怪体验？
3. **3 个 fetch 失败独立？** profile 失败 → 全页错误 / power-curve 失败 → 该 section 显示加载失败 / heatmap 失败 → 同上 / 互不影响？

---

## ⚠️ 红线

- ❌ 后端 endpoint 不加 user 存在性校验（404 必须显式抛出）
- ❌ 前端展示 FTP / 体重 / W·kg / 任何敏感字段（D-P08）
- ❌ 后端 endpoint 写在 `/me/...` 静态路径**之前**（FastAPI 路由顺序问题）
- ❌ utils/city.js 跟 4.1 的 profile.js 内联 CITY_LABELS 常量重复（必须抽公共）

---

**END task-4.3**
