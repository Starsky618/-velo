/**
 * 上传页 — 用户把码表文件交给系统阅卷的入口。
 *
 * 这个文件像一个"交卷窗口"：只负责选文件、上传、等待后端解析结果，
 * 再把成绩按开奖节奏展示出来；真正解析轨迹的重活在后端完成。
 *
 * 数据流：微信文件 → /api/activities/upload → 800ms 轻量状态轮询 →
 * /api/activities/{id} 拉完整成绩 → 开奖剧场和成绩卡。
 */

const api = require('../../utils/api')
const app = getApp()

function pad2(n) {
  return n < 10 ? '0' + n : '' + n
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return ''
  var sec = Math.max(0, Math.round(seconds))
  var h = Math.floor(sec / 3600)
  var m = Math.floor((sec % 3600) / 60)
  var s = sec % 60
  return h > 0 ? h + ':' + pad2(m) + ':' + pad2(s) : m + ':' + pad2(s)
}

function formatDateText(value) {
  if (!value) return ''
  var d = new Date(value)
  if (isNaN(d.getTime())) return ''
  return d.getFullYear() + '.' + pad2(d.getMonth() + 1) + '.' + pad2(d.getDate())
}

function formatNum(value, digits) {
  if (value === null || value === undefined || isNaN(Number(value))) return ''
  var n = Number(value)
  return digits === 0 ? String(Math.round(n)) : n.toFixed(digits)
}

function haversineDistance(lat1, lon1, lat2, lon2) {
  var R = 6371000
  var toRad = Math.PI / 180
  var dLat = (lat2 - lat1) * toRad
  var dLon = (lon2 - lon1) * toRad
  var a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2)
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function buildElevationData(track) {
  if (!track || track.length < 2) return []
  var result = []
  var cumDist = 0
  var hasValidEle = false
  for (var i = 0; i < track.length; i++) {
    if (i > 0) {
      cumDist += haversineDistance(
        track[i - 1].lat, track[i - 1].lon,
        track[i].lat, track[i].lon
      )
    }
    var ele = track[i].ele
    if (ele != null) hasValidEle = true
    result.push({
      distance: cumDist / 1000,
      elevation: ele != null ? ele : 0
    })
  }
  return hasValidEle ? result : []
}

Page({
  data: {
    // 状态机：idle / confirming / uploading / polling / reveal / done / error
    step: 'idle',
    fileName: '',
    filePath: '',
    fileSize: 0,
    fileSizeKB: 0,
    statusText: '',
    activityId: null,
    result: null,
    durationMin: 0,
    errorMsg: '',

    pollSeconds: 0,
    parsePointCount: 0,
    revealStats: [],
    revealDone: false,
    scoreCard: null,
    hasElevationProfile: false,
    elevationRevealed: false,

    meetupId: '',
    meetupToken: '',
    meetupBannerVisible: false,
    meetupTitle: '',
    meetupSubmittedCount: null,
    meetupRiderCount: null,
    reportPath: ''
  },

  elevationData: null,
  _pollTimer: null,
  _revealTimers: null,

  onLoad: function (options) {
    options = options || {}
    var meetupId = options.meetup_id || options.meetupId || ''
    var token = options.token || ''
    // 只看 meetupId：公开约骑没有口令（token 为空），上下文照样要生效——
    // 双条件会让公开约骑从战报"交卷"进来时横幅和战报分享整体失踪（跨任务契约，README 符号索引）
    if (meetupId) {
      this.setData({
        meetupId: meetupId,
        meetupToken: token,
        reportPath: this.buildReportPath(meetupId, token)
      })
      this.fetchMeetupReport(meetupId, token)
      wx.showShareMenu({ withShareTicket: true })
    } else {
      wx.hideShareMenu()
    }
  },

  onShow: function () {
    var that = this
    if (this.elevationData && this.elevationData.length > 0 && this.data.step === 'done') {
      wx.nextTick(function () { that.drawElevationProfile() })
    }
    // onHide 会停轮询省资源；切回来时若还在解析中要把轮询接上，
    // 否则用户切出去再回来，页面会永远卡在"解析中"（timer 已死没人再问后端）
    if (this.data.step === 'polling' && this.data.activityId && !this._pollTimer) {
      this.pollStatus(this.data.activityId)
    }
  },

  chooseFile: function () {
    var that = this
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['gpx', 'fit'],
      success: function (res) {
        var file = res.tempFiles[0]
        that.clearPollTimer()
        that.clearRevealTimers()
        that.elevationData = null
        that.setData({
          step: 'confirming',
          fileName: file.name,
          filePath: file.path,
          fileSize: file.size,
          fileSizeKB: Math.round(file.size / 1024),
          statusText: '',
          activityId: null,
          result: null,
          durationMin: 0,
          errorMsg: '',
          pollSeconds: 0,
          parsePointCount: 0,
          revealStats: [],
          revealDone: false,
          scoreCard: null,
          hasElevationProfile: false,
          elevationRevealed: false
        })
      }
    })
  },

  cancel: function () {
    this.reset()
  },

  startUpload: function () {
    var that = this
    if (!app.globalData.token) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }

    this.clearPollTimer()
    this.clearRevealTimers()
    this.setData({ step: 'uploading', statusText: '正在上传文件...' })

    api.upload('/api/activities/upload', this.data.filePath, 'file')
      .then(function (data) {
        that.setData({
          activityId: data.activity_id,
          step: 'polling',
          statusText: '正在读取轨迹点...',
          pollSeconds: 0,
          parsePointCount: 0
        })
        that.pollStatus(data.activity_id)
      })
      .catch(function (err) {
        that.setData({
          step: 'error',
          errorMsg: err.message || '上传失败'
        })
      })
  },

  pollStatus: function (activityId) {
    var that = this
    var startedAt = Date.now()
    var tickIndex = 0

    this.clearPollTimer()
    this._pollTimer = setInterval(function () {
      tickIndex++
      var elapsed = Date.now() - startedAt
      that.updatePollingCopy(elapsed, tickIndex)

      api.get('/api/activities/' + activityId + '/status')
        .then(function (data) {
          // 超时(30s)宣告"转后台"后，迟到的响应不再接管页面——
          // 否则用户会看到提示闪一下又突然跳开奖，状态机来回横跳
          if (!that._pollTimer) return
          if (data.status === 'completed') {
            that.clearPollTimer()
            if (data.duplicate_of) {
              wx.showToast({
                title: '已合并到已有骑行',
                icon: 'none',
                duration: 2500
              })
              setTimeout(function () {
                wx.redirectTo({ url: '/pages/detail/detail?id=' + data.duplicate_of })
              }, 1500)
              return
            }
            that.setData({ statusText: '解析完成，生成你的成绩卡...' })
            that.fetchResult(activityId)
          } else if (data.status === 'failed') {
            that.clearPollTimer()
            that.setData({
              step: 'error',
              errorMsg: data.error_message || '解析失败，请重试'
            })
          }
        })
        .catch(function () {
          // 网络抖动时不立刻判失败；下一轮轻量轮询会继续问后端。
        })

      if (elapsed > 30000) {
        that.clearPollTimer()
        that.setData({
          step: 'error',
          errorMsg: '已转后台解析，稍后在首页查看结果'
        })
      }
    }, 800)
  },

  updatePollingCopy: function (elapsed, tickIndex) {
    var seconds = Math.floor(elapsed / 1000)
    var dots = '.'.repeat((tickIndex % 3) + 1)
    var text = '正在读取轨迹点' + dots
    if (elapsed > 5000) text = '正在计算成绩' + dots
    if (elapsed > 30000) text = '已转后台解析，稍后在首页查看结果'
    this.setData({
      statusText: text,
      pollSeconds: seconds,
      parsePointCount: Math.min(9999, tickIndex * 187)
    })
  },

  clearPollTimer: function () {
    if (this._pollTimer) {
      clearInterval(this._pollTimer)
      this._pollTimer = null
    }
  },

  clearRevealTimers: function () {
    if (!this._revealTimers) {
      this._revealTimers = []
      return
    }
    for (var i = 0; i < this._revealTimers.length; i++) {
      clearTimeout(this._revealTimers[i])
    }
    this._revealTimers = []
  },

  fetchResult: function (activityId) {
    var that = this
    api.get('/api/activities/' + activityId)
      .then(function (data) {
        var timeSec = data.moving_time != null ? data.moving_time : data.duration
        var durationMin = timeSec != null ? Math.round(timeSec / 60) : 0
        if (data.avg_power != null) data.avg_power = Math.round(data.avg_power)
        if (data.avg_hr != null) data.avg_hr = Math.round(data.avg_hr)
        if (data.avg_cadence != null) data.avg_cadence = Math.round(data.avg_cadence)
        if (data.elevation_gain != null) data.elevation_gain = Math.round(data.elevation_gain)
        if (data.calories != null) data.calories = Math.round(data.calories)

        var eleData = buildElevationData(data.simplified_track)
        that.elevationData = eleData
        that.setData({
          step: 'reveal',
          result: data,
          durationMin: durationMin,
          revealStats: that.buildRevealStats(data, timeSec),
          scoreCard: that.buildScoreCard(data, timeSec),
          revealDone: false,
          hasElevationProfile: eleData.length > 0,
          elevationRevealed: false
        })
        that.runRevealSequence(eleData.length > 0)
      })
      .catch(function (err) {
        that.setData({
          step: 'error',
          errorMsg: err.message || '获取数据失败'
        })
      })
  },

  buildRevealStats: function (data, timeSec) {
    var stats = []
    if (data.distance != null) stats.push({ key: 'distance', label: '距离', value: formatNum(data.distance, 1), unit: 'km', visible: false })
    if (timeSec != null) stats.push({ key: 'time', label: '骑行时间', value: formatDuration(timeSec), unit: '', visible: false })
    if (data.avg_speed != null) stats.push({ key: 'avg_speed', label: '均速', value: formatNum(data.avg_speed, 1), unit: 'km/h', visible: false })
    if (data.elevation_gain != null) stats.push({ key: 'elevation_gain', label: '累计爬升', value: formatNum(data.elevation_gain, 0), unit: 'm', visible: false })
    if (data.max_speed != null) stats.push({ key: 'max_speed', label: '最高时速', value: formatNum(data.max_speed, 1), unit: 'km/h', visible: false })
    return stats
  },

  buildScoreCard: function (data, timeSec) {
    var userInfo = app.globalData && app.globalData.userInfo
    var title = data.title || this.data.fileName || '这次骑行'
    var items = []
    if (data.distance != null) items.push({ key: 'distance', label: '距离', value: formatNum(data.distance, 1), unit: 'km' })
    if (data.elevation_gain != null) items.push({ key: 'elevation_gain', label: '爬升', value: formatNum(data.elevation_gain, 0), unit: 'm' })
    if (data.avg_speed != null) items.push({ key: 'avg_speed', label: '均速', value: formatNum(data.avg_speed, 1), unit: 'km/h' })
    if (timeSec != null) items.push({ key: 'time', label: '时间', value: formatDuration(timeSec), unit: '' })
    if (data.max_speed != null) items.push({ key: 'max_speed', label: '最高时速', value: formatNum(data.max_speed, 1), unit: 'km/h' })
    if (data.calories != null) items.push({ key: 'calories', label: '消耗', value: formatNum(data.calories, 0), unit: 'kcal' })

    var riderCount = this.data.meetupRiderCount
    var submitted = this.data.meetupSubmittedCount
    var nextSubmitted = submitted != null ? submitted + 1 : null
    // 这里本地乐观 +1：约骑关联 tick 可能延迟几分钟，
    // 但用户刚交完卷，卡面应该先把"我这份"算进去。
    return {
      title: title,
      rider: (userInfo && userInfo.nickname) || 'VELO 骑友',
      dateText: formatDateText(data.started_at), // 展示时间只用业务时间 started_at；缺失就空串隐藏，不退回 DB 写入时间

      items: items,
      firstText: riderCount != null && nextSubmitted != null
        ? '本场战报由你开张 · 已交卷 ' + nextSubmitted + ' / ' + riderCount
        : '',
      firstHint: riderCount != null && nextSubmitted != null && riderCount > nextSubmitted
        ? '其他 ' + (riderCount - nextSubmitted) + ' 个人的卷子还空着。把这张卡发到群里，催他们交。'
        : ''
    }
  },

  runRevealSequence: function (hasElevation) {
    var that = this
    this.clearRevealTimers()
    var steps = [
      [1600, function () { that.revealStat('distance') }],
      [2300, function () { that.revealStat('time') }],
      [3000, function () { that.revealStat('avg_speed') }],
      [3700, function () {
        that.revealStat('elevation_gain')
        if (hasElevation) {
          that.setData({ elevationRevealed: true }, function () {
            wx.nextTick(function () { that.drawElevationProfile() })
          })
        }
      }],
      [4500, function () { that.revealStat('max_speed') }],
      [5800, function () { that.setData({ statusText: '解析完成，生成你的成绩卡' }) }],
      [6600, function () { that.setData({ step: 'done', revealDone: true }, function () {
        if (hasElevation) wx.nextTick(function () { that.drawElevationProfile() })
      }) }]
    ]
    for (var i = 0; i < steps.length; i++) {
      this._revealTimers.push(setTimeout(steps[i][1], steps[i][0]))
    }
  },

  revealStat: function (key) {
    var stats = this.data.revealStats || []
    for (var i = 0; i < stats.length; i++) {
      if (stats[i].key === key) stats[i].visible = true
    }
    this.setData({ revealStats: stats })
  },

  drawElevationProfile: function () {
    var data = this.elevationData
    if (!data || data.length < 2) return

    wx.createSelectorQuery()
      .in(this)
      .select('#uploadElevationCanvas')
      .fields({ node: true, size: true })
      .exec(function (res) {
        if (!res || !res[0] || !res[0].node) return
        var canvas = res[0].node
        var width = res[0].width
        var height = res[0].height
        var ctx = canvas.getContext('2d')
        var dpr = wx.getSystemInfoSync().pixelRatio
        canvas.width = width * dpr
        canvas.height = height * dpr
        ctx.scale(dpr, dpr)
        ctx.clearRect(0, 0, width, height)

        var pad = { top: 12, right: 12, bottom: 18, left: 12 }
        var chartW = width - pad.left - pad.right
        var chartH = height - pad.top - pad.bottom
        var minEle = Infinity
        var maxEle = -Infinity
        var maxDist = data[data.length - 1].distance
        if (maxDist <= 0) return
        for (var i = 0; i < data.length; i++) {
          if (data[i].elevation < minEle) minEle = data[i].elevation
          if (data[i].elevation > maxEle) maxEle = data[i].elevation
        }
        var eleRange = maxEle - minEle
        if (eleRange < 20) eleRange = 20
        minEle = minEle - eleRange * 0.1
        maxEle = maxEle + eleRange * 0.1
        eleRange = maxEle - minEle

        function toX(dist) { return pad.left + (dist / maxDist) * chartW }
        function toY(ele) { return pad.top + (1 - (ele - minEle) / eleRange) * chartH }

        ctx.beginPath()
        ctx.moveTo(toX(data[0].distance), toY(data[0].elevation))
        for (var j = 1; j < data.length; j++) {
          ctx.lineTo(toX(data[j].distance), toY(data[j].elevation))
        }
        ctx.lineTo(toX(data[data.length - 1].distance), pad.top + chartH)
        ctx.lineTo(toX(data[0].distance), pad.top + chartH)
        ctx.closePath()
        ctx.fillStyle = 'rgba(200, 255, 61, 0.12)'
        ctx.fill()

        ctx.beginPath()
        ctx.moveTo(toX(data[0].distance), toY(data[0].elevation))
        for (var k = 1; k < data.length; k++) {
          ctx.lineTo(toX(data[k].distance), toY(data[k].elevation))
        }
        ctx.strokeStyle = '#c8ff3d'
        ctx.lineWidth = 2
        ctx.stroke()
      })
  },

  fetchMeetupReport: function (meetupId, token) {
    var that = this
    api.get('/api/meetups/' + meetupId + '/report', token ? { token: token } : null)
      .then(function (data) {
        var totals = data && data.totals
        if (!totals || totals.rider_count == null || totals.submitted_count == null) return
        that.setData({
          meetupBannerVisible: true,
          meetupTitle: '本场约骑',
          meetupSubmittedCount: totals.submitted_count,
          meetupRiderCount: totals.rider_count
        })
      })
      .catch(function () {
        that.setData({
          meetupBannerVisible: false,
          meetupTitle: '',
          meetupSubmittedCount: null,
          meetupRiderCount: null
        })
      })
  },

  buildReportPath: function (meetupId, token) {
    // 公开约骑 token 为空：路径不带空 token，免得战报页把空串当口令透传
    var path = '/pages/meetup-report/meetup-report?id=' + meetupId + '&source=report_card'
    if (token) path += '&token=' + encodeURIComponent(token)
    return path
  },

  viewDetail: function () {
    wx.navigateTo({ url: '/pages/detail/detail?id=' + this.data.activityId })
  },

  viewReport: function () {
    if (!this.data.reportPath) return
    wx.navigateTo({ url: this.data.reportPath })
  },

  reset: function () {
    this.clearPollTimer()
    this.clearRevealTimers()
    this.elevationData = null
    this.setData({
      step: 'idle',
      fileName: '',
      filePath: '',
      fileSize: 0,
      fileSizeKB: 0,
      statusText: '',
      activityId: null,
      result: null,
      durationMin: 0,
      errorMsg: '',
      pollSeconds: 0,
      parsePointCount: 0,
      revealStats: [],
      revealDone: false,
      scoreCard: null,
      hasElevationProfile: false,
      elevationRevealed: false
    })
  },

  onShareAppMessage: function () {
    var card = this.data.scoreCard
    if (!this.data.meetupId || !card) {
      return {
        title: 'VELO 骑行记录',
        path: '/pages/upload/upload'
      }
    }
    var distanceText = ''
    if (this.data.result && this.data.result.distance != null) {
      distanceText = ' ' + formatNum(this.data.result.distance, 1) + 'km'
    }
    return {
      title: card.rider + '交卷了：' + card.title + distanceText,
      path: this.data.reportPath
    }
  },

  onHide: function () {
    this.clearPollTimer()
  },

  onUnload: function () {
    this.clearPollTimer()
    this.clearRevealTimers()
  }
})
