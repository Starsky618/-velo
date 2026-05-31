const api = require('../../utils/api')

// 把后端距离（km 数值）拼成展示文本；缺失返回空串，调用方用空串判断不拼接（不显示 "-"）
function distanceText(value) {
  if (value === undefined || value === null) return ''
  return Number(value).toFixed(1) + ' km'
}

// 把爬升（m）拼成展示文本；缺失返回空串
function climbText(value) {
  if (value === undefined || value === null) return ''
  return '爬升 ' + Math.round(Number(value)) + ' m'
}

// 把 JS Date 按设备本地时区（北京 UTC+8）拆成 picker 用的 date(YYYY-MM-DD) 和 time(HH:mm)
function splitLocal(date) {
  var y = date.getFullYear()
  var m = String(date.getMonth() + 1).padStart(2, '0')
  var d = String(date.getDate()).padStart(2, '0')
  var hh = String(date.getHours()).padStart(2, '0')
  var mm = String(date.getMinutes()).padStart(2, '0')
  return { date: y + '-' + m + '-' + d, time: hh + ':' + mm }
}

// 把 picker 的本地 date + time 拼回 UTC ISO 字符串（后端按 UTC 存）。
// 用 new Date(y,m,d,h,min) 走设备本地时区，再 toISOString() 转 UTC，时区闭环：
// 用户在北京时间选"6月2日 14:30" → 存 UTC → 详情页 new Date 转回本地仍是 14:30。
function toIso(dateStr, timeStr) {
  var dp = dateStr.split('-')
  var tp = timeStr.split(':')
  var local = new Date(Number(dp[0]), Number(dp[1]) - 1, Number(dp[2]), Number(tp[0]), Number(tp[1]))
  return local.toISOString()
}

Page({
  data: {
    steps: ['route', 'details', 'publish'],
    currentStep: 'route',
    selectedSegmentId: null,
    selectedRouteBookId: null,
    selectedActivityId: null,
    selectedRouteName: '',
    segments: [],
    routeBooks: [],
    activities: [],
    // picker 显示用的本地时间分量（出发默认明天此刻、结束默认 +3h，onLoad 初始化）
    startDate: '',
    startTime: '',
    endDate: '',
    endTime: '',
    form: {
      start_time: '',
      estimated_end_time: '',
      meeting_point: '',
      pace_level: 'cruise',
      max_participants: 6,
      description: '',
    },
    paceOptions: [
      { value: 'relaxed', label: '休闲' },
      { value: 'cruise', label: '巡航' },
      { value: 'training', label: '训练' },
      { value: 'race', label: '强度' },
    ],
    paceLabel: '巡航',
    submitting: false,
  },

  onLoad: function () {
    this.initDefaultTime()
    this.loadRoutes()
  },

  // 初始化默认时间：出发明天此刻，结束 +3h。拆成 picker 分量并拼好 ISO 存进 form。
  initDefaultTime: function () {
    var start = new Date(Date.now() + 24 * 60 * 60 * 1000)
    var end = new Date(Date.now() + 27 * 60 * 60 * 1000)
    var s = splitLocal(start)
    var e = splitLocal(end)
    this.setData({
      startDate: s.date,
      startTime: s.time,
      endDate: e.date,
      endTime: e.time,
      'form.start_time': toIso(s.date, s.time),
      'form.estimated_end_time': toIso(e.date, e.time),
    })
  },

  loadRoutes: function () {
    var that = this
    // 三个来源各自独立兜底：某个接口失败（如用户还没建路书、或某接口抖动）不该
    // 让其他来源也消失。不用 Promise.all（任一 reject 全挂、赛段会跟着路书 404 一起空），
    // 改成每个各自 catch 成 null，能拿到几样显示几样。
    var safe = function (promise) {
      return promise.then(function (res) { return (res && res.items) || [] }).catch(function () { return null })
    }
    Promise.all([
      safe(api.getSegmentsList({ page: 1, page_size: 20 })),
      safe(api.getRouteBooksList({ mine: 1 })),
      safe(api.getRouteBookActivityCandidates()),
    ]).then(function (results) {
      if (results[0] === null && results[1] === null && results[2] === null) {
        wx.showToast({ title: '路线加载失败', icon: 'none' })
      }
      that.setData({
        segments: that.decorateItems(results[0] || [], 'segment'),
        routeBooks: that.decorateItems(results[1] || [], 'route_book'),
        activities: that.decorateItems(results[2] || [], 'activity'),
      })
    })
  },

  decorateItems: function (items, type) {
    return items.map(function (item) {
      var name = item.name || item.title || '未命名路线'
      var climb = item.climb !== undefined ? item.climb : item.elevation_gain
      // 距离和爬升缺失时不拼 "-"，只显示有值的部分（守"不显示占位符"规则）
      var meta = distanceText(item.distance)
      var ct = climbText(climb)
      if (ct) meta = meta ? meta + ' · ' + ct : ct
      return Object.assign({}, item, {
        type: type,
        displayName: name,
        displayMeta: meta,
      })
    })
  },

  selectRoute: function (event) {
    var type = event.currentTarget.dataset.type
    var id = Number(event.currentTarget.dataset.id)
    var name = event.currentTarget.dataset.name
    this.setData({
      selectedSegmentId: type === 'segment' ? id : null,
      selectedRouteBookId: type === 'route_book' ? id : null,
      selectedActivityId: type === 'activity' ? id : null,
      selectedRouteName: name,
    })
  },

  onStartDateChange: function (event) {
    var value = event.detail.value
    this.setData({ startDate: value, 'form.start_time': toIso(value, this.data.startTime) })
  },

  onStartTimeChange: function (event) {
    var value = event.detail.value
    this.setData({ startTime: value, 'form.start_time': toIso(this.data.startDate, value) })
  },

  onEndDateChange: function (event) {
    var value = event.detail.value
    this.setData({ endDate: value, 'form.estimated_end_time': toIso(value, this.data.endTime) })
  },

  onEndTimeChange: function (event) {
    var value = event.detail.value
    this.setData({ endTime: value, 'form.estimated_end_time': toIso(this.data.endDate, value) })
  },

  nextStep: function () {
    if (this.data.currentStep === 'route') {
      if (!this.data.selectedSegmentId && !this.data.selectedRouteBookId && !this.data.selectedActivityId) {
        wx.showToast({ title: '先选路线', icon: 'none' })
        return
      }
      this.setData({ currentStep: 'details' })
      return
    }
    if (this.data.currentStep === 'details') {
      if (!this.data.form.meeting_point) {
        wx.showToast({ title: '填写集合点', icon: 'none' })
        return
      }
      // 时间顺序前端先拦一次：结束必须晚于开始，免得到发布才被后端 422 退回
      if (new Date(this.data.form.estimated_end_time) <= new Date(this.data.form.start_time)) {
        wx.showToast({ title: '结束时间要晚于出发', icon: 'none' })
        return
      }
      this.setData({ currentStep: 'publish' })
    }
  },

  prevStep: function () {
    if (this.data.currentStep === 'publish') {
      this.setData({ currentStep: 'details' })
    } else if (this.data.currentStep === 'details') {
      this.setData({ currentStep: 'route' })
    }
  },

  updateField: function (event) {
    var field = event.currentTarget.dataset.field
    var value = event.detail.value
    var key = 'form.' + field
    this.setData({ [key]: value })
  },

  onPaceChange: function (event) {
    var index = Number(event.detail.value)
    var option = this.data.paceOptions[index]
    this.setData({ 'form.pace_level': option.value, paceLabel: option.label })
  },

  createOrUpdateDraft: function (payload) {
    return api.createMeetup(payload)
      .catch(function (err) {
        var detail = err && err.message
        if (err && err.code === 409 && detail && detail.code === 'draft_exists' && detail.existing_draft_id) {
          return api.updateMeetup(detail.existing_draft_id, payload)
        }
        return Promise.reject(err)
      })
  },

  onPublish: function () {
    var that = this
    if (this.data.submitting) return
    this.setData({ submitting: true })

    this.resolveRouteBookId()
      .then(function (routeBookId) {
        var payload = Object.assign({}, that.data.form, {
          segment_id: that.data.selectedSegmentId || null,
          route_book_id: routeBookId || that.data.selectedRouteBookId || null,
          max_participants: Number(that.data.form.max_participants),
        })
        return that.createOrUpdateDraft(payload)
      })
      .then(function (draft) {
        return api.publishMeetup(draft.id)
      })
      .then(function (meetup) {
        wx.redirectTo({ url: '/pages/meetup-detail/meetup-detail?id=' + meetup.id })
      })
      .catch(function (err) {
        wx.showToast({ title: (err && err.message) || '发布失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ submitting: false })
      })
  },

  resolveRouteBookId: function () {
    if (!this.data.selectedActivityId) {
      return Promise.resolve(null)
    }
    var name = this.data.selectedRouteName || '我的路线'
    return api.createRouteBookFromActivity(name, this.data.selectedActivityId)
      .then(function (routeBook) {
        return routeBook.id
      })
  },
})
