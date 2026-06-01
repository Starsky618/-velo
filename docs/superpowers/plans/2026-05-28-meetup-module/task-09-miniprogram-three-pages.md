# Task 9: Mini Program Three Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1 mini program journey: meetup list, meetup detail, and a three-step create sheet.

**Architecture:** The mini program stays thin. It calls backend APIs, renders states, and never rebuilds route or participation rules in the page layer.

**Tech Stack:** WeChat Mini Program JS/WXML/WXSS/JSON, existing `utils/api.js`, static pytest checks.

---

## User Story

周五晚阿杰打开“约骑”，看到陈哥周六的“晋阳湖巡航”卡片，点进去看配速和名额，发现 3/6 还能加入，就点“加入”。陈哥则在创建页先选路线、填时间集合点、确认发布，一路都是三步，不用理解后端状态机。

## Files

- Modify: `miniprogram/app.json`
- Modify: `miniprogram/utils/api.js`
- Create: `miniprogram/pages/meetups-list/meetups-list.js`
- Create: `miniprogram/pages/meetups-list/meetups-list.wxml`
- Create: `miniprogram/pages/meetups-list/meetups-list.wxss`
- Create: `miniprogram/pages/meetups-list/meetups-list.json`
- Create: `miniprogram/pages/meetup-detail/meetup-detail.js`
- Create: `miniprogram/pages/meetup-detail/meetup-detail.wxml`
- Create: `miniprogram/pages/meetup-detail/meetup-detail.wxss`
- Create: `miniprogram/pages/meetup-detail/meetup-detail.json`
- Create: `miniprogram/pages/meetup-create/meetup-create.js`
- Create: `miniprogram/pages/meetup-create/meetup-create.wxml`
- Create: `miniprogram/pages/meetup-create/meetup-create.wxss`
- Create: `miniprogram/pages/meetup-create/meetup-create.json`
- Create: `tests/test_meetup_miniprogram_static.py`
- Test: `tests/test_meetup_miniprogram_static.py`

## Evidence Anchors

- [✓ grep] v1 has list/detail/create three-page frontend task: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:545`.
- [✓ grep] API wrapper pattern: `miniprogram/utils/api.js:114-125`.
- [✓ grep] app page registration pattern: `miniprogram/app.json:1-17`.
- [✓ grep] v1 excludes route footprint, recommendation, and user interaction beyond join/leave: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:552-560`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 mini program pages；复审时确认测试者≠实现者，且 v1 范围外页面词汇扫描为空。

## Steps

- [ ] **Step 1: Read frontend patterns**

```bash
nl -ba miniprogram/utils/api.js | sed -n '114,125p'
nl -ba miniprogram/app.json | sed -n '1,17p'
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '552,560p'
```

Expected: you see page registration, api helper style, and v1 non-goals.

- [ ] **Step 2: Write red static tests**

Create `tests/test_meetup_miniprogram_static.py`:

```python
"""约骑模块 Task 9：小程序静态合同测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_meetup_pages_are_registered_at_app_json_tail():
    app_json = json.loads(_read(MINI / "app.json"))

    assert app_json["pages"][0] == "pages/home/home"
    assert app_json["pages"][-3:] == [
        "pages/meetups-list/meetups-list",
        "pages/meetup-detail/meetup-detail",
        "pages/meetup-create/meetup-create",
    ]


def test_meetup_page_files_exist():
    for page in ("meetups-list", "meetup-detail", "meetup-create"):
        folder = MINI / "pages" / page
        for suffix in ("js", "wxml", "wxss", "json"):
            assert (folder / f"{page}.{suffix}").exists()


def test_api_helpers_use_meetup_endpoints():
    api = _read(MINI / "utils" / "api.js")

    for snippet in [
        "getMeetupsList",
        "getMeetupDetail",
        "createMeetup",
        "updateMeetup",
        "publishMeetup",
        "cancelMeetup",
        "joinMeetup",
        "leaveMeetup",
        "getRouteBooksList",
        "getRouteBookActivityCandidates",
        "createRouteBookFromActivity",
        "getSegmentsList",
        "requestForm",
    ]:
        assert snippet in api
    assert "/api/meetups" in api
    assert "/api/route-books" in api


def test_list_page_loads_open_meetups_and_navigates_to_detail():
    js = _read(MINI / "pages" / "meetups-list" / "meetups-list.js")
    wxml = _read(MINI / "pages" / "meetups-list" / "meetups-list.wxml")

    assert "api.getMeetupsList" in js
    assert "status: 'OPEN'" in js
    assert "/pages/meetup-detail/meetup-detail?id=" in js
    assert 'wx:for="{{meetups}}"' in wxml
    assert "发起约骑" in wxml


def test_detail_page_joins_and_leaves_without_user_chat():
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    wxml = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxml")

    assert "api.joinMeetup" in js
    assert "api.leaveMeetup" in js
    assert "api.getMeetupDetail" in js
    assert "onTapJoin" in js
    assert "onTapLeave" in js
    assert "私信" not in wxml
    assert "评论" not in wxml


def test_create_page_is_three_step_flow_and_uses_backend_state():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "steps: [" in js
    assert "route" in js and "details" in js and "publish" in js
    assert "api.createMeetup" in js
    assert "api.publishMeetup" in js
    assert "api.getSegmentsList" in js
    assert "api.getRouteBooksList" in js
    assert "api.getRouteBookActivityCandidates" in js
    assert "selectedSegmentId" in js
    assert "selectedRouteBookId" in js
    assert "selectedActivityId" in js
    assert "currentStep" in wxml
    assert "路线" in wxml and "时间" in wxml and "发布" in wxml


def test_v1_out_of_scope_features_are_absent():
    all_text = "\n".join(_read(path) for path in (MINI / "pages").glob("meetup*/*.*"))

    assert "路线足迹" not in all_text
    assert "算法推荐" not in all_text
    assert "为你推荐" not in all_text
    assert "私聊" not in all_text
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_meetup_miniprogram_static.py -q
```

Expected: FAIL because the mini program pages and helpers do not exist.

- [ ] **Step 4: Register pages**

Append these three paths to the end of `miniprogram/app.json` pages:

```json
"pages/meetups-list/meetups-list",
"pages/meetup-detail/meetup-detail",
"pages/meetup-create/meetup-create"
```

Keep `pages/home/home` first.

- [ ] **Step 5: Add API helpers**

Insert this helper before `module.exports` in `miniprogram/utils/api.js`. It keeps the route-book activity import aligned with the backend `Form(...)` contract from Task 2:

```javascript
function requestForm(url, method, data) {
  var app = getAppSafe()
  var baseUrl = (app && app.globalData.baseUrl) || BASE_URL
  var token = app && app.globalData.token

  if (method === undefined) method = 'POST'
  if (data === undefined) data = {}

  return new Promise(function (resolve, reject) {
    wx.request({
      url: baseUrl + url,
      method: method,
      data: data,
      header: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': token ? 'Bearer ' + token : '',
      },
      success: function (res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          var defaultMsg = res.statusCode >= 500 ? '服务器开小差了，请稍后重试' : '请求失败'
          reject({
            code: res.statusCode,
            message: (res.data && res.data.detail) || defaultMsg,
          })
        }
      },
      fail: function () {
        reject({ code: -1, message: '网络连接失败，请检查网络' })
      },
    })
  })
}
```

Append these methods inside `module.exports` in `miniprogram/utils/api.js`:

```javascript
  getMeetupsList: function (params) {
    return request('/api/meetups' + buildQuery(params || {}), 'GET')
  },
  getMeetupDetail: function (meetupId) {
    return request('/api/meetups/' + meetupId, 'GET')
  },
  getMyMeetupDraft: function () {
    return request('/api/meetups/my-draft', 'GET')
  },
  createMeetup: function (data) {
    return request('/api/meetups', 'POST', data)
  },
  updateMeetup: function (meetupId, data) {
    return request('/api/meetups/' + meetupId, 'PATCH', data)
  },
  publishMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId + '/publish', 'POST', {})
  },
  cancelMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId + '/cancel', 'POST', {})
  },
  deleteMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId, 'DELETE')
  },
  joinMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId + '/join', 'POST', {})
  },
  leaveMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId + '/leave', 'DELETE')
  },
  getRouteBooksList: function (params) {
    return request('/api/route-books' + buildQuery(params || {}), 'GET')
  },
  getRouteBookActivityCandidates: function () {
    return request('/api/route-books/activity-candidates', 'GET')
  },
  createRouteBookFromActivity: function (name, activityId) {
    return requestForm('/api/route-books', 'POST', {
      name: name,
      source: 'activity_derived',
      source_activity_id: activityId,
    })
  },
```

- [ ] **Step 6: Create list page**

`miniprogram/pages/meetups-list/meetups-list.json`:

```json
{
  "navigationBarTitleText": "约骑",
  "enablePullDownRefresh": true
}
```

`miniprogram/pages/meetups-list/meetups-list.js`:

```javascript
const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    loadError: false,
    meetups: [],
    page: 1,
    hasMore: true,
  },

  onLoad() {
    this.fetchMeetups(1)
  },

  onPullDownRefresh() {
    this.fetchMeetups(1).finally(function () {
      wx.stopPullDownRefresh()
    })
  },

  onReachBottom() {
    if (!this.data.hasMore || this.data.loading) return
    this.fetchMeetups(this.data.page + 1)
  },

  fetchMeetups(page) {
    const that = this
    this.setData({ loading: true, loadError: false })
    return api.getMeetupsList({ status: 'OPEN', page: page, page_size: 20 })
      .then(function (res) {
        const items = (res.items || []).map(that._enrichMeetup)
        that.setData({
          loading: false,
          page: page,
          meetups: page === 1 ? items : that.data.meetups.concat(items),
          hasMore: (res.items || []).length >= 20,
        })
      })
      .catch(function () {
        that.setData({ loading: false, loadError: true })
      })
  },

  _enrichMeetup(item) {
    const count = Number(item.participants_count) || 0
    const max = Number(item.max_participants) || 0
    return Object.assign({}, item, {
      distanceText: item.snapshot_distance ? (item.snapshot_distance / 1000).toFixed(1) + 'km' : '-',
      climbText: item.snapshot_climb ? Math.round(item.snapshot_climb) + 'm' : '-',
      seatText: count + '/' + max,
      full: max > 0 && count >= max,
    })
  },

  onTapMeetup(e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    wx.navigateTo({ url: '/pages/meetup-detail/meetup-detail?id=' + id })
  },

  onTapCreate() {
    wx.navigateTo({ url: '/pages/meetup-create/meetup-create' })
  },
})
```

`miniprogram/pages/meetups-list/meetups-list.wxml`:

```xml
<view class="meetups-page">
  <view class="topbar">
    <text class="title">约骑</text>
    <button class="create-btn" bindtap="onTapCreate">发起约骑</button>
  </view>

  <view wx:if="{{loading && meetups.length === 0}}" class="state">加载中</view>
  <view wx:elif="{{loadError}}" class="state">约骑加载失败</view>
  <view wx:elif="{{meetups.length === 0}}" class="state">暂时没有开放约骑</view>

  <view wx:else class="meetup-list">
    <view class="meetup-card" wx:for="{{meetups}}" wx:key="id" data-id="{{item.id}}" bindtap="onTapMeetup">
      <view class="card-head">
        <text class="route-name">{{item.snapshot_route_name}}</text>
        <text class="seat {{item.full ? 'full' : ''}}">{{item.seatText}}</text>
      </view>
      <view class="meta-row">
        <text>{{item.distanceText}}</text>
        <text>{{item.climbText}}</text>
        <text>{{item.pace_level}}</text>
      </view>
      <text class="meeting">{{item.meeting_point}}</text>
    </view>
  </view>
</view>
```

`miniprogram/pages/meetups-list/meetups-list.wxss`:

```css
page { background: #F3F5F4; }
.meetups-page { min-height: 100vh; padding: 24rpx; box-sizing: border-box; }
.topbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24rpx; }
.title { font-size: 42rpx; font-weight: 800; color: #111827; }
.create-btn { margin: 0; height: 64rpx; line-height: 64rpx; padding: 0 24rpx; border-radius: 12rpx; background: #111827; color: #fff; font-size: 24rpx; }
.state { min-height: 420rpx; display: flex; align-items: center; justify-content: center; color: #6B7280; font-size: 26rpx; }
.meetup-list { display: flex; flex-direction: column; gap: 20rpx; }
.meetup-card { background: #fff; border: 1rpx solid #DDE4DF; border-radius: 16rpx; padding: 28rpx; box-shadow: 0 10rpx 24rpx rgba(20, 35, 28, 0.08); }
.card-head { display: flex; justify-content: space-between; gap: 20rpx; align-items: center; }
.route-name { font-size: 32rpx; font-weight: 800; color: #111827; }
.seat { flex: 0 0 auto; font-size: 24rpx; font-weight: 700; color: #2EAD6B; }
.seat.full { color: #C9574C; }
.meta-row { display: flex; gap: 18rpx; margin-top: 18rpx; font-size: 23rpx; color: #5D6672; }
.meeting { display: block; margin-top: 16rpx; font-size: 24rpx; color: #30363D; }
```

- [ ] **Step 7: Create detail page**

`miniprogram/pages/meetup-detail/meetup-detail.json`:

```json
{
  "navigationBarTitleText": "约骑详情"
}
```

`miniprogram/pages/meetup-detail/meetup-detail.js`:

```javascript
const api = require('../../utils/api')

Page({
  data: {
    meetupId: 0,
    loading: true,
    loadError: false,
    meetup: null,
    joining: false,
  },

  onLoad(options) {
    const id = parseInt(options && options.id, 10)
    if (!id || isNaN(id)) {
      wx.showToast({ title: '无效约骑', icon: 'none' })
      return
    }
    this.setData({ meetupId: id })
    this.fetchDetail()
  },

  fetchDetail() {
    const that = this
    this.setData({ loading: true, loadError: false })
    return api.getMeetupDetail(this.data.meetupId)
      .then(function (res) {
        that.setData({ loading: false, meetup: that._enrich(res) })
      })
      .catch(function () {
        that.setData({ loading: false, loadError: true })
      })
  },

  _enrich(item) {
    const count = Number(item.participants_count) || 0
    const max = Number(item.max_participants) || 0
    return Object.assign({}, item, {
      distanceText: item.snapshot_distance ? (item.snapshot_distance / 1000).toFixed(1) + 'km' : '-',
      climbText: item.snapshot_climb ? Math.round(item.snapshot_climb) + 'm' : '-',
      seatText: count + '/' + max,
      full: max > 0 && count >= max,
    })
  },

  onTapJoin() {
    const that = this
    if (this.data.joining) return
    this.setData({ joining: true })
    api.joinMeetup(this.data.meetupId)
      .then(function () {
        wx.showToast({ title: '已加入', icon: 'success' })
        return that.fetchDetail()
      })
      .catch(function (err) {
        wx.showToast({ title: (err && err.message) || '加入失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ joining: false })
      })
  },

  onTapLeave() {
    const that = this
    if (this.data.joining) return
    this.setData({ joining: true })
    api.leaveMeetup(this.data.meetupId)
      .then(function () {
        wx.showToast({ title: '已退出', icon: 'success' })
        return that.fetchDetail()
      })
      .catch(function (err) {
        wx.showToast({ title: (err && err.message) || '退出失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ joining: false })
      })
  },
})
```

`miniprogram/pages/meetup-detail/meetup-detail.wxml`:

```xml
<view class="detail-page">
  <view wx:if="{{loading}}" class="state">加载中</view>
  <view wx:elif="{{loadError}}" class="state">约骑详情加载失败</view>
  <view wx:else class="detail">
    <view class="hero">
      <text class="route-name">{{meetup.snapshot_route_name}}</text>
      <text class="desc">{{meetup.description || '一起稳定骑完这条路线'}}</text>
      <view class="meta-grid">
        <view><text class="num">{{meetup.distanceText}}</text><text class="label">距离</text></view>
        <view><text class="num">{{meetup.climbText}}</text><text class="label">爬升</text></view>
        <view><text class="num">{{meetup.seatText}}</text><text class="label">名额</text></view>
        <view><text class="num">{{meetup.pace_level}}</text><text class="label">配速</text></view>
      </view>
    </view>

    <view class="section">
      <text class="section-title">集合点</text>
      <text class="body">{{meetup.meeting_point}}</text>
    </view>

    <view class="action-row">
      <button class="join" disabled="{{meetup.full || joining}}" bindtap="onTapJoin">{{meetup.full ? '已满员' : '加入'}}</button>
      <button class="leave" disabled="{{joining}}" bindtap="onTapLeave">退出</button>
    </view>
  </view>
</view>
```

`miniprogram/pages/meetup-detail/meetup-detail.wxss`:

```css
page { background: #F3F5F4; }
.detail-page { min-height: 100vh; padding: 24rpx; box-sizing: border-box; }
.state { min-height: 520rpx; display: flex; align-items: center; justify-content: center; color: #6B7280; }
.hero, .section { background: #fff; border: 1rpx solid #DDE4DF; border-radius: 16rpx; padding: 32rpx; margin-bottom: 22rpx; }
.route-name { display: block; font-size: 42rpx; font-weight: 850; color: #111827; }
.desc { display: block; margin-top: 16rpx; font-size: 25rpx; line-height: 1.6; color: #4B5563; }
.meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18rpx; margin-top: 28rpx; }
.meta-grid view { background: #F7F8FA; border-radius: 12rpx; padding: 20rpx; }
.num { display: block; font-size: 30rpx; font-weight: 800; color: #111827; }
.label { display: block; margin-top: 6rpx; font-size: 21rpx; color: #7B828C; }
.section-title { display: block; font-size: 28rpx; font-weight: 800; color: #111827; }
.body { display: block; margin-top: 12rpx; font-size: 25rpx; color: #374151; }
.action-row { display: grid; grid-template-columns: 1fr 1fr; gap: 18rpx; }
.join, .leave { height: 82rpx; line-height: 82rpx; border-radius: 14rpx; font-size: 28rpx; font-weight: 800; }
.join { background: #111827; color: #fff; }
.leave { background: #fff; color: #111827; border: 1rpx solid #DDE4DF; }
```

- [ ] **Step 8: Create three-step create page**

`miniprogram/pages/meetup-create/meetup-create.json`:

```json
{
  "navigationBarTitleText": "发起约骑"
}
```

`miniprogram/pages/meetup-create/meetup-create.js`:

```javascript
const api = require('../../utils/api')

Page({
  data: {
    steps: ['route', 'details', 'publish'],
    currentStep: 0,
    routeSource: 'segment',
    segments: [],
    routeBooks: [],
    candidates: [],
    selectedSegmentId: null,
    selectedRouteBookId: null,
    selectedActivityId: null,
    draftId: null,
    form: {
      routeName: '',
      meetingPoint: '',
      paceLevel: 'cruise',
      maxParticipants: 6,
      description: '',
      startTime: '',
      estimatedEndTime: '',
    },
    saving: false,
  },

  onLoad() {
    this.fetchRouteOptions()
  },

  fetchRouteOptions() {
    const that = this
    api.getSegmentsList({ page: 1, page_size: 50 })
      .then(function (res) {
        that.setData({ segments: res.items || [] })
      })
      .catch(function () {
        that.setData({ segments: [] })
      })
    api.getRouteBooksList()
      .then(function (res) {
        that.setData({ routeBooks: res.items || [] })
      })
      .catch(function () {
        that.setData({ routeBooks: [] })
      })
    api.getRouteBookActivityCandidates()
      .then(function (res) {
        that.setData({ candidates: res.items || [] })
      })
      .catch(function () {
        that.setData({ candidates: [] })
      })
  },

  onSelectRouteSource(e) {
    this.setData({
      routeSource: e.currentTarget.dataset.source,
      selectedSegmentId: null,
      selectedRouteBookId: null,
      selectedActivityId: null,
    })
  },

  onSelectSegment(e) {
    this.setData({ selectedSegmentId: Number(e.currentTarget.dataset.id) })
  },

  onSelectRouteBook(e) {
    this.setData({ selectedRouteBookId: Number(e.currentTarget.dataset.id) })
  },

  onSelectActivity(e) {
    this.setData({ selectedActivityId: Number(e.currentTarget.dataset.id) })
  },

  onInput(e) {
    const key = e.currentTarget.dataset.key
    const value = e.detail.value
    this.setData({ ['form.' + key]: value })
  },

  onNext() {
    if (this.data.currentStep < this.data.steps.length - 1) {
      this.setData({ currentStep: this.data.currentStep + 1 })
    }
  },

  onBack() {
    if (this.data.currentStep > 0) {
      this.setData({ currentStep: this.data.currentStep - 1 })
    }
  },

  onCreateDraft() {
    const that = this
    const hasSegment = !!this.data.selectedSegmentId
    const hasRouteBook = !!this.data.selectedRouteBookId
    const hasActivity = !!this.data.selectedActivityId
    if (!hasSegment && !hasRouteBook && !hasActivity) {
      wx.showToast({ title: '先选一条骑行路线', icon: 'none' })
      return
    }
    if (this.data.saving) return
    this.setData({ saving: true })
    const createMeetup = function (routeBookId, segmentId) {
      return api.createMeetup({
        segment_id: segmentId || null,
        route_book_id: routeBookId || null,
        start_time: that.data.form.startTime,
        estimated_end_time: that.data.form.estimatedEndTime,
        meeting_point: that.data.form.meetingPoint,
        pace_level: that.data.form.paceLevel,
        max_participants: Number(that.data.form.maxParticipants) || 6,
        description: that.data.form.description,
      })
    }
    const action = hasSegment
      ? createMeetup(null, this.data.selectedSegmentId)
      : hasRouteBook
        ? createMeetup(this.data.selectedRouteBookId, null)
        : api.createRouteBookFromActivity(this.data.form.routeName || '约骑路线', this.data.selectedActivityId)
          .then(function (routeBook) { return createMeetup(routeBook.id, null) })

    action
      .then(function (draft) {
        that.setData({ draftId: draft.id, currentStep: 2 })
      })
      .catch(function (err) {
        wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ saving: false })
      })
  },

  onPublish() {
    const id = this.data.draftId
    if (!id) return
    api.publishMeetup(id)
      .then(function () {
        wx.showToast({ title: '已发布', icon: 'success' })
        wx.redirectTo({ url: '/pages/meetup-detail/meetup-detail?id=' + id })
      })
      .catch(function (err) {
        wx.showToast({ title: (err && err.message) || '发布失败', icon: 'none' })
      })
  },
})
```

`miniprogram/pages/meetup-create/meetup-create.wxml`:

```xml
<view class="create-page">
  <view class="stepbar">
    <text class="{{currentStep === 0 ? 'active' : ''}}">路线</text>
    <text class="{{currentStep === 1 ? 'active' : ''}}">时间</text>
    <text class="{{currentStep === 2 ? 'active' : ''}}">发布</text>
  </view>

  <view wx:if="{{currentStep === 0}}" class="panel">
    <text class="panel-title">选择约骑路线</text>
    <view class="source-row">
      <text class="{{routeSource === 'segment' ? 'source active' : 'source'}}" data-source="segment" bindtap="onSelectRouteSource">已有赛段</text>
      <text class="{{routeSource === 'route_book' ? 'source active' : 'source'}}" data-source="route_book" bindtap="onSelectRouteSource">已有路书</text>
      <text class="{{routeSource === 'activity' ? 'source active' : 'source'}}" data-source="activity" bindtap="onSelectRouteSource">从骑行生成</text>
    </view>

    <block wx:if="{{routeSource === 'segment'}}">
      <view class="candidate" wx:for="{{segments}}" wx:key="id" data-id="{{item.id}}" bindtap="onSelectSegment">
        <text>{{item.name}}</text>
        <text>{{selectedSegmentId === item.id ? '已选' : '选择'}}</text>
      </view>
    </block>
    <block wx:elif="{{routeSource === 'route_book'}}">
      <view class="candidate" wx:for="{{routeBooks}}" wx:key="id" data-id="{{item.id}}" bindtap="onSelectRouteBook">
        <text>{{item.name}}</text>
        <text>{{selectedRouteBookId === item.id ? '已选' : '选择'}}</text>
      </view>
    </block>
    <block wx:else>
      <view class="candidate" wx:for="{{candidates}}" wx:key="id" data-id="{{item.id}}" bindtap="onSelectActivity">
        <text>{{item.title || '未命名骑行'}}</text>
        <text>{{selectedActivityId === item.id ? '已选' : '选择'}}</text>
      </view>
    </block>

    <view wx:if="{{routeSource === 'activity'}}">
      <text class="field-label">路书名称</text>
      <input data-key="routeName" bindinput="onInput" value="{{form.routeName}}" />
    </view>
    <button bindtap="onNext">下一步</button>
  </view>

  <view wx:elif="{{currentStep === 1}}" class="panel">
    <text class="panel-title">填写集合和时间</text>
    <text class="field-label">集合点</text>
    <input data-key="meetingPoint" bindinput="onInput" value="{{form.meetingPoint}}" />
    <text class="field-label">开始时间 ISO</text>
    <input data-key="startTime" bindinput="onInput" value="{{form.startTime}}" />
    <text class="field-label">预计结束时间 ISO</text>
    <input data-key="estimatedEndTime" bindinput="onInput" value="{{form.estimatedEndTime}}" />
    <text class="field-label">人数上限</text>
    <input type="number" data-key="maxParticipants" bindinput="onInput" value="{{form.maxParticipants}}" />
    <text class="field-label">备注</text>
    <input data-key="description" bindinput="onInput" value="{{form.description}}" />
    <view class="buttons"><button bindtap="onBack">上一步</button><button bindtap="onCreateDraft">保存草稿</button></view>
  </view>

  <view wx:else class="panel">
    <text class="panel-title">确认发布</text>
    <text class="summary">{{form.routeName}}</text>
    <text class="summary">{{form.meetingPoint}}</text>
    <view class="buttons"><button bindtap="onBack">上一步</button><button bindtap="onPublish">发布</button></view>
  </view>
</view>
```

`miniprogram/pages/meetup-create/meetup-create.wxss`:

```css
page { background: #F3F5F4; }
.create-page { min-height: 100vh; padding: 24rpx; box-sizing: border-box; }
.stepbar { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12rpx; margin-bottom: 24rpx; }
.stepbar text { text-align: center; padding: 18rpx 0; border-radius: 999rpx; background: #E7ECE9; color: #6B7280; font-size: 24rpx; font-weight: 700; }
.stepbar .active { background: #111827; color: #fff; }
.panel { background: #fff; border: 1rpx solid #DDE4DF; border-radius: 16rpx; padding: 28rpx; display: flex; flex-direction: column; gap: 20rpx; }
.panel-title { font-size: 32rpx; font-weight: 850; color: #111827; }
.source-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10rpx; }
.source { text-align: center; padding: 16rpx 8rpx; border-radius: 12rpx; background: #F7F8FA; color: #5D6672; font-size: 23rpx; font-weight: 750; }
.source.active { background: #111827; color: #fff; }
.candidate { display: flex; justify-content: space-between; align-items: center; padding: 20rpx; background: #F7F8FA; border-radius: 12rpx; font-size: 25rpx; }
input { min-height: 76rpx; padding: 0 20rpx; background: #F7F8FA; border-radius: 12rpx; font-size: 25rpx; }
.field-label { font-size: 23rpx; color: #5D6672; font-weight: 700; }
button { height: 78rpx; line-height: 78rpx; border-radius: 14rpx; background: #111827; color: #fff; font-weight: 800; }
.buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 16rpx; }
.summary { font-size: 26rpx; color: #374151; line-height: 1.5; }
```

- [ ] **Step 9: Run green tests**

```bash
python3 -m pytest tests/test_meetup_miniprogram_static.py -q
```

Expected: PASS.

- [ ] **Step 10: Self-review**

- [ ] Spec coverage: list, detail, existing segment, existing route book, activity-derived route book, and create three-step flow are present.
- [ ] Type consistency: frontend sends exactly one of `segment_id` or `route_book_id`, plus `start_time`, `estimated_end_time`, `meeting_point`, `pace_level`, `max_participants`.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: page code does not rebuild route matching, join rules, or backend state-machine logic.
- [ ] Scope guard: no route footprint, algorithm recommendation, private chat, comments, or user-to-user interaction beyond join/leave appears.

Run:

```bash
grep -rn "路线足迹\\|算法推荐\\|为你推荐\\|私聊\\|私信\\|评论\\|关注\\|点赞\\|打招呼\\|群聊\\|@用户\\|@骑友" miniprogram/pages/meetup* miniprogram/utils/api.js
python3 -m pytest tests/test_meetup_miniprogram_static.py -q
```

Expected: grep empty; tests pass.

- [ ] **Step 11: Commit**

```bash
git add miniprogram/app.json miniprogram/utils/api.js miniprogram/pages/meetups-list miniprogram/pages/meetup-detail miniprogram/pages/meetup-create tests/test_meetup_miniprogram_static.py
git commit -F - <<'MSG'
feat(meetup): task 9 add mini program meetup flow

Add meetup list, detail, and create pages with API helpers and static contract tests.
Keep the frontend inside v1 scope: discover, create, join, and leave only.
MSG
```
