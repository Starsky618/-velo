# Sprint 5 Task-4.5 — 新页 segment-efforts：我在某赛段的全部成绩列表

> Sprint 5 task-4 系列 / 第 5 个 / 前置：4.1 / 4.2 / 4.3 / 4.4（4.4 已留好"你的成绩 N 项 ›"入口待接通）

---

## ─────── 给 Tim 看 ───────

### 干啥用

新建一个**全屏列表页**——你给我看的第 1 张图那样：

```
2025
  5月11日       21:37   26.5 km/h   107 W

2024
  7月3日        18:44   30.6 km/h   160 W
  5月18日       18:49   30.5 km/h   152 W
  5月11日 🟡   17:50   32.2 km/h   146 W     ← PR
  2月9日        18:19   31.3 km/h   180 W

2023
  ...
```

按年份分组（粗体大标题）/ 每行一次成绩 / 点行跳那次原始骑行详情 / 最快那条挂黄点。

### 用户故事

**A — 接通入口跳转**
我打开妙峰山赛段详情 → 看到"你的成绩 21 项 ›"
→ 点一下 → 跳新页 → 全屏显示我 21 次骑行成绩 / 按年份分组 / PR 黄点
→ 点 2024 年 5月18日那行 → 跳到那次 80 公里骑行详情页

**B — 没骑过这条赛段**
卡片在 task-4.4 已经显示"还没骑过这条赛段" / 不显示"N 项"入口 → 用户根本到不了 task-4.5 这个页面 / 不用处理空状态

**C — 仅骑过 1 次**
新页只有 1 行 / 标 PR 黄点 / 没有"对比"概念但页面照样可读

### 怎么算做对了

- ✓ 任何赛段都能从"你的成绩 N 项"点进来
- ✓ 列表按 created_at 倒序 / 同年合并到同一年份标题下
- ✓ 年份标题样式跟图 1 类似（粗体白字 + 上下分隔线）
- ✓ 每行 4 列：日期 / 用时 / 平均速度 / 平均功率
- ✓ PR 那条左侧或右侧挂黄点（小圆 / 不是文字）
- ✓ 点任意一行 → wx.navigateTo 跳 `/pages/detail/detail?id=N`
- ✓ 接通 task-4.4 留下的"你的成绩 N 项 ›"入口的 bindtap

### 这次**不做**
- 隐藏功率 / 心率开关（task-4.6 做）
- 分页（首页 100 条以内 / 不分页）

### 估时
1 天

---

## ─────── 折叠：技术细节 ───────

<details>

### 新建文件

新建小程序页 `miniprogram/pages/segment-efforts/`：
- `segment-efforts.js` — onLoad 拿 segment_id / fetch my-efforts / 按年份分组
- `segment-efforts.wxml` — 年份标题 + 列表渲染
- `segment-efforts.wxss` — 暗色主题 / 大字号 / 年份标题样式
- `segment-efforts.json` — 配置 navigationBarTitleText

`app.json` pages 数组加 `pages/segment-efforts/segment-efforts`

### task-4.4 入口接通

`segment.wxml` 把：
```html
<view class="my-efforts-entry" wx:if="{{myEffortsCount > 0}}">
  <text class="my-efforts-text">你的成绩 {{myEffortsCount}} 项</text>
  <text class="my-efforts-arrow">›</text>
</view>
```
改成：
```html
<view class="my-efforts-entry" wx:if="{{myEffortsCount > 0}}" bindtap="goMyEfforts">
  <text class="my-efforts-text">你的成绩 {{myEffortsCount}} 项</text>
  <text class="my-efforts-arrow">›</text>
</view>
```

`segment.js` 加 `goMyEfforts(): wx.navigateTo('/pages/segment-efforts/segment-efforts?segment_id=' + this.data.segmentId)`

### segment-efforts.js 数据流

```js
const api = require('../../utils/api')
const { formatTime, formatDate } = require('../../utils/format')

Page({
  data: {
    segmentId: null,
    groupedItems: [],  // [{ year: '2024', items: [{date, time, speed, power, is_pr, activity_id}] }]
    loading: true,
    loadFailed: false,
  },

  onLoad(options) {
    const segmentId = parseInt(options.segment_id, 10)
    if (!segmentId || segmentId <= 0) {
      wx.showToast({ title: '无效赛段', icon: 'none' })
      return setTimeout(() => wx.navigateBack(), 1500)
    }
    this.setData({ segmentId })
    this.fetchData()
  },

  fetchData() {
    api.getMySegmentEfforts(this.data.segmentId)
      .then((data) => {
        const grouped = this.groupByYear(data.items || [])
        this.setData({ groupedItems: grouped, loading: false })
      })
      .catch(() => {
        this.setData({ loading: false, loadFailed: true })
      })
  },

  // 按 created_at 的年份分组（保留接口返回的倒序顺序）
  groupByYear(items) {
    const groups = []
    let current = null
    items.forEach((item) => {
      const date = new Date(item.created_at)
      const year = String(date.getFullYear())
      const month = date.getMonth() + 1
      const day = date.getDate()
      if (!current || current.year !== year) {
        current = { year, items: [] }
        groups.push(current)
      }
      current.items.push({
        activity_id: item.activity_id,
        dateLabel: `${month}月${day}日`,
        timeText: formatTime(item.elapsed_time),
        speedText: item.avg_speed ? item.avg_speed.toFixed(1) + ' km/h' : '-',
        powerText: item.avg_power ? Math.round(item.avg_power) + ' W' : '-',
        is_pr: item.is_pr,
      })
    })
    return groups
  },

  onTapRow(e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    wx.navigateTo({ url: '/pages/detail/detail?id=' + id })
  },
})
```

### wxml 结构

```html
<view wx:if="{{loading}}" class="loading">加载中</view>
<view wx:elif="{{loadFailed}}" class="error">加载失败 点击重试</view>
<view wx:else class="page">
  <view class="group" wx:for="{{groupedItems}}" wx:key="year" wx:for-item="group">
    <text class="year-title">{{group.year}}</text>
    <view class="row" wx:for="{{group.items}}" wx:key="activity_id" wx:for-item="item"
          data-id="{{item.activity_id}}" bindtap="onTapRow">
      <view class="date-col">
        <text class="date-text">{{item.dateLabel}}</text>
        <view class="pr-dot" wx:if="{{item.is_pr}}"></view>
      </view>
      <view class="stats-col">
        <text class="time-text">{{item.timeText}}</text>
        <text class="speed-text">{{item.speedText}}</text>
        <text class="power-text">{{item.powerText}}</text>
      </view>
      <text class="arrow">›</text>
    </view>
  </view>
</view>
```

### wxss 风格（参考图 1）

- 黑底（背景 #000）/ 白字
- 年份标题：32rpx / 粗体 / 上下白线分隔
- 每行：日期左 / 数字右 / › 最右
- PR 黄点：8rpx 圆 / 亮黄 #FFD60A

### 红线

- 不动 task-4.1/4.2/4.3 后端代码
- 不动 task-4.4 双行结构（只接通入口 bindtap）
- 不写隐私字段挖空（task-4.6）

### 测试覆盖

小程序无单测——前后端契约靠 reviewer grep + 手动验证：
- groupByYear 算法正确（按年分组 / 保留 API 倒序）
- bindtap 跳转 url 拼接
- wxml ↔ js setData 字段对齐

### Codex 异源审重点

- `new Date(item.created_at)` 在 ISO 8601 含 +00:00 时区时跨平台行为是否一致（iOS / Android / 微信开发工具）
- groupByYear "年份切换"逻辑：API 已倒序时（5/2025, 7/2024, 5/2024, 2/2024, 11/2023） 是否正确分成 3 组
- 跳 detail 不传 from_activity_id（避免 detail 页又跳回 segment 形成循环？grep detail.js 看是否会自动跳 segment）

</details>
