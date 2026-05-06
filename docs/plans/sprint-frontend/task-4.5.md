# 任务 4.5：赛段详情页新建（批 2 独立页 / 4 区块）

> **批 2 第二步**——可与 4.4 并行。新建独立页 `pages/segment/`，从 explore 卡片点击进入，展示 4 个区块：第一屏 + AI 介绍 + 我的记录 + 全网排行榜 top 10。

---

## 🎯 目标（一句话）

新建小程序赛段详情独立页 `pages/segment/`，4 区块自上而下：①第一屏（海拔曲线 + 城市 + 坡度 + 4 数字 / 不展示难度 badge / D14）②AI 介绍（admin 审核过 / 50-100 字 / 展开收起）③我的记录（个人最佳 + 进步对比 / D7 改文案）④全网排行榜（top 10 + 我的排名 / D7 反转后展示）。

---

## ⛓ 前置依赖

- 批 1（task-4.1 + 4.2 + 4.3）已 ship + 真用 1 周
- task-4.4 explore tab 改造已开工（跳转入口 / 但 4.5 至少先有空架子让 4.4 能跳）

## 📥 输入契约

- 后端 `GET /api/segments/{id}`（已有 / 含 introduction）
- 后端 `GET /api/user/efforts?segment_id={id}`（已有 / 我在该赛段的成绩）
- 后端 `GET /api/segments/{id}/leaderboard?limit=10`（已有 / 全网 top 10 + 我的排名）

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| pages/segment/ 完整页面 | 赛段详情独立页 |
| 4 区块视觉沿用 v4 detail.wxml 海拔曲线同款 | 视觉一致性 |
| 跳转入口接通（explore 卡片 / detail "途经赛段" section） | 用户能进 |

---

## 🧱 现状清单

| 项 | grep 命令 | 期望结果 |
|---|---|---|
| 后端 segment detail | `grep -n "/{segment_id}\b" app/segment/router.py` | 应见 line 180 |
| 后端 leaderboard endpoint | `grep -n "leaderboard" app/segment/router.py` | 应见 line 197 |
| 后端 user efforts | `grep -n "efforts.*segment_id" app/segment/router.py` | 应见 user_effort_router 在 line 261 |
| LeaderboardResponse schema | `grep -n "LeaderboardResponse\|leaderboard.*top" app/segment/schemas.py` | 字段：top / my_rank 等 |
| v4 detail 海拔曲线参考 | `grep -n "elevation\|altitude" miniprogram/pages/detail/detail.wxml` | 应见 elevation-chart canvas 用法 |

---

## 🛠 操作步骤

### Step 1：创建目录 + 注册 app.json

- [ ] **1.1** mkdir `miniprogram/pages/segment/`
- [ ] **1.2** 创建 4 文件：segment.wxml / segment.js / segment.wxss / segment.json
- [ ] **1.3** `miniprogram/app.json` pages 数组追加 `"pages/segment/segment"`（**不在 tabBar**）
- [ ] **1.4** 先 commit 一个空架子（让 4.4 能跳转）：

```bash
git add miniprogram/pages/segment/ miniprogram/app.json
git commit -m "feat(miniprogram): 任务4.5 step 1 空架子 ship（让 4.4 能跳转）"
```

### Step 2：加 API 方法（utils/api.js）

- [ ] **2.1** 加 3 个方法：

```js
function getSegmentDetail(segmentId) {
  return request({ url: `/api/segments/${segmentId}`, method: 'GET' })
}
function getMySegmentEfforts(segmentId) {
  return request({ url: `/api/user/efforts?segment_id=${segmentId}`, method: 'GET' })
}
function getSegmentLeaderboard(segmentId, limit = 10) {
  return request({ url: `/api/segments/${segmentId}/leaderboard?limit=${limit}`, method: 'GET' })
}
exports.getSegmentDetail = getSegmentDetail
exports.getMySegmentEfforts = getMySegmentEfforts
exports.getSegmentLeaderboard = getSegmentLeaderboard
```

### Step 3：实现 segment.wxml 4 区块

- [ ] **3.1** 结构：

```xml
<view wx:if="{{loading}}" class="loading">加载中...</view>
<view wx:elif="{{notFound}}" class="error-page">
  <text>赛段不存在</text>
  <view class="btn" bindtap="goBack">返回</view>
</view>

<view wx:else>
  <!-- 区块 1：第一屏（海拔曲线 + 城市 + 坡度 + 4 数字 / D14 不展示难度 badge） -->
  <view class="card hero-card">
    <text class="seg-name">{{segment.name}}</text>
    <view class="seg-tags">
      <text class="city-tag" wx:if="{{cityLabel}}">{{cityLabel}}</text>
    </view>
    
    <!-- 海拔曲线 / 沿用 v4 detail.wxml 同款 echart-canvas 模式 -->
    <canvas type="2d" id="elevationCanvas" class="elevation-chart" hidden="{{!segment.elevation_profile}}"></canvas>
    
    <!-- 4 数字（距离 / 爬升 / 平均坡度 / 最大坡度） -->
    <view class="meta-grid">
      <view class="meta-item">
        <text class="value">{{segment.distance}}</text>
        <text class="label">km</text>
      </view>
      <view class="meta-item">
        <text class="value">{{segment.elevation_gain}}</text>
        <text class="label">m 爬升</text>
      </view>
      <view class="meta-item">
        <text class="value">{{segment.avg_gradient}}%</text>
        <text class="label">平均坡度</text>
      </view>
      <view class="meta-item">
        <text class="value">{{segment.max_gradient}}%</text>
        <text class="label">最大坡度</text>
      </view>
    </view>
  </view>

  <!-- 区块 2：AI 介绍 section -->
  <view class="card intro-card" wx:if="{{segment.introduction}}">
    <text class="card-title">关于这条赛段</text>
    <text class="intro-text {{introExpanded ? 'expanded' : ''}}">{{segment.introduction}}</text>
    <view class="expand-btn" wx:if="{{shouldShowExpand}}" bindtap="toggleIntro">
      <text>{{introExpanded ? '收起' : '展开'}}</text>
    </view>
  </view>
  <view class="card intro-card empty" wx:elif="{{segment.introduction === null}}">
    <text class="placeholder">暂无介绍</text>
  </view>

  <!-- 区块 3：我的记录 section（D7 文案 / 不叫 PB） -->
  <view class="card my-record-card">
    <text class="card-title">我的记录</text>
    
    <view wx:if="{{!isLoggedIn}}" class="login-hint">
      <text>登录后查看你的成绩</text>
      <view class="btn" bindtap="goLogin">微信登录</view>
    </view>
    
    <view wx:elif="{{!myEffort}}" class="empty-record">
      <text>还没骑过这条赛段，骑一次试试看</text>
    </view>
    
    <view wx:else class="record-content">
      <view class="record-main">
        <text class="record-time">{{myEffort.elapsed_timeFormatted}}</text>
        <text class="record-speed">{{myEffort.avg_speed}} km/h</text>
      </view>
      <text class="record-date">创下于 {{myEffort.created_atFormatted}}</text>
      <text class="record-progress" wx:if="{{progressText}}">你的进步：{{progressText}}</text>
    </view>
  </view>

  <!-- 区块 4：全网排行榜 section（D7 反转后展示）-->
  <view class="card leaderboard-card">
    <text class="card-title">全网排行榜</text>
    <text class="subtitle" wx:if="{{leaderboard.total_count}}">共 {{leaderboard.total_count}} 人骑过</text>
    
    <view wx:if="{{leaderboardError}}" class="error-mini" bindtap="fetchLeaderboard">
      排行榜加载失败 · 点击重试
    </view>
    
    <view wx:elif="{{!leaderboard.top || leaderboard.top.length === 0}}" class="empty-mini">
      还没人骑过这条赛段
    </view>
    
    <view wx:else class="leaderboard-list">
      <view class="leaderboard-row {{item.user_id === myUserId ? 'me' : ''}}"
            wx:for="{{leaderboard.top}}" wx:key="user_id">
        <text class="rank">{{index + 1}}</text>
        <text class="nickname">{{item.nickname}}</text>
        <text class="time">{{item.elapsed_timeFormatted}}</text>
      </view>
      
      <!-- 我的排名（独立行 / 即使在 top 10 之外也展示） -->
      <view class="my-rank-divider" wx:if="{{leaderboard.my_rank && leaderboard.my_rank > 10}}"></view>
      <view class="leaderboard-row me my-rank-row"
            wx:if="{{isLoggedIn && leaderboard.my_rank}}">
        <text class="rank">#{{leaderboard.my_rank}}</text>
        <text class="nickname">我</text>
        <text class="time">{{leaderboard.my_elapsed_timeFormatted}}</text>
      </view>
      <view class="login-hint-inline" wx:if="{{!isLoggedIn}}">
        <text>登录后查看你的排名</text>
      </view>
    </view>
  </view>
</view>
```

### Step 4：实现 segment.js

- [ ] **4.1** onLoad 接受 `?id=xxx`：

```js
onLoad(options) {
  const segmentId = parseInt(options.id, 10)
  if (!segmentId || isNaN(segmentId)) {
    wx.showToast({ title: '无效赛段', icon: 'none' })
    setTimeout(() => wx.navigateBack(), 1500)
    return
  }
  
  const app = getApp()
  this.setData({ 
    segmentId, 
    loading: true,
    isLoggedIn: !!app.globalData.token,
    myUserId: app.globalData.userId
  })
  this.fetchAllData(segmentId)
}
```

- [ ] **4.2** fetchAllData 三 fetch 并行：

```js
async fetchAllData(segmentId) {
  try {
    // 三 fetch 并行 / 各自独立失败
    const [segment, myEffort, leaderboard] = await Promise.all([
      api.getSegmentDetail(segmentId),
      this.data.isLoggedIn ? api.getMySegmentEfforts(segmentId).catch(() => null) : Promise.resolve(null),
      api.getSegmentLeaderboard(segmentId, 10).catch(() => { 
        this.setData({ leaderboardError: true })
        return null
      })
    ])
    
    // 处理 segment
    const cityLabel = (segment.city && segment.city !== 'unknown') ? CITY_LABELS[segment.city] : ''
    const shouldShowExpand = segment.introduction && segment.introduction.length > 80
    
    // 处理 myEffort（数组取最快一条 = PB）
    let myEffortData = null, progressText = ''
    if (myEffort && myEffort.efforts && myEffort.efforts.length > 0) {
      const sorted = myEffort.efforts.sort((a, b) => a.elapsed_time - b.elapsed_time)
      myEffortData = sorted[0]
      myEffortData.elapsed_timeFormatted = formatTime(myEffortData.elapsed_time)
      myEffortData.created_atFormatted = formatDate(myEffortData.created_at)
      // 进步对比（最快 vs 最慢）
      if (sorted.length >= 2) {
        const slowest = sorted[sorted.length - 1]
        progressText = `从 ${formatTime(slowest.elapsed_time)} 提到 ${formatTime(myEffortData.elapsed_time)}`
      }
    }
    
    // 处理 leaderboard
    if (leaderboard && leaderboard.top) {
      leaderboard.top = leaderboard.top.map(row => ({
        ...row,
        elapsed_timeFormatted: formatTime(row.elapsed_time)
      }))
      if (leaderboard.my_rank && leaderboard.my_elapsed_time) {
        leaderboard.my_elapsed_timeFormatted = formatTime(leaderboard.my_elapsed_time)
      }
    }
    
    this.setData({ 
      segment, cityLabel, shouldShowExpand,
      myEffort: myEffortData, progressText,
      leaderboard: leaderboard || { top: [], my_rank: null },
      loading: false 
    })
    
    // 渲染海拔曲线（F1 陷阱：setTimeout 兜底）
    if (segment.elevation_profile) {
      setTimeout(() => this.renderElevationChart(segment.elevation_profile), 100)
    }
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

- [ ] **4.3** 加 toggleIntro / fetchLeaderboard 重试 / goBack / goLogin / renderElevationChart 方法
- [ ] **4.4** require utils/city.js + utils/format.js（formatTime / formatDate 助手）

### Step 5：实现 segment.wxss

- [ ] **5.1** 4 区块 card 样式 + 海拔图 canvas + leaderboard 行（含"我"高亮）+ my-rank-divider 虚线分隔

### Step 6：手工回归

- [ ] **6.1** 真机：
  - 进 explore tab 点"妙峰山"卡片 → 跳转赛段详情页
  - 第一屏：海拔曲线 + 城市 tag + 4 数字（不显示难度 badge）
  - AI 介绍 section 显示（admin 审过的内容 / 长文展开收起）
  - 我的记录：Tim 骑过则显示 PB + 进步；CCF 没骑则显示引导
  - 全网排行榜：top 10 显示 + Tim 在第 3 高亮 + CCF 第 12 在 my-rank-row 单独显示
  - 未登录：第一屏 + AI + leaderboard 显示 / 我的记录 + 我的排名 显示登录引导
  - 不存在 segment_id → "赛段不存在"+ 返回

### Step 7：双审 + Codex + commit

- [ ] **7.1** Claude 双审 + Codex 异源审（重点关注：D7 leaderboard 展示 / D14 不展示难度 badge / 4 区块状态机完整性）
- [ ] **7.2** commit：

```bash
git add miniprogram/pages/segment/ miniprogram/utils/ miniprogram/app.json
git commit -m "feat(miniprogram): 任务4.5 赛段详情页新建（4 区块完整 ship）

新建 pages/segment/（独立页 / 不在 tabBar）4 区块：
- 第一屏：海拔曲线 + 城市 tag + 4 数字（D14 不展示难度 badge）
- AI 介绍：50-100 字 + 展开收起 / 暂无介绍 placeholder
- 我的记录（D7 改文案）：PB + 进步对比 / 没骑过引导文案
- 全网排行榜（D7 反转）：top 10 + 我的排名（top 10 外单独行）

技术要点：
- 三 fetch 并行（segment + my efforts + leaderboard）/ 独立失败
- 海拔曲线 canvas hidden + setTimeout(100) 兜底（F1 陷阱）
- 未登录降级（第一屏 + AI + top 10 正常 / 我的记录 + 排名 登录引导）
- utils/city.js + utils/format.js 抽公共

来源：phase-4-prd.md §10 / D7 反转 / D14 / 用户故事 §2.2
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## ✅ 自检三问

1. **D7 反转落实？** 全网排行榜 top 10 + 我的排名都展示？我在 top 10 里高亮 / 不在 top 10 单独行显示？
2. **D14 落实？** 第一屏没有难度 badge？只有海拔 + 城市 + 4 数字？
3. **3 fetch 独立失败？** segment fetch 失败 = 全页错误；my efforts 失败 = 我的记录显示加载失败；leaderboard 失败 = 排行榜显示加载失败 + 重试按钮？

---

## ⚠️ 红线

- ❌ 第一屏展示难度 badge（D14 / Tim 砍了 / Sprint 5 再细化算法）
- ❌ 我的记录用"PB"文案（D7 / 必须叫"我的记录"）
- ❌ 全网排行榜不展示（D7 反转 / v0.1 砍了 / v0.2 改回展示）
- ❌ 海拔曲线 canvas 用 wx:if（必须 hidden / F1 陷阱）
- ❌ 三 fetch 共用 try/catch 一损俱损（必须独立 catch）

---

**END task-4.5**
