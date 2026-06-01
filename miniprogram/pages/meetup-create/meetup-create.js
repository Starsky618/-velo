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
    // 四步向导：选路线 → 填详情 → 加照片 → 确认发布。
    // 把"照片"插在 details 和 publish 之间，让发起人发布前就能给约骑配图，
    // 而不是等发布后再回详情页补——发布即图文齐全，对围观者更有吸引力。
    steps: ['route', 'details', 'media', 'publish'],
    currentStep: 'route',
    selectedSegmentId: null,
    selectedRouteBookId: null,
    selectedActivityId: null,
    selectedRouteName: '',
    segments: [],
    routeBooks: [],
    activities: [],
    // meetupId：进入"照片"步骤时存出来的草稿 id。
    // 为什么必须先有 id 才能加照片？因为上传接口是 /api/meetups/{id}/media，
    // 照片必须挂在一条已存在的约骑记录上。所以照片这一步的前提就是"草稿已落库拿到 id"。
    meetupId: null,
    generatedRouteBookId: null, // "从骑行生成"时建出的路书 id 缓存：同一活动多次保存草稿复用同一条，不重复建（防孤儿路书）
    savingDraft: false, // 存草稿进行中标记：防止 details→media 转场被连点两次重复建草稿
    mediaList: [], // 照片墙：每项含 url（拼好的可显示地址）+ isVideo
    mediaError: false, // 照片墙加载失败标记：true 时显示"加载失败"而非"还没有照片"，避免误导
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
      // 换了路线选择 → 作废上次"从骑行生成"缓存的路书 id，否则改选别的活动还会复用旧路书（指错）
      generatedRouteBookId: null,
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
      // details → media 这一跳是关键：照片必须挂在已落库的约骑上，所以这里先把草稿存出来拿到 id。
      // 存成功才放行进入"照片"步骤；存失败留在 details 让用户重试（saveDraft 内部已 toast）。
      this.saveDraft()
      return
    }
    if (this.data.currentStep === 'media') {
      // 照片可选，不强制必须传，直接进发布确认页
      this.setData({ currentStep: 'publish' })
    }
  },

  prevStep: function () {
    if (this.data.currentStep === 'publish') {
      this.setData({ currentStep: 'media' })
    } else if (this.data.currentStep === 'media') {
      this.setData({ currentStep: 'details' })
    } else if (this.data.currentStep === 'details') {
      this.setData({ currentStep: 'route' })
    }
  },

  // 把当前表单存成草稿（或更新已有草稿），成功后进入"照片"步骤并回显已有照片。
  // 设计要点：
  // 1）首次进入：调 createOrUpdateDraft（内部已处理 409 draft_exists → 转 updateMeetup 复用旧草稿）。
  // 2）已有 meetupId（用户从 media 退回 details 改了内容又前进）：直接 updateMeetup 复用同一条，
  //    不再重复建，避免每来回一次就产生一条新草稿。
  // 3）resolveRouteBookId：选的是"从骑行生成"时，要先把那条活动转成路书拿到 route_book_id。
  saveDraft: function () {
    var that = this
    if (this.data.savingDraft) return // 防连点重复建
    this.setData({ savingDraft: true })
    wx.showLoading({ title: '保存中', mask: true })

    this.resolveRouteBookId()
      .then(function (routeBookId) {
        var payload = Object.assign({}, that.data.form, {
          segment_id: that.data.selectedSegmentId || null,
          route_book_id: routeBookId || that.data.selectedRouteBookId || null,
          max_participants: Number(that.data.form.max_participants),
        })
        // 已有草稿 id → 复用更新；否则建新草稿
        if (that.data.meetupId) {
          return api.updateMeetup(that.data.meetupId, payload)
        }
        return that.createOrUpdateDraft(payload)
      })
      .then(function (draft) {
        // 进入照片步骤前先记下 id，再拉该草稿已有的照片（支持退回再进/复用旧草稿时回显）
        that.setData({ meetupId: draft.id, currentStep: 'media' })
        that.loadMedia()
      })
      .catch(function (err) {
        // 存失败：不进入下一步，留在 details 让用户改了重试
        wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
      })
      .finally(function () {
        wx.hideLoading()
        that.setData({ savingDraft: false })
      })
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
    // 草稿已在进入"照片"步骤时建好，这里只需发布。
    // 兜底：理论上走到 publish 必有 meetupId，缺失说明流程异常，直接报错不静默发空。
    if (!this.data.meetupId) {
      wx.showToast({ title: '草稿丢失，请退回重试', icon: 'none' })
      return
    }
    this.setData({ submitting: true })

    api.publishMeetup(this.data.meetupId)
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
    // 同一次"从骑行生成"已经建过路书就复用：否则用户从照片步退回改详情再前进，每次 saveDraft 都会
    // 重新 POST /api/route-books 建一条新路书，旧的变孤儿留在"我的路书"里污染数据（Codex 异源审抓的回归）。
    if (this.data.generatedRouteBookId) {
      return Promise.resolve(this.data.generatedRouteBookId)
    }
    var that = this
    var name = this.data.selectedRouteName || '我的路线'
    return api.createRouteBookFromActivity(name, this.data.selectedActivityId)
      .then(function (routeBook) {
        that.setData({ generatedRouteBookId: routeBook.id })
        return routeBook.id
      })
  },

  // —— 照片墙（镜像详情页逻辑：列表/上传/删除/预览）——
  // 拉当前草稿的所有媒体，拼成可显示 URL（baseUrl + /uploads/ + file_id，caddy 静态服务）。
  loadMedia: function () {
    var that = this
    if (!this.data.meetupId) return
    api.getMeetupMedia(this.data.meetupId)
      .then(function (list) {
        var base = (getApp().globalData && getApp().globalData.baseUrl) || ''
        that.setData({
          mediaError: false,
          mediaList: (list || []).map(function (m) {
            return Object.assign({}, m, { url: base + '/uploads/' + m.file_id, isVideo: m.type === 'video' })
          }),
        })
      })
      .catch(function (err) {
        // 加载失败不阻塞流程，但要让用户知道是"加载失败"而非"还没有照片"，避免误导（同详情页）
        console.error('照片墙加载失败', err)
        that.setData({ mediaError: true })
      })
  },

  // 微信选图/视频 → 逐个上传到当前草稿 → 刷新照片墙。
  // 用 Promise.all 并发上传，每个各自 catch 成 null（api.js 的 upload 已对 JSON.parse 做 try/catch
  // 兜底，保证每个 Promise 一定 settle，不会卡死 loading）；只要有一个失败就提示"部分上传失败"。
  onTapAddMedia: function () {
    var that = this
    if (!this.data.meetupId) return
    wx.chooseMedia({
      count: 9,
      mediaType: ['image', 'video'],
      success: function (res) {
        wx.showLoading({ title: '上传中', mask: true })
        var tasks = res.tempFiles.map(function (f) {
          return api.uploadMeetupMedia(that.data.meetupId, f.tempFilePath).catch(function () { return null })
        })
        Promise.all(tasks)
          .then(function (results) {
            if (results.some(function (r) { return r === null })) {
              wx.showToast({ title: '部分上传失败', icon: 'none' })
            }
            that.loadMedia()
          })
          .finally(function () {
            wx.hideLoading()
          })
      },
    })
  },

  onTapDeleteMedia: function (event) {
    var that = this
    var mediaId = event.currentTarget.dataset.id
    wx.showModal({
      title: '删除',
      content: '删除这张照片/视频？',
      success: function (modal) {
        if (!modal.confirm) return
        api.deleteMeetupMedia(that.data.meetupId, mediaId)
          .then(function () { that.loadMedia() })
          .catch(function (err) { wx.showToast({ title: (err && err.message) || '删除失败', icon: 'none' }) })
      },
    })
  },

  // 点图全屏预览（只在图片间预览，视频不进 previewImage）
  onTapPreviewMedia: function (event) {
    var url = event.currentTarget.dataset.url
    var images = this.data.mediaList.filter(function (m) { return !m.isVideo }).map(function (m) { return m.url })
    if (images.indexOf(url) >= 0) {
      wx.previewImage({ current: url, urls: images })
    }
  },
})
