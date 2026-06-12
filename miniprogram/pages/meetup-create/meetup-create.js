const api = require('../../utils/api')
const { wgs84ToGcj02 } = require('../../utils/coords')
const mapTheme = require('../../utils/map-theme')
const routeThumb = require('../../utils/route-thumb')
const routeMapNav = require('../../utils/route-map-nav')

const TENCENT_POINT_NAME_MAX_LENGTH = 40
const TENCENT_ROUTE_NAME_MAX_LENGTH = 80
const MEETUP_PUBLISH_CUTOFF_BUFFER_MS = 30 * 60 * 1000 + 30 * 1000

function normalizeShortText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function limitText(value, maxLength) {
  var text = normalizeShortText(value)
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength)
}

function limitTencentRouteName(value) {
  return limitText(value, TENCENT_ROUTE_NAME_MAX_LENGTH)
}

function formatTencentRouteError(err) {
  if (err && err.code === 503) return '路线服务暂不可用'
  if (err && err.code === 422) return '生成失败，请检查路线名称和起终点'
  if (err && typeof err.message === 'string' && err.message) return err.message
  return '生成失败'
}

function formatMeetupPublishError(err) {
  if (err && err.code === 410 && err.message === 'meetup cutoff passed') {
    return '离出发太近，不能发布'
  }
  if (err && typeof err.message === 'string' && err.message) return err.message
  return '发布失败'
}

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

// 推荐功率 / 预计均速的可选区间（Tim 2026-06-13 拍：仪表盘式挑区间，不让骑友手打）。
// ⚠ PACE_DISPLAY 的默认值必须是下面两个数组里的成员，否则 picker 定位不到当前档
const POWER_OPTIONS = ['不限功率', '120-140W', '140-160W', '160-180W', '180-200W', '200-220W', '220-250W', '250W+']
const SPEED_OPTIONS = ['15-18 km/h', '18-21 km/h', '21-24 km/h', '24-27 km/h', '27-30 km/h', '30+ km/h']

// pace_level → 推荐功率 / 预计均速 默认档对照表（纯前端，不入库 / 区间值 Tim 可调）
const PACE_DISPLAY = {
  relaxed: { pace_label: '轻松慢骑', recommended_power_label: '不限功率', average_speed_range: '15-18 km/h' },
  cruise: { pace_label: '稳爬不竞速', recommended_power_label: '160-180W', average_speed_range: '21-24 km/h' },
  training: { pace_label: '高强度拉练', recommended_power_label: '200-220W', average_speed_range: '24-27 km/h' },
  race: { pace_label: '竞速冲刺', recommended_power_label: '250W+', average_speed_range: '30+ km/h' },
}

// 给 picker 定位当前档：找不到（老草稿存过自由文本）就退到 0，不炸
function findOptionIndex(options, value) {
  var index = options.indexOf(value)
  return index >= 0 ? index : 0
}

function findPaceIndex(options, value) {
  var index = 0
  options.forEach(function (option, i) {
    if (option.value === value) index = i
  })
  return index
}

// 适合谁标签（6 枚举，和后端白名单一致）
const AUDIENCE_OPTIONS = [
  { value: 'climb_steady', label: '稳爬不竞速', icon: '/assets/icons/meetup/mountain.svg' },
  { value: 'high_intensity', label: '高强度拉练', icon: '/assets/icons/meetup/zap.svg' },
  { value: 'leisure', label: '休闲骑游', icon: '/assets/icons/meetup/coffee.svg' },
  { value: 'photography', label: '摄影打卡', icon: '/assets/icons/meetup/camera.svg' },
  { value: 'female_friendly', label: '女性友好', icon: '/assets/icons/meetup/venus.svg' },
  { value: 'newbie_caution', label: '新手慎选', icon: '/assets/icons/meetup/shield-alert.svg' },
]

// velo 安全提示模板（前端常量，发起人一键填入后还能改）
const SAFETY_TEMPLATES = [
  '头盔必戴 · 遵守交规 · 量力而行',
  '新手友好 · 全程收队 · 不拉爆',
  '强度拉练 · 请自备补给 · 跟不上自行返回',
  '山路多弯 · 控制下坡车速 · 保持车距',
]

Page({
  data: {
    // 四步向导：选路线 → 填详情 → 加照片 → 确认发布。
    // 把"照片"插在 details 和 publish 之间，让发起人发布前就能给约骑配图，
    // 而不是等发布后再回详情页补——发布即图文齐全，对围观者更有吸引力。
    steps: ['route', 'edit', 'confirm'], // 选路线 → 图二就地编辑 → 图一总览确认（2026-06 Tim 拍的新流程）
    currentStep: 'route',
    selectedSegmentId: null,
    selectedRouteBookId: null,
    selectedActivityId: null,
    selectedRouteName: '',
    segments: [],
    officialRouteBooks: [],
    routeBooks: [],
    activities: [],
    tencentStart: null,
    tencentEnd: null,
    tencentStartText: '选择起点',
    tencentEndText: '选择终点',
    tencentRouteName: '',
    tencentRouteNameEdited: false,
    creatingTencentRoute: false,
    routePreviewVisible: false,
    routePreviewCenter: { latitude: 37.8706, longitude: 112.5489 },
    routePreviewPolylines: [],
    routePreviewMarkers: [],
    routePreviewIncludePoints: [],
    favoritePlaces: [],
    selectedMeetingPoint: null,
    // meetupId：进入"照片"步骤时存出来的草稿 id。
    // 为什么必须先有 id 才能加照片？因为上传接口是 /api/meetups/{id}/media，
    // 照片必须挂在一条已存在的约骑记录上。所以照片这一步的前提就是"草稿已落库拿到 id"。
    meetupId: null,
    generatedRouteBookId: null, // "从骑行生成"时建出的路书 id 缓存：同一活动多次保存草稿复用同一条，不重复建（防孤儿路书）
    savingDraft: false, // 存草稿进行中标记：防止 details→media 转场被连点两次重复建草稿
    mediaList: [], // 照片墙：每项含 url（拼好的可显示地址）+ isVideo
    mediaError: false, // 照片墙加载失败标记：true 时显示"加载失败"而非"还没有照片"，避免误导
    // picker 显示用的本地时间分量（出发默认明天此刻、结束默认 +3h，onLoad 初始化）
    minStartDate: '',
    startDate: '',
    startTime: '',
    endDate: '',
    endTime: '',
    form: {
      start_time: '',
      estimated_end_time: '',
      meeting_point: '',
      pace_level: 'cruise',
      recommended_power_label: PACE_DISPLAY.cruise.recommended_power_label,
      average_speed_range: PACE_DISPLAY.cruise.average_speed_range,
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
    paceIndex: 1,
    paceLabel: '巡航',
    // 功率/均速区间选择器（不手打）：选项固定、索引由 updatePreviewDerived 对齐当前值
    powerOptions: POWER_OPTIONS,
    speedOptions: SPEED_OPTIONS,
    powerIndex: findOptionIndex(POWER_OPTIONS, PACE_DISPLAY.cruise.recommended_power_label),
    speedIndex: findOptionIndex(SPEED_OPTIONS, PACE_DISPLAY.cruise.average_speed_range),
    // —— 发布前总览（图二）用 ——
    // audienceOptions 带 selected 标志：WXML 不支持 .indexOf()，选中态必须在 JS 侧算
    audienceOptions: AUDIENCE_OPTIONS.map(function (o) { return { value: o.value, label: o.label, icon: o.icon, selected: false } }),
    safetyTemplates: SAFETY_TEMPLATES,
    visibilityOptions: [
      { value: 'public', label: '本城可见' },
      { value: 'invite_only', label: '私圈可见' },
    ],
    invitees: [], // 已加入骑友（进 preview 时拉）
    shareToken: '', // 私圈分享口令（后端只回 creator / onShareAppMessage 用）
    estimatedDurationText: '',
    routeDistanceText: '', // 总览页路线卡距离(km，进 preview 时从草稿快照填)
    routeClimbText: '',    // 总览页路线卡爬升(m)
    registrationDeadlineLabel: '', // 报名截止 = 出发前 30 分钟（派生）
    recommendedPowerLabel: PACE_DISPLAY.cruise.recommended_power_label,
    averageSpeedRange: PACE_DISPLAY.cruise.average_speed_range,
    submitting: false,
    // 总览页两个展示行（报名门槛 / 安全提示）的"是否展开编辑"开关。
    // 视觉照原型是只读展示行，但发起人得能改 → 点行翻成 true 露出 textarea，再点收起。
    // 类比：像手机设置里某一行点一下才滑出输入框，平时只显示当前值，界面更干净。
    pvEditGate: false,
    pvEditSafety: false,
  },

  onLoad: function (options) {
    var routeBookId = Number(options && options.route_book_id)
    if (!Number.isFinite(routeBookId) || routeBookId <= 0) routeBookId = null
    this.initDefaultTime()
    this.loadFavoritePlaces()
    this.loadRoutes()
    this.restoreDraft(routeBookId)
  },

  onShow: function () {
    this.refreshMinStartDate()
    this.consumePendingMapPoint()
  },

  // 退出重进恢复草稿：每用户唯一 DRAFT，拉 my-draft 回填表单 + 照片 + 路线预览
  restoreDraft: function (routeBookId) {
    var that = this
    api.getMyMeetupDraft().then(function (draft) {
      if (!draft) {
        if (routeBookId) that.applyRouteBookParam(routeBookId)
        return
      }
      var start = splitLocal(new Date(draft.start_time))
      var end = splitLocal(new Date(draft.estimated_end_time))
      var paceIndex = findPaceIndex(that.data.paceOptions, draft.pace_level || 'cruise')
      var paceLabel = that.data.paceOptions[paceIndex].label
      var pace = PACE_DISPLAY[draft.pace_level || 'cruise'] || PACE_DISPLAY.cruise
      that.setData({
        meetupId: draft.id,
        selectedSegmentId: draft.segment_id || null,
        selectedRouteBookId: draft.route_book_id || null,
        selectedRouteName: draft.snapshot_route_name || '',
        startDate: start.date,
        startTime: start.time,
        endDate: end.date,
        endTime: end.time,
        paceIndex: paceIndex,
        paceLabel: paceLabel,
        shareToken: draft.share_token || '',
        audienceOptions: that.syncAudienceOptions(draft.audience_tags || []),
        form: {
          start_time: draft.start_time,
          estimated_end_time: draft.estimated_end_time,
          meeting_point: draft.meeting_point || '',
          pace_level: draft.pace_level || 'cruise',
          recommended_power_label: draft.recommended_power_label || pace.recommended_power_label,
          average_speed_range: draft.average_speed_range || pace.average_speed_range,
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
      if (routeBookId) {
        // 参数优先覆盖草稿路线：用户刚从路线详情点进来，显式意图比上次没填完的草稿更可信。
        that.applyRouteBookParam(routeBookId)
      } else {
        that.restoreRoutePreview(draft.route_book_id)
      }
    }).catch(function () {
      // 恢复草稿失败不阻塞新建流程，用户照常从头建
      if (routeBookId) that.applyRouteBookParam(routeBookId)
    })
  },

  // 草稿恢复时按 route_book_id 拉路书重画地图预览（path 预览图，非导航）
  restoreRoutePreview: function (routeBookId) {
    var that = this
    if (!routeBookId || !api.getRouteBookDetail) return Promise.resolve(null)
    return api.getRouteBookDetail(routeBookId).then(function (routeBook) {
      that.setData(buildRoutePreview(routeBook.preview_points), function () {
        that.drawMainRoutePreview()
        that.drawStepThumb()
      })
      return routeBook
    }).catch(function () {
      // 拉路书失败就清空预览，别残留上一条路线的图（视觉状态不一致）
      that.setData(buildRoutePreview([]))
      return null
    })
  },

  // 编辑步 / 确认步左上角的轨迹缩略线：按当前步挑对应 canvas 画。
  // 幂等：状态不满足就静默返回，所以所有"可能改了步骤或路线"的地方都能放心调。
  // setTimeout 兜底 canvas 初始化（同路线详情页海拔缩略图 pattern，陷阱 #17）。
  // ⚠ 这里的 px 尺寸 = wxss 里 .route-thumb-canvas 的 rpx ÷ 2，改一处必须同步另一处
  drawStepThumb: function () {
    var that = this
    if (!this.data.routePreviewVisible) return
    var step = this.data.currentStep
    if (step !== 'edit' && step !== 'confirm') return
    var canvasId = step === 'edit' ? 'route-thumb-edit' : 'route-thumb-confirm'
    var size = step === 'edit' ? { width: 60, height: 52 } : { width: 80, height: 66 }
    setTimeout(function () {
      routeThumb.drawRouteThumb(canvasId, that.data.routePreviewIncludePoints, {
        width: size.width,
        height: size.height,
        lineWidth: 2,
      })
    }, 120)
  },

  // 第 1 步生成路线后的大预览图：这是展示卡，不需要原生地图拖动。
  // 自绘浅色纸面 + 橙色轨迹，真机上不会再露出腾讯默认导航底图。
  drawMainRoutePreview: function () {
    var that = this
    if (!this.data.routePreviewVisible || this.data.currentStep !== 'route') return
    setTimeout(function () {
      routeThumb.drawRouteThumb('route-preview-main', that.data.routePreviewIncludePoints, {
        width: 323,
        height: 180,
        lineWidth: 4,
        dotR: 6,
        paper: true,
      })
    }, 120)
  },

  applyRouteBookParam: function (routeBookId) {
    var that = this
    this.setData({
      selectedSegmentId: null,
      selectedRouteBookId: routeBookId,
      selectedActivityId: null,
      selectedRouteName: '已选路线',
      generatedRouteBookId: null,
      // 从路线详情"约骑这条路线"带参进来 = 路线已经定了（Tim 2026-06-11 拍），
      // 直奔编辑页填时间/集合点，不让用户再看一遍选路线步；想换路线点"上一步"回去
      currentStep: 'edit',
    })
    return this.restoreRoutePreview(routeBookId).then(function (routeBook) {
      if (!routeBook) return
      that.setData({ selectedRouteName: routeBook.name || '已选路线' })
    })
  },

  // 微信原生转发邀请：invite_only 带 share_token，朋友点开链接才能进，猜 id 进不来
  onShareAppMessage: function () {
    var path = '/pages/meetup-detail/meetup-detail?id=' + this.data.meetupId
    if (this.data.form.visibility === 'invite_only' && this.data.shareToken) {
      path += '&token=' + encodeURIComponent(this.data.shareToken)
    }
    path += '&source=share_card'
    return {
      title: this.data.selectedRouteName || 'VELO 约骑',
      path: path,
    }
  },

  // 初始化默认时间：出发明天此刻，结束 +3h。拆成 picker 分量并拼好 ISO 存进 form。
  initDefaultTime: function () {
    var today = splitLocal(new Date())
    var start = new Date(Date.now() + 24 * 60 * 60 * 1000)
    var end = new Date(Date.now() + 27 * 60 * 60 * 1000)
    var s = splitLocal(start)
    var e = splitLocal(end)
    this.setData({
      minStartDate: today.date,
      startDate: s.date,
      startTime: s.time,
      endDate: e.date,
      endTime: e.time,
      'form.start_time': toIso(s.date, s.time),
      'form.estimated_end_time': toIso(e.date, e.time),
    })
  },

  refreshMinStartDate: function () {
    this.setData({ minStartDate: splitLocal(new Date()).date })
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
      safe(api.getRouteBooksList({ official: 1 })),
      safe(api.getRouteBooksList({ mine: 1 })),
      safe(api.getRouteBookActivityCandidates()),
    ]).then(function (results) {
      if (results[0] === null && results[1] === null && results[2] === null && results[3] === null) {
        wx.showToast({ title: '路线加载失败', icon: 'none' })
      }
      that.setData({
        segments: that.decorateItems(results[0] || [], 'segment'),
        officialRouteBooks: that.decorateItems(results[1] || [], 'route_book'),
        routeBooks: that.decorateItems(results[2] || [], 'route_book'),
        activities: that.decorateItems(results[3] || [], 'activity'),
      })
    })
  },

  loadFavoritePlaces: function () {
    var that = this
    if (!api.getMeetupFavoritePlaces) return
    api.getMeetupFavoritePlaces()
      .then(function (places) {
        that.setData({ favoritePlaces: places || [] })
      })
      .catch(function () {
        that.setData({ favoritePlaces: [] })
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
    var source = event.currentTarget.dataset.source
    var list = type === 'route_book'
      ? (source === 'official' ? this.data.officialRouteBooks : this.data.routeBooks)
      : []
    var routePreview = type === 'route_book' ? buildRoutePreview((list[index] || {}).preview_points) : buildRoutePreview([])
    this.setData(Object.assign({
      selectedSegmentId: type === 'segment' ? id : null,
      selectedRouteBookId: type === 'route_book' ? id : null,
      selectedActivityId: type === 'activity' ? id : null,
      selectedRouteName: name,
      // 换了路线选择 → 作废上次"从骑行生成"缓存的路书 id，否则改选别的活动还会复用旧路书（指错）
      generatedRouteBookId: null,
    }, routePreview), this.drawMainRoutePreview.bind(this))
  },

  onTapChooseTencentStart: function () {
    this.chooseTencentPoint('start')
  },

  onTapChooseTencentEnd: function () {
    this.chooseTencentPoint('end')
  },

  onTapChooseMeetingPoint: function () {
    var url = '/pages/map-picker/map-picker?kind=meeting'
    if (this.data.form.meeting_point) {
      url += '&name=' + encodeURIComponent(this.data.form.meeting_point)
    }
    if (this.data.selectedMeetingPoint) {
      url += '&latitude=' + encodeURIComponent(this.data.selectedMeetingPoint.latitude)
      url += '&longitude=' + encodeURIComponent(this.data.selectedMeetingPoint.longitude)
      url += '&coordinate_system=' + encodeURIComponent(this.data.selectedMeetingPoint.coordinate_system || 'wgs84')
      url += '&address=' + encodeURIComponent(this.data.selectedMeetingPoint.address || '')
    }
    wx.navigateTo({ url: url })
  },

  applyFavoritePlace: function (event) {
    var index = Number(event.currentTarget.dataset.index)
    var place = this.data.favoritePlaces[index]
    if (!place) return
    this.setData({
      selectedMeetingPoint: Object.assign({}, place, { coordinate_system: 'wgs84' }),
      'form.meeting_point': place.name,
    })
  },

  saveMeetingPointAsFavorite: function () {
    var that = this
    var point = this.data.selectedMeetingPoint
    var name = normalizeShortText(this.data.form.meeting_point)
    if (!name || !point) {
      wx.showToast({ title: '先用地图选择集合点', icon: 'none' })
      return
    }
    api.saveMeetupFavoritePlace({
      name: name,
      address: point.address || '',
      latitude: point.latitude,
      longitude: point.longitude,
      coordinate_system: point.coordinate_system || 'wgs84',
    }).then(function () {
      wx.showToast({ title: '已保存常用点', icon: 'success' })
      that.loadFavoritePlaces()
    }).catch(function (err) {
      wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
    })
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
      name: limitText(point.name || (point.kind === 'meeting' ? '集合点' : (point.kind === 'start' ? '路线起点' : '路线终点')), TENCENT_POINT_NAME_MAX_LENGTH),
      address: point.address || '',
      latitude: lat,
      longitude: lon,
      coordinate_system: point.coordinate_system || 'gcj02',
    }
    if (point.kind === 'meeting') {
      this.setData({
        selectedMeetingPoint: selected,
        'form.meeting_point': selected.name,
      })
      return
    }
    if (point.kind === 'start') {
      this.setData({
        tencentStart: selected,
        tencentStartText: selected.name,
      }, this.syncTencentRouteNameFromPoints.bind(this))
      return
    }
    if (point.kind === 'end') {
      this.setData({
        tencentEnd: selected,
        tencentEndText: selected.name,
      }, this.syncTencentRouteNameFromPoints.bind(this))
    }
  },

  buildTencentRouteFallbackName: function () {
    var start = this.data.tencentStart
    var end = this.data.tencentEnd
    if (start && end) return limitTencentRouteName(start.name + ' → ' + end.name)
    return ''
  },

  syncTencentRouteNameFromPoints: function () {
    if (this.data.tencentRouteNameEdited) return
    var fallbackName = this.buildTencentRouteFallbackName()
    if (fallbackName) this.setData({ tencentRouteName: fallbackName })
  },

  onTencentRouteNameInput: function (event) {
    var value = limitTencentRouteName(event.detail.value || '')
    this.setData({
      tencentRouteName: value,
      tencentRouteNameEdited: Boolean(String(value).trim()),
    })
  },

  buildTencentRouteName: function () {
    var typed = limitTencentRouteName(this.data.tencentRouteName || '')
    if (typed) return typed
    return this.buildTencentRouteFallbackName() || '腾讯地图路线'
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
    var routeName = this.buildTencentRouteName()
    this.setData({ creatingTencentRoute: true })
    wx.showLoading({ title: '生成中', mask: true })
    api.createRouteBookFromTencentDirection({
      name: routeName,
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
        selectedRouteName: decorated.displayName || routeName,
        generatedRouteBookId: null,
      }, buildRoutePreview(decorated.preview_points)), function () {
        that.drawMainRoutePreview()
      })
      wx.showToast({ title: '已生成路线', icon: 'success' })
    }).catch(function (err) {
      wx.showToast({ title: formatTencentRouteError(err), icon: 'none' })
    }).finally(function () {
      wx.hideLoading()
      that.setData({ creatingTencentRoute: false })
    })
  },

  // 图二只有"出发时间"一行（无"预计结束"），但后端需要 estimated_end_time，
  // 所以出发时间一变就把预计结束自动顺成出发 +3h（和 initDefaultTime 默认一致）。
  bumpEndAfterStart: function (startIso) {
    var end = new Date(new Date(startIso).getTime() + 3 * 60 * 60 * 1000)
    var e = splitLocal(end)
    this.setData({ endDate: e.date, endTime: e.time, 'form.estimated_end_time': toIso(e.date, e.time) })
  },

  onStartDateChange: function (event) {
    var value = event.detail.value
    var startIso = toIso(value, this.data.startTime)
    this.setData({ startDate: value, 'form.start_time': startIso })
    this.bumpEndAfterStart(startIso)
  },

  onStartTimeChange: function (event) {
    var value = event.detail.value
    var startIso = toIso(this.data.startDate, value)
    this.setData({ startTime: value, 'form.start_time': startIso })
    this.bumpEndAfterStart(startIso)
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
      // 选完路线直接进图二编辑页。草稿懒建（加照片 / 下一步时才落库），
      // 因为后端建草稿必须有集合点，而集合点要在这一步图二里才填。
      this.setData({ currentStep: 'edit' }, this.drawStepThumb.bind(this))
      return
    }
    if (this.data.currentStep === 'edit') {
      if (!this.data.form.meeting_point) {
        wx.showToast({ title: '填写集合点', icon: 'none' })
        return
      }
      if (!this.ensureFutureMeetupTime()) return
      // 时间顺序前端先拦一次：结束必须晚于开始，免得到发布才被后端 422 退回
      if (new Date(this.data.form.estimated_end_time) <= new Date(this.data.form.start_time)) {
        wx.showToast({ title: '结束时间要晚于出发', icon: 'none' })
        return
      }
      // 编辑完 → 落库 + 进图一总览确认页
      this.onTapGoPreview()
    }
  },

  prevStep: function () {
    if (this.data.currentStep === 'confirm') {
      this.setData({ currentStep: 'edit' }, this.drawStepThumb.bind(this))
    } else if (this.data.currentStep === 'edit') {
      this.setData({ currentStep: 'route' })
    }
  },

  // 把当前表单存成草稿（或更新已有草稿），成功后进入"照片"步骤并回显已有照片。
  // 设计要点：
  // 1）首次进入：调 createOrUpdateDraft（内部已处理 409 draft_exists → 转 updateMeetup 复用旧草稿）。
  // 2）已有 meetupId（用户从 media 退回 details 改了内容又前进）：直接 updateMeetup 复用同一条，
  //    不再重复建，避免每来回一次就产生一条新草稿。
  // 3）resolveRouteBookId：选的是"从骑行生成"时，要先把那条活动转成路书拿到 route_book_id。
  // 懒建草稿：图二编辑页"加照片 / 下一步 / 保存草稿"前调用。
  // 后端建草稿必须有集合点（meeting_point 必填），所以这里先校验。
  // 已有草稿直接复用 id；没有则 resolveRouteBookId（"从骑行生成"先转路书）→ 建草稿 → 记下 id + 回显照片。
  ensureDraft: function () {
    var that = this
    if (!this.data.form.meeting_point) {
      wx.showToast({ title: '请先填写集合点', icon: 'none' })
      return Promise.reject(new Error('no_meeting_point'))
    }
    if (!this.ensureFutureMeetupTime()) {
      return Promise.reject(new Error('past_start_time'))
    }
    return this.resolveRouteBookId()
      .then(function (routeBookId) {
        var payload = Object.assign({}, that.data.form, {
          segment_id: that.data.selectedSegmentId || null,
          route_book_id: routeBookId || that.data.selectedRouteBookId || null,
          max_participants: Number(that.data.form.max_participants),
        })
        if (that.data.meetupId) {
          // 已有草稿也要把路线写回后端；否则从路线详情带参数进来只会改 UI，不会改后端草稿路线。
          // 只 PATCH 路线两字段，不带整张 form——form 里时间等字段此刻可能是空串，
          // 全量 PATCH 会 422 把照片上传/下一步全部卡死（T9 集成审 I1）。完整 form 由 saveDraft/publish 负责。
          return api.updateMeetup(that.data.meetupId, {
            segment_id: that.data.selectedSegmentId || null,
            route_book_id: routeBookId || that.data.selectedRouteBookId || null,
          }).then(function () {
            return { id: that.data.meetupId }
          })
        }
        return that.createOrUpdateDraft(payload)
      })
      .then(function (draft) {
        that.setData({ meetupId: draft.id })
        that.loadMedia()
        return draft.id
      })
  },

  // "保存草稿"按钮：把当前编辑落库后退出（草稿留在"我发起的"，下次进来 restoreDraft 恢复）。
  saveDraft: function () {
    var that = this
    if (this.data.savingDraft) return
    this.setData({ savingDraft: true })
    wx.showLoading({ title: '保存中', mask: true })
    this.ensureDraft()
      .then(function (meetupId) {
        // 已有草稿时 ensureDraft 不重存，这里补一次更新保证最新；只发 form 字段不发 route id（路线已定，避免触发二选一重算）
        return api.updateMeetup(meetupId, Object.assign({}, that.data.form, {
          max_participants: Number(that.data.form.max_participants),
        }))
      })
      .then(function () {
        wx.showToast({ title: '草稿已保存', icon: 'success' })
        setTimeout(function () { wx.navigateBack() }, 600)
      })
      .catch(function (err) {
        if (err && err.message !== 'no_meeting_point' && err.message !== 'past_start_time') {
          wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
        }
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
    var patch = {}
    patch[key] = value
    if (field === 'recommended_power_label') patch.recommendedPowerLabel = value
    if (field === 'average_speed_range') patch.averageSpeedRange = value
    this.setData(patch)
  },

  // 发布页人数加减器：就地 +/- 人数，夹在 [2,20]（和后端 CHECK 一致），不跳步编辑
  onStepMax: function (event) {
    var delta = Number(event.currentTarget.dataset.delta)
    var n = Number(this.data.form.max_participants) + delta
    if (n < 2) n = 2
    if (n > 20) n = 20
    this.setData({ 'form.max_participants': n })
  },

  // 发布前总览页：可见范围两个盒子点选（图一是并排盒子不是 picker），按 data-value 直接设
  onSelectVisibility: function (event) {
    this.setData({ 'form.visibility': event.currentTarget.dataset.value })
  },

  onPaceChange: function (event) {
    var index = Number(event.detail.value)
    var option = this.data.paceOptions[index]
    if (!option) return
    var pace = PACE_DISPLAY[option.value] || PACE_DISPLAY.cruise
    var that = this
    this.setData({
      'form.pace_level': option.value,
      'form.recommended_power_label': pace.recommended_power_label,
      'form.average_speed_range': pace.average_speed_range,
      paceIndex: index,
      paceLabel: option.label,
    }, function () {
      that.updatePreviewDerived()
    })
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

  // 算图二的派生展示：预计时长（结束-出发）+ 推荐功率/均速（默认跟强度走，用户改过就用用户填的）
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
    var powerLabel = this.data.form.recommended_power_label || pace.recommended_power_label
    var speedLabel = this.data.form.average_speed_range || pace.average_speed_range
    this.setData({
      recommendedPowerLabel: powerLabel,
      averageSpeedRange: speedLabel,
      // picker 的当前档跟着展示值走；老草稿存过自由文本时退到 0 档（展示不受影响）
      powerIndex: findOptionIndex(POWER_OPTIONS, powerLabel),
      speedIndex: findOptionIndex(SPEED_OPTIONS, speedLabel),
      estimatedDurationText: duration,
      registrationDeadlineLabel: deadlineText,
    })
  },

  // 功率/均速区间选择：从固定档位里挑一档写进 form（绝不出现自由文本）
  onPaceHintChange: function (event) {
    var kind = event.currentTarget.dataset.kind
    var index = Number(event.detail.value)
    if (kind === 'power') {
      this.setData({ 'form.recommended_power_label': POWER_OPTIONS[index] || POWER_OPTIONS[0] })
    } else {
      this.setData({ 'form.average_speed_range': SPEED_OPTIONS[index] || SPEED_OPTIONS[0] })
    }
    this.updatePreviewDerived()
  },

  // 编辑页"下一步" → 懒建/更新草稿拿到 share_token，再进图一总览确认
  onTapGoPreview: function () {
    var that = this
    this.updatePreviewDerived()
    this.ensureDraft().then(function (meetupId) {
      return api.updateMeetup(meetupId, Object.assign({}, that.data.form, {
        max_participants: Number(that.data.form.max_participants),
      }))
    }).then(function (draft) {
      that.setData({
        currentStep: 'confirm',
        meetupId: draft.id,
        shareToken: draft.share_token || that.data.shareToken || '',
        // 总览页路线卡的距离/爬升，从草稿快照拿（API 返回 km / 米）
        routeDistanceText: (draft.snapshot_distance || draft.snapshot_distance === 0) ? draft.snapshot_distance : '',
        routeClimbText: (draft.snapshot_climb || draft.snapshot_climb === 0) ? draft.snapshot_climb : '',
      }, function () {
        that.drawStepThumb()
      })
      // 拉已加入骑友（getMeetupParticipants 在 Task5 才加，没有就跳过不报错）
      if (api.getMeetupParticipants) {
        // 带上 share_token：发起人本人虽豁免，但 invite_only 下显式传 token 更稳（不靠隐式身份侥幸）
        api.getMeetupParticipants(draft.id, draft.share_token).then(function (items) {
          that.setData({ invitees: items || [] })
        }).catch(function () {
          that.setData({ invitees: [] })
        })
      }
    }).catch(function (err) {
      // no_meeting_point 已由 ensureDraft toast 过，别重复报"保存失败"
      if (err && err.message !== 'no_meeting_point' && err.message !== 'past_start_time') {
        wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
      }
    })
  },

  // WXML 不支持 .indexOf()，"哪些标签选中"在 JS 算成 selected 标志
  syncAudienceOptions: function (tags) {
    var chosen = tags || []
    return AUDIENCE_OPTIONS.map(function (o) {
      return { value: o.value, label: o.label, icon: o.icon, selected: chosen.indexOf(o.value) >= 0 }
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

  // 总览页"报名门槛"展示行：点一下翻开/收起底下的可编辑 textarea（视觉默认是只读行）
  togglePvEditGate: function () {
    this.setData({ pvEditGate: !this.data.pvEditGate })
  },

  // 总览页"安全提示"展示行：点一下翻开/收起 textarea + 模板 chips（视觉默认是只读行）
  togglePvEditSafety: function () {
    this.setData({ pvEditSafety: !this.data.pvEditSafety })
  },

  ensureFutureMeetupTime: function () {
    var start = new Date(this.data.form.start_time)
    if (!Number.isFinite(start.getTime())) {
      wx.showToast({ title: '请选择出发时间', icon: 'none' })
      return false
    }
    if (start <= new Date()) {
      wx.showToast({ title: '出发时间要晚于现在', icon: 'none' })
      return false
    }
    return true
  },

  ensurePublishableMeetupTime: function () {
    if (!this.ensureFutureMeetupTime()) return false
    var start = new Date(this.data.form.start_time)
    if (start.getTime() - Date.now() <= MEETUP_PUBLISH_CUTOFF_BUFFER_MS) {
      wx.showToast({ title: '离出发太近，不能发布', icon: 'none' })
      return false
    }
    return true
  },

  onTapPreviewRouteDetail: function () {
    routeMapNav.openRouteMapPage({
      title: this.data.selectedRouteName || '路线地图',
      center: this.data.routePreviewCenter,
      markers: this.data.routePreviewMarkers,
      polylines: this.data.routePreviewPolylines,
      includePoints: this.data.routePreviewIncludePoints,
    })
  },

  // 确认并发布：把图二设的 social 字段再存一次 → 发布 → 跳详情
  onConfirmPublish: function () {
    var that = this
    if (this.data.submitting) return
    if (!this.data.meetupId) {
      wx.showToast({ title: '草稿丢失，请退回重试', icon: 'none' })
      return
    }
    if (!this.ensurePublishableMeetupTime()) return
    this.setData({ submitting: true })
    api.updateMeetup(this.data.meetupId, {
      pace_level: this.data.form.pace_level,
      recommended_power_label: this.data.form.recommended_power_label,
      average_speed_range: this.data.form.average_speed_range,
      audience_tags: this.data.form.audience_tags,
      visibility: this.data.form.visibility,
      eligibility_note: this.data.form.eligibility_note,
      safety_note: this.data.form.safety_note,
    }).then(function () {
      return api.publishMeetup(that.data.meetupId)
    }).then(function (meetup) {
      wx.redirectTo({ url: '/pages/meetup-detail/meetup-detail?id=' + meetup.id })
    }).catch(function (err) {
      wx.showToast({ title: formatMeetupPublishError(err), icon: 'none' })
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
    // 草稿懒建：照片要挂在已落库的约骑上，所以先 ensureDraft（会校验集合点）再选图上传
    this.ensureDraft().then(function () {
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
    }).catch(function () {})
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
