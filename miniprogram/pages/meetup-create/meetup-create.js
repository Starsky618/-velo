const api = require('../../utils/api')
const { wgs84ToGcj02 } = require('../../utils/coords')
const mapTheme = require('../../utils/map-theme')

// 把不同来源的距离拼成展示文本。
// 赛段列表接口已经给公里；路书和"我的骑行"候选给米。
// 这里按来源换算，像看菜单先分清"斤"和"克"，不能只看数字大小猜单位。
function distanceText(value, type) {
  if (value === undefined || value === null) return ''
  var n = Number(value)
  if (!Number.isFinite(n)) return ''
  var km = type === 'segment' ? n : n / 1000
  return km.toFixed(1) + ' km'
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

// 把后端给的路书点 [[lon, lat], ...] 转成小程序 map 能画的红色路线。
// 后端存 WGS-84 是"地图原稿"，小程序显示要 GCJ-02 是"微信地图门牌号"；
// 这里像翻译门牌一样，只在展示前翻译，不改后端真相源。
function buildRoutePreview(points) {
  if (!Array.isArray(points) || points.length < 2) {
    return {
      routePreviewVisible: false,
      routePreviewPolylines: [],
      routePreviewMarkers: [],
      routePreviewIncludePoints: [],
    }
  }
  var mapPoints = []
  points.forEach(function (point) {
    if (!Array.isArray(point) || point.length < 2) return
    var lon = Number(point[0])
    var lat = Number(point[1])
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return
    var gcj = wgs84ToGcj02(lat, lon)
    mapPoints.push({ latitude: gcj[0], longitude: gcj[1] })
  })
  if (mapPoints.length < 2) {
    return {
      routePreviewVisible: false,
      routePreviewPolylines: [],
      routePreviewMarkers: [],
      routePreviewIncludePoints: [],
    }
  }
  var first = mapPoints[0]
  var last = mapPoints[mapPoints.length - 1]
  return {
    routePreviewVisible: true,
    routePreviewCenter: first,
    routePreviewIncludePoints: mapPoints,
    routePreviewMarkers: [
      { id: 1, latitude: first.latitude, longitude: first.longitude, title: '起点' },
      { id: 2, latitude: last.latitude, longitude: last.longitude, title: '终点' },
    ],
    routePreviewPolylines: mapTheme.buildRoutePreviewPolylines(mapPoints),
  }
}

// pace_level → 推荐功率 / 预计均速 展示对照表（纯前端，不入库 / 占位区间 Tim 可调）
const PACE_DISPLAY = {
  relaxed: { pace_label: '轻松慢骑', recommended_power_label: '不限功率', average_speed_range: '15-18 km/h' },
  cruise: { pace_label: '稳爬不竞速', recommended_power_label: 'FTP 160W+ 更舒服', average_speed_range: '17-22 km/h' },
  training: { pace_label: '高强度拉练', recommended_power_label: 'FTP 220W+', average_speed_range: '25-30 km/h' },
  race: { pace_label: '竞速冲刺', recommended_power_label: 'FTP 280W+', average_speed_range: '30+ km/h' },
}

// 适合谁标签（6 枚举，和后端白名单一致）
const AUDIENCE_OPTIONS = [
  { value: 'climb_steady', label: '稳爬不竞速' },
  { value: 'high_intensity', label: '高强度拉练' },
  { value: 'leisure', label: '休闲骑游' },
  { value: 'photography', label: '摄影打卡' },
  { value: 'female_friendly', label: '女性友好' },
  { value: 'newbie_caution', label: '新手慎选' },
]

// velo 安全提示模板（前端常量，发起人一键填入后还能改）
const SAFETY_TEMPLATES = [
  '头盔必戴 · 遵守交规 · 量力而行',
  '新手友好 · 全程收队 · 不拉爆',
  '强度拉练 · 请自备补给 · 跟不上自行返回',
  '山路多弯 · 控制下坡车速 · 保持车距',
]

Page({
  data: Object.assign({}, mapTheme.getPaperMapData(), {
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
    tencentStart: null,
    tencentEnd: null,
    tencentStartText: '选择起点',
    tencentEndText: '选择终点',
    creatingTencentRoute: false,
    routePreviewVisible: false,
    routePreviewCenter: { latitude: 37.8706, longitude: 112.5489 },
    routePreviewPolylines: [],
    routePreviewMarkers: [],
    routePreviewIncludePoints: [],
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
      supply_point: '',
      audience_tags: [],
      visibility: 'public',
      eligibility_note: '',
      safety_note: SAFETY_TEMPLATES[0],
    },
    paceOptions: [
      { value: 'relaxed', label: '休闲' },
      { value: 'cruise', label: '巡航' },
      { value: 'training', label: '训练' },
      { value: 'race', label: '强度' },
    ],
    paceLabel: '巡航',
    // —— 发布前总览（图二）用 ——
    // audienceOptions 带 selected 标志：WXML 不支持 .indexOf()，选中态必须在 JS 侧算
    audienceOptions: AUDIENCE_OPTIONS.map(function (o) { return { value: o.value, label: o.label, selected: false } }),
    safetyTemplates: SAFETY_TEMPLATES,
    visibilityOptions: [
      { value: 'public', label: '本城可见' },
      { value: 'invite_only', label: '私圈可见' },
    ],
    invitees: [], // 已加入骑友（进 preview 时拉）
    shareToken: '', // 私圈分享口令（后端只回 creator / onShareAppMessage 用）
    estimatedDurationText: '',
    registrationDeadlineLabel: '', // 报名截止 = 出发前 30 分钟（派生）
    recommendedPowerLabel: PACE_DISPLAY.cruise.recommended_power_label,
    averageSpeedRange: PACE_DISPLAY.cruise.average_speed_range,
    submitting: false,
  }),

  onLoad: function () {
    this.initDefaultTime()
    this.loadRoutes()
    this.restoreDraft()
  },

  onShow: function () {
    this.consumePendingMapPoint()
  },

  // 退出重进恢复草稿：每用户唯一 DRAFT，拉 my-draft 回填表单 + 照片 + 路线预览
  restoreDraft: function () {
    var that = this
    api.getMyMeetupDraft().then(function (draft) {
      if (!draft) return
      var start = splitLocal(new Date(draft.start_time))
      var end = splitLocal(new Date(draft.estimated_end_time))
      var paceLabel = '巡航'
      that.data.paceOptions.forEach(function (o) {
        if (o.value === draft.pace_level) paceLabel = o.label
      })
      that.setData({
        meetupId: draft.id,
        selectedSegmentId: draft.segment_id || null,
        selectedRouteBookId: draft.route_book_id || null,
        selectedRouteName: draft.snapshot_route_name || '',
        startDate: start.date,
        startTime: start.time,
        endDate: end.date,
        endTime: end.time,
        paceLabel: paceLabel,
        shareToken: draft.share_token || '',
        audienceOptions: that.syncAudienceOptions(draft.audience_tags || []),
        form: {
          start_time: draft.start_time,
          estimated_end_time: draft.estimated_end_time,
          meeting_point: draft.meeting_point || '',
          pace_level: draft.pace_level || 'cruise',
          max_participants: draft.max_participants || 6,
          description: draft.description || '',
          supply_point: draft.supply_point || '',
          audience_tags: draft.audience_tags || [],
          visibility: draft.visibility || 'public',
          eligibility_note: draft.eligibility_note || '',
          safety_note: draft.safety_note || SAFETY_TEMPLATES[0],
        },
      })
      that.updatePreviewDerived()
      that.loadMedia()
      that.restoreRoutePreview(draft.route_book_id)
    }).catch(function () {
      // 恢复草稿失败不阻塞新建流程，用户照常从头建
    })
  },

  // 草稿恢复时按 route_book_id 拉路书重画地图预览（path 预览图，非导航）
  restoreRoutePreview: function (routeBookId) {
    var that = this
    if (!routeBookId || !api.getRouteBookDetail) return
    api.getRouteBookDetail(routeBookId).then(function (routeBook) {
      that.setData(buildRoutePreview(routeBook.preview_points))
    }).catch(function () {})
  },

  // 微信原生转发邀请：invite_only 带 share_token，朋友点开链接才能进，猜 id 进不来
  onShareAppMessage: function () {
    var path = '/pages/meetup-detail/meetup-detail?id=' + this.data.meetupId
    if (this.data.form.visibility === 'invite_only' && this.data.shareToken) {
      path += '&token=' + encodeURIComponent(this.data.shareToken)
    }
    return {
      title: this.data.selectedRouteName || 'VELO 约骑',
      path: path,
    }
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
      var meta = distanceText(item.distance, type)
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
    var index = Number(event.currentTarget.dataset.index)
    var list = type === 'route_book' ? this.data.routeBooks : []
    var routePreview = type === 'route_book' ? buildRoutePreview((list[index] || {}).preview_points) : buildRoutePreview([])
    this.setData(Object.assign({
      selectedSegmentId: type === 'segment' ? id : null,
      selectedRouteBookId: type === 'route_book' ? id : null,
      selectedActivityId: type === 'activity' ? id : null,
      selectedRouteName: name,
      // 换了路线选择 → 作废上次"从骑行生成"缓存的路书 id，否则改选别的活动还会复用旧路书（指错）
      generatedRouteBookId: null,
    }, routePreview))
  },

  onTapChooseTencentStart: function () {
    this.chooseTencentPoint('start')
  },

  onTapChooseTencentEnd: function () {
    this.chooseTencentPoint('end')
  },

  chooseTencentPoint: function (kind) {
    var current = kind === 'start' ? this.data.tencentStart : this.data.tencentEnd
    var url = '/pages/map-picker/map-picker?kind=' + kind
    if (current) {
      url += '&latitude=' + encodeURIComponent(current.latitude)
      url += '&longitude=' + encodeURIComponent(current.longitude)
      url += '&name=' + encodeURIComponent(current.name || '')
    }
    wx.navigateTo({ url: url })
  },

  consumePendingMapPoint: function () {
    var app = getApp()
    var point = app && app.globalData && app.globalData.pendingMapPoint
    if (!point) return
    app.globalData.pendingMapPoint = null
    var lat = Number(point.latitude)
    var lon = Number(point.longitude)
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      wx.showToast({ title: '选点失败', icon: 'none' })
      return
    }
    var selected = {
      name: point.name || (point.kind === 'start' ? '路线起点' : '路线终点'),
      address: '',
      latitude: lat,
      longitude: lon,
    }
    if (point.kind === 'start') {
      this.setData({
        tencentStart: selected,
        tencentStartText: selected.name,
      })
      return
    }
    if (point.kind === 'end') {
      this.setData({
        tencentEnd: selected,
        tencentEndText: selected.name,
      })
    }
  },

  onTapCreateTencentRoute: function () {
    var that = this
    var start = this.data.tencentStart
    var end = this.data.tencentEnd
    if (!start || !end) {
      wx.showToast({ title: '先选起终点', icon: 'none' })
      return
    }
    if (this.data.creatingTencentRoute) return
    var name = start.name + ' → ' + end.name
    this.setData({ creatingTencentRoute: true })
    wx.showLoading({ title: '生成中', mask: true })
    api.createRouteBookFromTencentDirection({
      name: name,
      from_lat: start.latitude,
      from_lon: start.longitude,
      to_lat: end.latitude,
      to_lon: end.longitude,
    }).then(function (routeBook) {
      var decorated = that.decorateItems([routeBook], 'route_book')[0]
      that.setData(Object.assign({
        routeBooks: [decorated].concat(that.data.routeBooks),
        selectedSegmentId: null,
        selectedActivityId: null,
        selectedRouteBookId: routeBook.id,
        selectedRouteName: decorated.displayName,
        generatedRouteBookId: null,
      }, buildRoutePreview(decorated.preview_points)))
      wx.showToast({ title: '已生成路线', icon: 'success' })
    }).catch(function (err) {
      var message = '生成失败'
      if (err && err.code === 503) {
        message = '路线服务暂不可用'
      } else if (err && err.message) {
        message = err.message
      }
      wx.showToast({ title: message, icon: 'none' })
    }).finally(function () {
      wx.hideLoading()
      that.setData({ creatingTencentRoute: false })
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
    if (this.data.currentStep === 'preview') {
      this.setData({ currentStep: 'publish' })
    } else if (this.data.currentStep === 'publish') {
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

  // 算图二的派生展示：预计时长（结束-出发）+ 推荐功率/均速（按节奏档位查表）
  updatePreviewDerived: function () {
    var pace = PACE_DISPLAY[this.data.form.pace_level] || PACE_DISPLAY.cruise
    var start = new Date(this.data.form.start_time)
    var end = new Date(this.data.form.estimated_end_time)
    var duration = ''
    if (Number.isFinite(start.getTime()) && Number.isFinite(end.getTime()) && end > start) {
      var minutes = Math.round((end - start) / 60000)
      duration = Math.floor(minutes / 60) + ':' + String(minutes % 60).padStart(2, '0')
    }
    // 报名截止 = 出发前 30 分钟（项目既有截止线），格式化成本地"周X HH:mm 截止"
    var deadlineText = ''
    if (Number.isFinite(start.getTime())) {
      var dl = new Date(start.getTime() - 30 * 60000)
      var week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][dl.getDay()]
      deadlineText = week + ' ' + String(dl.getHours()).padStart(2, '0') + ':' + String(dl.getMinutes()).padStart(2, '0') + ' 截止'
    }
    this.setData({
      recommendedPowerLabel: pace.recommended_power_label,
      averageSpeedRange: pace.average_speed_range,
      estimatedDurationText: duration,
      registrationDeadlineLabel: deadlineText,
    })
  },

  // publish 步点"发布约骑" → 先把草稿（含已填字段）存一次拿到 share_token，再进图二总览
  onTapGoPreview: function () {
    var that = this
    if (!this.data.meetupId) {
      wx.showToast({ title: '草稿丢失，请退回重试', icon: 'none' })
      return
    }
    this.updatePreviewDerived()
    api.updateMeetup(this.data.meetupId, Object.assign({}, this.data.form, {
      max_participants: Number(this.data.form.max_participants),
    })).then(function (draft) {
      that.setData({
        currentStep: 'preview',
        meetupId: draft.id,
        shareToken: draft.share_token || that.data.shareToken || '',
      })
      // 拉已加入骑友（getMeetupParticipants 在 Task5 才加，没有就跳过不报错）
      if (api.getMeetupParticipants) {
        api.getMeetupParticipants(draft.id).then(function (items) {
          that.setData({ invitees: items || [] })
        }).catch(function () {
          that.setData({ invitees: [] })
        })
      }
    }).catch(function (err) {
      wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
    })
  },

  // WXML 不支持 .indexOf()，"哪些标签选中"在 JS 算成 selected 标志
  syncAudienceOptions: function (tags) {
    var chosen = tags || []
    return AUDIENCE_OPTIONS.map(function (o) {
      return { value: o.value, label: o.label, selected: chosen.indexOf(o.value) >= 0 }
    })
  },

  toggleAudienceTag: function (event) {
    var value = event.currentTarget.dataset.value
    var tags = (this.data.form.audience_tags || []).slice()
    var index = tags.indexOf(value)
    if (index >= 0) {
      tags.splice(index, 1)
    } else {
      tags.push(value)
    }
    this.setData({ 'form.audience_tags': tags, audienceOptions: this.syncAudienceOptions(tags) })
  },

  onVisibilityChange: function (event) {
    var index = Number(event.detail.value)
    var option = this.data.visibilityOptions[index] || this.data.visibilityOptions[0]
    this.setData({ 'form.visibility': option.value })
  },

  applySafetyTemplate: function (event) {
    var index = Number(event.currentTarget.dataset.index)
    this.setData({ 'form.safety_note': this.data.safetyTemplates[index] || this.data.safetyTemplates[0] })
  },

  // 确认并发布：把图二设的 social 字段再存一次 → 发布 → 跳详情
  onConfirmPublish: function () {
    var that = this
    if (this.data.submitting) return
    if (!this.data.meetupId) {
      wx.showToast({ title: '草稿丢失，请退回重试', icon: 'none' })
      return
    }
    this.setData({ submitting: true })
    api.updateMeetup(this.data.meetupId, {
      audience_tags: this.data.form.audience_tags,
      visibility: this.data.form.visibility,
      eligibility_note: this.data.form.eligibility_note,
      safety_note: this.data.form.safety_note,
    }).then(function () {
      return api.publishMeetup(that.data.meetupId)
    }).then(function (meetup) {
      wx.redirectTo({ url: '/pages/meetup-detail/meetup-detail?id=' + meetup.id })
    }).catch(function (err) {
      wx.showToast({ title: (err && err.message) || '发布失败', icon: 'none' })
    }).finally(function () {
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
