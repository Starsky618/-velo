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
    period: schemas.PeriodEnum = schemas.PeriodEnum.last3months,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """看他人功率曲线
    
    权限：任意登录用户（D-P08 / 看他人主页默认公开）
    路由匹配：FastAPI /me/... 静态路径优先匹配（line 123 注释），
    本动态路径 /{user_id}/... 不会跟 /me/power-curve 冲突
    """
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return service.get_user_power_curve(db, user_id, period.value)


@router.get("/{user_id}/heatmap", response_model=schemas.HeatmapResponse)
def get_user_heatmap_for_others(
    user_id: int,
    city: schemas.CityEnum = schemas.CityEnum.auto,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """看他人热力图（同上，权限 + 路由匹配说明）"""
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return service.get_user_heatmap(db, user_id, city.value)
```

#### Step 0.2 - 写测试

- [ ] **0.2.1** 在 `tests/test_user_router.py` 加 8 个 case：
  - 看自己 power-curve（200 / 数据齐）
  - 看他人 power-curve（200 / 数据齐）
  - 看不存在用户 power-curve（404）
  - 未登录看 power-curve（401）
  - 同上 4 个 case 给 heatmap

#### Step 0.3 - 跑测试

- [ ] **0.3.1** `pytest tests/test_user_router.py -v -k "power_curve or heatmap"`
- [ ] **0.3.2** 期望全 passed（含原有 me/... 测试 + 新增 8 个）

#### Step 0.4 - 双审 + Codex 异源审 + commit（后端独立 commit）

- [ ] **0.4.1** Claude 双审 + Codex 异源审（小改动可能跳过 Codex / 但需写 commit message 理由）
- [ ] **0.4.2** commit：

```bash
git add app/user/router.py tests/test_user_router.py
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

  <!-- 功率曲线（看 ta 的） -->
  <view class="card power-curve-card">
    <text class="card-title">功率曲线</text>
    <!-- 同 4.2.A 渲染逻辑 / 数据源 = getUserPowerCurve(userId) -->
  </view>

  <!-- 骑行热力图（看 ta 的） -->
  <view class="card heatmap-card">
    <text class="card-title">骑行热力图</text>
    <!-- 同 4.2.B 渲染逻辑 / 数据源 = getUserHeatmap(userId) -->
  </view>

  <!-- ❌ 不展示：导航卡片（我的荣誉 / 设置）-->
</view>
```

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

- [ ] **1.4.2** 加 fetchAllData 并行 3 个 endpoint：

```js
async fetchAllData(userId) {
  try {
    const [profile, powerCurve, heatmap] = await Promise.all([
      api.getUserProfile(userId),  // GET /api/user/{userId}/profile
      api.getUserPowerCurve(userId).catch(() => null),  // 失败不挡
      api.getUserHeatmap(userId).catch(() => null)
    ])
    // city label 转换（沿用 4.1 同款 CITY_LABELS 常量 / 抽到 utils/city.js）
    const cityLabel = CITY_LABELS[profile.city] || ''
    this.setData({ profile, cityLabel, powerCurveData: powerCurve, heatmapData: heatmap, loading: false })
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

#### Step 1.5 - 加 utils/api.js 3 个新方法

- [ ] **1.5.1** `getUserProfile(userId)` / `getUserPowerCurve(userId)` / `getUserHeatmap(userId)`

#### Step 1.6 - 抽 CITY_LABELS 到 utils/city.js（避免 4.1 / 4.3 重复）

- [ ] **1.6.1** 新建 `miniprogram/utils/city.js` export CITY_LABELS + getCityLabel(cityCode) 助手函数
- [ ] **1.6.2** 改 4.1 的 profile.js 改为 `require('../../utils/city')`

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
