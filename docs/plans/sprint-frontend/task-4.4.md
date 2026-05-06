# 任务 4.4：探索 tab 改造 + 砍 leaderboard tab（批 2 主体）

> **批 2 第一步**——批 1 ship 后启动。两件事：①explore tab 占位 → 实际功能（瀑布流 + 城市筛选 + 候选池曝光）；②砍掉 leaderboard tab（5 → 4 tab）+ 全代码 grep 跳转改向。

---

## 🎯 目标（一句话）

把 explore tab 从占位"即将上线"改造为赛段瀑布流（顶部城市筛选条 + 卡片瀑布流 + 新赛段 NEW 标签）；同时删除 leaderboard tab 整个目录 + app.json tabBar 减一项 + 全代码引用改向 explore tab 或赛段详情页。

---

## ⛓ 前置依赖

- 批 1（task-4.1 + 4.2 + 4.3）已 ship + 真用 1 周
- task-4.5 赛段详情页（独立页 / 可并行 / 但跳转目标必须存在 → 4.5 至少先有空架子）

## 📥 输入契约

- v5 Sprint 1+3 后端 `GET /api/segments?city=xxx&page=N&page_size=20` 已 ship（默认 `order_by(created_at desc)`）
- segments 表已含 city / introduction / created_at 字段

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| explore tab 改造（瀑布流 + 城市筛选 + NEW 标签）| 用户找新赛段 |
| 5 → 4 tab（app.json tabBar 减一项）| navigation 重构 |
| pages/leaderboard/ 整目录删除 | 减熵 |
| 全代码 leaderboard 跳转改向 | 无死链接 |

---

## 🧱 现状清单（subagent 必先 grep + Read）

| 项 | grep 命令 | 期望结果 |
|---|---|---|
| explore 现状 | `cat miniprogram/pages/explore/explore.wxml` | 应见占位"即将上线" |
| leaderboard 现状 | `ls miniprogram/pages/leaderboard/` | 应见 4 文件（js/wxml/wxss/json）|
| app.json tabBar | `grep -A 10 "tabBar" miniprogram/app.json` | 应见 5 项（home/explore/upload/leaderboard/profile）|
| 全代码 leaderboard 引用 | `grep -rn "pages/leaderboard\|/leaderboard/leaderboard" miniprogram/` | 应见至少 home / detail 等页面有跳转引用 |
| 后端 segments 列表 | `grep -n "@router.get(\"\")" app/segment/router.py` | 应见 line 127 |
| 后端默认排序 | `grep -n "order_by" app/segment/service_query.py | head -3` | 应见 line 82 `order_by(Segment.created_at.desc())` |

---

## 🛠 操作步骤

### Step 1：先做 explore tab 改造（不破坏 leaderboard）

#### 1.1 加 API 方法

- [ ] **1.1.1** `miniprogram/utils/api.js` 加：

```js
function getSegmentsList(params = {}) {
  const { city = '', page = 1, page_size = 20 } = params
  const query = []
  if (city) query.push(`city=${city}`)
  query.push(`page=${page}`, `page_size=${page_size}`)
  return request({
    url: `/api/segments?${query.join('&')}`,
    method: 'GET'
  })
}
exports.getSegmentsList = getSegmentsList
```

#### 1.2 改 explore.wxml

- [ ] **1.2.1** 替换占位为：

```xml
<view class="page-header">
  <text class="title">探索</text>
  <text class="subtitle">发现值得骑的赛段</text>
</view>

<!-- 顶部城市筛选条（横向滚动） -->
<scroll-view scroll-x class="city-filter-scroll">
  <view class="city-filter-list">
    <view class="city-chip {{activeCity === '' ? 'active' : ''}}"
          bindtap="switchCity" data-city="">
      <text>全部</text>
    </view>
    <view class="city-chip {{activeCity === item.code ? 'active' : ''}}"
          wx:for="{{cities}}" wx:key="code"
          bindtap="switchCity" data-city="{{item.code}}">
      <text>{{item.label}}</text>
    </view>
  </view>
</scroll-view>

<!-- 主体瀑布流 -->
<view class="loading" wx:if="{{loading && segments.length === 0}}">加载中...</view>
<view class="empty" wx:elif="{{segments.length === 0}}">该城市暂无赛段</view>

<view class="segment-list" wx:else>
  <view class="segment-card" wx:for="{{segments}}" wx:key="id"
        bindtap="goSegment" data-id="{{item.id}}">
    <view class="card-header">
      <text class="seg-name">{{item.name}}</text>
      <view class="new-badge" wx:if="{{item.isNew}}">NEW</view>
    </view>
    <view class="card-meta">
      <text class="meta-item">{{item.distance}} km</text>
      <text class="meta-item">↑{{item.elevation_gain}} m</text>
      <text class="meta-item">{{item.cityLabel}}</text>
      <text class="meta-item difficulty-{{item.difficulty}}">{{item.difficultyLabel}}</text>
    </view>
    <text class="card-intro" wx:if="{{item.introduction}}">{{item.introductionPreview}}</text>
  </view>
</view>

<view class="loading-more" wx:if="{{loadingMore}}">加载下一页...</view>
<view class="no-more" wx:elif="{{!hasMore && segments.length > 0}}">没有更多了</view>
```

#### 1.3 改 explore.js

- [ ] **1.3.1** data 初始化：

```js
data: {
  cities: [
    { code: 'beijing', label: '北京' },
    { code: 'shanghai', label: '上海' },
    { code: 'hangzhou', label: '杭州' },
    { code: 'shenzhen', label: '深圳' },
    { code: 'chengdu', label: '成都' },
    { code: 'taiyuan', label: '太原' }
  ],
  activeCity: '',
  segments: [],
  page: 1,
  loading: false,
  loadingMore: false,
  hasMore: true
}
```

- [ ] **1.3.2** 加 fetchSegments / switchCity / goSegment / onReachBottom 方法：
  - **NEW 标签**：前端判断 `item.created_at < (Date.now() - 30*24*60*60*1000)` → false 时 isNew = true
  - **城市筛选切换**：清空 segments + 重置 page=1 + refetch
  - **分页**：onReachBottom 触发 fetchSegments(page+1) 追加
  - **跳转**：`wx.navigateTo({ url: '/pages/segment/segment?id=' + e.currentTarget.dataset.id })`

#### 1.4 改 explore.wxss

- [ ] **1.4.1** 加 `.city-filter-scroll` / `.city-chip` / `.segment-card` / `.new-badge` / `.difficulty-easy/medium/hard/extreme` 样式

#### 1.5 测试 explore tab（leaderboard 还在不删）

- [ ] **1.5.1** 真机：
  - 进 explore 看到瀑布流
  - 切换城市筛选准确
  - 滑到底部加载下一页
  - 点卡片跳转赛段详情页（task-4.5 必须先 ship 空架子或同步进行）
  - NEW 标签合理（30 天内 created 才显示）

#### 1.6 explore 改造独立 commit（先稳一版）

- [ ] **1.6.1** commit：

```bash
git add miniprogram/pages/explore/ miniprogram/utils/api.js
git commit -m "feat(miniprogram): 任务4.4.1 explore tab 改造（瀑布流 + 城市筛选 + NEW 标签）

- explore.wxml/.js/.wxss 完整改造（占位 → 实际功能）
- 顶部 6 城横向筛选条（chip + active 高亮）
- 主体瀑布流（segment-card / 距离 / 爬升 / 城市 / 难度 / NEW 标签 / AI 介绍前 30 字）
- 分页 onReachBottom + loading-more / no-more 状态
- NEW 标签前端判断：created_at < 30 天前
- utils/api.js 加 getSegmentsList(params)

依赖 task-4.5 segment 详情页（跳转目标）
来源：phase-4-prd.md §9 / 4.4.A
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Step 2：砍 leaderboard tab + 全代码引用改向

#### 2.1 grep 全代码 leaderboard 引用

- [ ] **2.1.1** `grep -rn "pages/leaderboard\|/leaderboard/leaderboard" miniprogram/`
- [ ] **2.1.2** 列出所有引用文件 + 每处的跳转目的

#### 2.2 改向跳转

- [ ] **2.2.1** 每处引用判断改向哪：
  - `detail.wxml` "途经赛段"section → `/pages/segment/segment?id={{seg.id}}`
  - 其他类似引用 → 同上

#### 2.3 改 app.json tabBar（5 → 4 项）

- [ ] **2.3.1** Read `miniprogram/app.json` 现状
- [ ] **2.3.2** tabBar.list 删除 leaderboard 项（保留 home / explore / upload / profile 4 项）
- [ ] **2.3.3** 检查 icon path 是否还存在 / 如果 leaderboard icon 文件被引用就保留，否则可删除 assets/icons/leaderboard*

#### 2.4 删除 pages/leaderboard/ 目录

- [ ] **2.4.1** `rm -rf miniprogram/pages/leaderboard/`
- [ ] **2.4.2** 检查 app.json pages 数组也删除 `"pages/leaderboard/leaderboard"`

#### 2.5 真机测试 4 tab

- [ ] **2.5.1** 微信开发者工具 + 真机预览：
  - 4 个 tab 切换流畅 / icon 显示正常 / 没有 leaderboard tab
  - detail 页"途经赛段"section 点击跳转赛段详情页（不再跳 leaderboard）
  - notification / home 等页面跳转无死链接

#### 2.6 砍 leaderboard 独立 commit

- [ ] **2.6.1** commit：

```bash
git add miniprogram/app.json miniprogram/pages/  # 含删除的 leaderboard 目录
git commit -m "feat(miniprogram): 任务4.4.2 砍 leaderboard tab（5 → 4 tab）+ 跳转改向

- 删 pages/leaderboard/ 整目录（4 文件）
- app.json tabBar.list 5 项 → 4 项（删 leaderboard 配置）
- app.json pages 数组删 'pages/leaderboard/leaderboard'
- detail.wxml '途经赛段' section 跳转改向 /pages/segment/segment?id=
- grep 全代码无残留 leaderboard 引用
- 真机回归 4 tab 切换正常 / 无死链接

来源：phase-4-prd.md §9 / D5 / 4.4.B
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Step 3：双审 + Codex 异源审（整 task 4.4 完成后）

- [ ] **3.1** Claude A 忠 spec / Claude B 集成审
- [ ] **3.2** Codex 异源审（关注：跳转链路完整性 / NEW 标签判断 / 城市筛选准确性 / 4 tab 后底部 navigation 视觉是否破坏）

---

## ✅ 自检三问

1. **4 tab navigation 视觉零破坏？** icon size / tabBar height 跟 5 tab 时一致？iOS / Android 都没变形？
2. **leaderboard 跳转零残留？** grep 全代码 `pages/leaderboard` 0 结果？真机点遍 home / detail / notification 没死链接？
3. **explore 瀑布流性能？** 220 条赛段全部加载完会不会卡？分页是否正常截断？

---

## ⚠️ 红线

- ❌ explore 改造跟 leaderboard 砍合并到一个 commit（必须分两个 commit 便于 revert 单步）
- ❌ leaderboard 砍前不 grep 全代码就删（漏跳转引用 = 死链接）
- ❌ 用 PostGIS ST_* 函数做城市筛选（CLAUDE.md 陷阱 #15 SQLite 测试 fixture 不支持 / city 已是字符串字段直接 WHERE city='xxx'）
- ❌ NEW 标签判断逻辑写在后端（前端简单按 created_at < 30 天前判断 / 后端不动）

---

**END task-4.4**
