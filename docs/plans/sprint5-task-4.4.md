# Sprint 5 Task-4.4 — segment 详情页改 Strava 双行 + from_activity_id

> Sprint 5 task-4 系列 / 第 4 个 / 前置：4.1 `f877844` / 4.2 `9058ba3` / 4.3 `8c32e23`

---

## ─────── 给 Tim 看 ───────

### 干啥用

把赛段详情页"我的记录"那张卡改成 Strava 风格的双行结构：
- 上行：**本次成绩**（只在从某次骑行点进来时才显示）
- 下行：**个人最快**（PR）
- 卡底：**"你的成绩 N 项 ›"**（task-4.5 才接通跳转）

### 用户故事

**A — 从骑行详情点赛段**
我刚骑完一次妙峰山，打开骑行详情 → 点列表里"妙峰山 5:42" → 跳转 segment 详情页
→ "我的记录"卡显示：
```
本次  5:42  ·  2026-05-15
最快  4:16  ·  2023-09-10
        你的成绩 21 项 ›
```

**B — 从探索 tab / 通知点赛段**
我在 explore tab 看到一条新赛段卡（从没骑过）→ 点进去
→ "我的记录"卡显示：
```
最快  4:16  ·  2023-09-10
        你的成绩 21 项 ›
```
（没"本次"那行 / 因为不是从某次骑行进的）

**C — 从未骑过这条赛段**
卡片显示：`还没骑过这条赛段，去骑一次试试`（沿用现有兜底）

### 怎么算做对了

- ✓ 从 `骑行详情` 进 → 路径带 `?from_activity_id=N` → 显示"本次"行
- ✓ 从 explore / 通知进 → 路径不带参数 → 不显示"本次"行
- ✓ "本次"行的用时 + 日期来自 my-efforts 接口里 activity_id == N 的那条
- ✓ PR 那行用现有 myEffort.pr_elapsed_time（不变）
- ✓ "你的成绩 N 项 ›" 中 N = my-efforts 总数（点击 task-4.5 才接通）
- ✓ N=0（从没骑过）→ 不显示这行入口

### 这次**不做**
- 点击"你的成绩 N 项"跳转新页（task-4.5 做）
- 黄色 PR 标记 / 全屏列表渲染（task-4.5）

### 估时
1 天

---

## ─────── 折叠：技术细节 ───────

<details>

### 改动文件

1. **`miniprogram/utils/api.js`** — 加 `getMySegmentEfforts(segmentId)` helper（调 task-4.3 新接口）
2. **`miniprogram/pages/segment/segment.js`**:
   - onLoad 解析 `options.from_activity_id`
   - fetchAllData 加第 4 个 fetch：my-efforts（仅登录时拉）
   - 新 applyMyEfforts() 找出"本次"对应 effort + 算 N
3. **`miniprogram/pages/segment/segment.wxml`**:
   - "我的记录"卡改双行结构
   - 加底部 "你的成绩 N 项 ›"（task-4.5 之前 disabled）
4. **`miniprogram/pages/segment/segment.wxss`** — 双行布局样式
5. **`miniprogram/pages/detail/detail.js:508`** — wx.navigateTo url 加 `&from_activity_id=` + activity id
6. **`miniprogram/pages/explore/explore.js:307`** + **`miniprogram/pages/notification/notification.js:179`** —— **不改**（保持不传 from_activity_id / 显示纯 PR 模式）

### "本次" 数据查找逻辑

```js
applyMyEfforts(myEffortsItems) {
  const fromActivityId = this.data.fromActivityId
  if (!fromActivityId) {
    this.setData({ myEffortsCount: myEffortsItems.length, currentAttempt: null })
    return
  }
  const current = myEffortsItems.find(e => e.activity_id === fromActivityId)
  this.setData({
    myEffortsCount: myEffortsItems.length,
    currentAttempt: current
      ? { time: formatTime(current.elapsed_time), date: formatDate(current.created_at) }
      : null
  })
}
```

### onLoad 改动

```js
onLoad(options) {
  const segmentId = parseInt(options.id, 10)
  const fromActivityId = parseInt(options.from_activity_id, 10) || null
  // ...
  this.setData({ segmentId, fromActivityId, ... })
}
```

### wxml 双行结构（替换现有 record-content 区块）

```html
<view wx:else class="record-content">
  <view class="record-row" wx:if="{{currentAttempt}}">
    <text class="record-label">本次</text>
    <text class="record-time">{{currentAttempt.time}}</text>
    <text class="record-date">{{currentAttempt.date}}</text>
  </view>
  <view class="record-row record-pr">
    <text class="record-label">最快</text>
    <text class="record-time">{{myEffortDisplay.prTime}}</text>
    <text class="record-date">{{myEffortDisplay.prDate}}</text>
  </view>
  <view class="record-row record-pr-flag" wx:if="{{myEffort.current_attempt_is_pr && !myEffort.is_first_attempt}}">
    <text>这次创下新纪录</text>
  </view>
  <view class="record-row my-efforts-entry" wx:if="{{myEffortsCount > 0}}">
    <text>你的成绩 {{myEffortsCount}} 项 ›</text>
  </view>
</view>
```

注：task-4.4 阶段 my-efforts-entry 不接 bindtap（task-4.5 才接通），先 disabled-like 渲染。

### detail.js:508 修改

```js
// 前
wx.navigateTo({ url: '/pages/segment/segment?id=' + id })
// 后
wx.navigateTo({ url: '/pages/segment/segment?id=' + id + '&from_activity_id=' + this.data.activityId })
```

### 红线

- 不动 explore.js / notification.js（保持不传 from_activity_id 行为）
- 不接通 my-efforts-entry 点击（task-4.5 做）
- 不在 task-4.4 范围内做 PR 黄点 / 年份分组（task-4.5 做）

### 测试覆盖

小程序无单测框架——靠手动验证 + Claude 集成审 grep 自校验：
- wxml 渲染字段 ↔ js setData 字段一致
- js fetch 调用 ↔ api.js helper 签名一致
- url 参数命名一致（`from_activity_id` snake_case）
- 三种打开路径手动验证（从 detail 进 / explore 进 / 通知进）

</details>
