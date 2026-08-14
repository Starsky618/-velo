const api = require('../../utils/api')
const { wgs84ToGcj02 } = require('../../utils/coords')
const mapTheme = require('../../utils/map-theme')
const routeMapNav = require('../../utils/route-map-nav')
const climbPlanUi = require('../../utils/climb-plan')

function buildRoutePreview(points) {
  if (!Array.isArray(points) || points.length < 2) {
    return {
      routePreviewVisible: false,
      routePreviewCenter: { latitude: 37.8706, longitude: 112.5489 },
      routePreviewMarkers: [],
      routePreviewPolylines: [],
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
      routePreviewCenter: { latitude: 37.8706, longitude: 112.5489 },
      routePreviewMarkers: [],
      routePreviewPolylines: [],
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
      { id: 1, latitude: first.latitude, longitude: first.longitude, width: 18, height: 18, title: '起点' },
      { id: 2, latitude: last.latitude, longitude: last.longitude, width: 18, height: 18, title: '终点' },
    ],
    routePreviewPolylines: mapTheme.buildRoutePreviewPolylines(mapPoints),
  }
}

function buildStats(route) {
  var stats = []
  var distance = Number(route && route.distance)
  var hasClimb = route && route.climb !== null && route.climb !== undefined
  var climb = Number(route && route.climb)
  if (Number.isFinite(distance) && distance > 0) {
    var km = distance / 1000
    stats.push({ v: km >= 10 ? km.toFixed(1) : km.toFixed(2), u: 'km', k: '距离' })
  }
  if (hasClimb && Number.isFinite(climb)) {
    stats.push({ v: String(Math.round(climb)), u: 'm', k: '爬升' })
  }
  var climbPlan = climbPlanUi.normalizeClimbPlan(route && route.climb_plan)
  if (climbPlan) {
    stats.push({
      v: String(Number(climbPlan.composition.climb_count) || 0),
      u: '段',
      k: '显著爬坡',
    })
  }
  return stats
}

function exportBlockHint(route) {
  if (!route || route.export_ready) return ''
  if (route.export_block_reason === 'no_current_version') {
    return '这条路线还没有可下载轨迹'
  }
  if (route.export_block_reason === 'no_elevation') {
    return '这条路线缺少完整逐点海拔，暂时不能导出到码表'
  }
  if (route.export_block_reason === 'not_public') {
    return '这条路线暂时不能下载'
  }
  return '这条路线暂时不能导出'
}

function exportErrorMessage(err) {
  var code = err && err.code
  if (code === 403) return '这条路线暂时不能下载'
  if (code === 422) {
    var message = err && err.message
    if (message && message.indexOf('海拔') >= 0) return '这条路线缺少完整逐点海拔，暂时不能导出到码表'
    return '这条路线还没有可下载轨迹'
  }
  if (code === -1) return '网络失败，请稍后再试'
  if (code >= 500) return '服务器开小差了，请稍后再试'
  return (err && err.message) || '下载失败，请稍后再试'
}

function canCopyAnonymousExportLink(route) {
  return !!route && route.anonymous_export_download_allowed === true
}

Page({
  data: {
    routeBookId: null,
    loading: true,
    error: '',
    route: null,
    routeStats: [],
    hasElevation: false,
    climbPlanView: climbPlanUi.buildView(null, null),
    exportHint: '',
    routePreviewVisible: false,
    routePreviewCenter: { latitude: 37.8706, longitude: 112.5489 },
    routePreviewMarkers: [],
    routePreviewPolylines: [],
    routePreviewIncludePoints: [],
    exporting: false,
    exportingFormat: '',
    lastExportFilename: '',
    lastExportTempPath: '',
    lastExportSavedPath: '',
    lastExportDownloadUrl: '',
    canCopyExportLink: false,
    exportSendFailed: false,
    exportSendError: '',
    exportSendRawMessage: '',
  },

  onLoad: function (options) {
    var id = Number(options && options.id)
    if (!Number.isFinite(id) || id <= 0) {
      this.setData({ loading: false, error: '路线不存在' })
      return
    }
    this.setData({ routeBookId: id })
    this.fetchRoute(id)
  },

  fetchRoute: function (id) {
    var that = this
    this.setData({ loading: true, error: '' })
    return api.getRouteBookDetail(id)
      .then(function (route) {
        var preview = buildRoutePreview(route.preview_points)
        var hasElevation = Array.isArray(route.elevation_profile) && route.elevation_profile.length > 1
        that.setData(Object.assign({
          route: route,
          routeStats: buildStats(route),
          hasElevation: hasElevation,
          climbPlanView: climbPlanUi.buildView(route.climb_plan, route.rider_climb_plan),
          exportHint: exportBlockHint(route),
          lastExportFilename: '',
          lastExportTempPath: '',
          lastExportSavedPath: '',
          lastExportDownloadUrl: '',
          canCopyExportLink: canCopyAnonymousExportLink(route),
          exportSendFailed: false,
          exportSendError: '',
          loading: false,
        }, preview), function () {
          if (hasElevation) {
            setTimeout(function () {
              that.drawElevationThumb(route.elevation_profile)
            }, 100)
          }
        })
      })
      .catch(function () {
        that.setData({ loading: false, error: '路线暂时加载失败' })
      })
  },

  onOpenRouteMapPage: function () {
    routeMapNav.openRouteMapPage({
      title: (this.data.route && this.data.route.name) || '路线地图',
      center: this.data.routePreviewCenter,
      markers: this.data.routePreviewMarkers,
      polylines: this.data.routePreviewPolylines,
      includePoints: this.data.routePreviewIncludePoints,
    })
  },

  drawElevationThumb: function (profile) {
    if (!Array.isArray(profile) || profile.length < 2) return
    var ctx = wx.createCanvasContext('route-book-elevation-thumb', this)
    var width = 311
    var height = 70
    var padY = 6
    var distances = profile.map(function (p) { return Number(p[0]) || 0 })
    var elevations = profile.map(function (p) { return Number(p[1]) || 0 })
    var minD = Math.min.apply(null, distances)
    var maxD = Math.max.apply(null, distances)
    var minE = Math.min.apply(null, elevations)
    var maxE = Math.max.apply(null, elevations)
    var spanD = maxD - minD || 1
    var spanE = maxE - minE || 1
    var points = profile.map(function (p) {
      return {
        x: ((Number(p[0]) || 0) - minD) / spanD * width,
        y: height - padY - ((Number(p[1]) || 0) - minE) / spanE * (height - padY * 2),
      }
    })
    ctx.beginPath()
    ctx.moveTo(points[0].x, height)
    points.forEach(function (pt) { ctx.lineTo(pt.x, pt.y) })
    ctx.lineTo(points[points.length - 1].x, height)
    ctx.closePath()
    ctx.setFillStyle('rgba(255, 149, 0, 0.10)')
    ctx.fill()
    var climbPlan = climbPlanUi.normalizeClimbPlan(this.data.route && this.data.route.climb_plan)
    ;(climbPlan && climbPlan.climbs ? climbPlan.climbs : []).forEach(function (climb) {
      var startKm = Number(climb.start_distance_m) / 1000
      var endKm = Number(climb.end_distance_m) / 1000
      if (!Number.isFinite(startKm) || !Number.isFinite(endKm) || endKm <= startKm) return
      ctx.setGlobalAlpha(0.12)
      ctx.setFillStyle(climbPlanUi.categoryColor(climb.category))
      ctx.fillRect((startKm - minD) / spanD * width, padY, (endKm - startKm) / spanD * width, height - padY * 2)
      ctx.setGlobalAlpha(1)
    })
    ctx.beginPath()
    points.forEach(function (pt, i) {
      if (i === 0) ctx.moveTo(pt.x, pt.y)
      else ctx.lineTo(pt.x, pt.y)
    })
    ctx.setStrokeStyle('#FF9500')
    ctx.setLineWidth(2)
    ctx.setLineJoin('round')
    ctx.stroke()
    ctx.draw()
  },

  onDownloadRouteExport: function (event) {
    var format = event.currentTarget.dataset.format
    var route = this.data.route
    if (!format || this.data.exporting) return
    if (!route || !route.export_ready || !route.id) {
      wx.showToast({ title: '这条路线还没有可下载轨迹', icon: 'none' })
      return
    }

    var that = this
    this.setData({
      exporting: true,
      exportingFormat: format,
      lastExportFilename: '',
      lastExportTempPath: '',
      lastExportSavedPath: '',
      lastExportDownloadUrl: '',
      exportSendFailed: false,
      exportSendError: '',
      exportSendRawMessage: '',
    })
    api.createRouteExport(route.id, format, 'generic')
      .then(function (exportInfo) {
        return api.downloadRouteExport(exportInfo.download_url, exportInfo.filename)
          .then(function (downloadedFile) {
            var tempFilePath = downloadedFile && downloadedFile.tempFilePath
            var savedFilePath = downloadedFile && downloadedFile.savedFilePath
            var shareFilePath = downloadedFile && downloadedFile.filePath
            that.setData({
              lastExportFilename: exportInfo.filename,
              lastExportTempPath: shareFilePath || tempFilePath || '',
              lastExportSavedPath: savedFilePath || '',
              lastExportDownloadUrl: canCopyAnonymousExportLink(route) ? api.resolveUrl(exportInfo.download_url) : '',
            })
            wx.showToast({ title: '路线文件已下载', icon: 'success' })
          })
      })
      .catch(function (err) {
        wx.showToast({ title: exportErrorMessage(err), icon: 'none' })
      })
      .then(function () {
        that.setData({
          exporting: false,
          exportingFormat: '',
        })
      })
  },

  shareExportFile: function (filePath, fileName) {
    if (!filePath) {
      wx.showToast({ title: '请先下载路线文件', icon: 'none' })
      return
    }
    this.setData({ exportSendFailed: false, exportSendError: '', exportSendRawMessage: '' })
    var that = this
    api.shareRouteExportFile(filePath, fileName)
      .then(function () {
        wx.showToast({ title: '已打开微信发送', icon: 'success' })
      })
      .catch(function (err) {
        that.showExportSendFallback(err)
      })
  },

  onShareLastExport: function () {
    this.shareExportFile(this.data.lastExportSavedPath || this.data.lastExportTempPath, this.data.lastExportFilename)
  },

  showExportSendFallback: function (err) {
    if (err && err.rawMessage) {
      console.warn('route book export share failed:', err.rawMessage)
    }
    this.setData({
      exportSendFailed: true,
      exportSendError: this.data.canCopyExportLink
        ? ((err && err.message) || '微信没能发送文件，可以改用浏览器下载链接。')
        : '微信没能发送文件。路线文件仍保存在微信本地；私有路线链接不能在浏览器直接打开，请稍后重试发送。',
      exportSendRawMessage: (err && err.rawMessage) || '',
    })
    wx.showToast({ title: this.data.canCopyExportLink ? '发送失败，可复制链接' : '发送失败，请稍后重试', icon: 'none' })
  },

  onCopyLastExportLink: function () {
    if (!this.data.canCopyExportLink) {
      wx.showToast({ title: '私有路线请发送文件，不支持浏览器链接', icon: 'none' })
      return
    }
    var url = this.data.lastExportDownloadUrl
    if (!url) {
      wx.showToast({ title: '请先下载路线文件', icon: 'none' })
      return
    }
    api.copyText(url)
      .then(function () {
        wx.showToast({ title: '下载链接已复制', icon: 'success' })
      })
      .catch(function (err) {
        wx.showToast({ title: (err && err.message) || '复制失败', icon: 'none' })
      })
  },

  onShowExportHelp: function () {
    var content = this.data.canCopyExportLink
      ? '1. 点“发送到微信”把 GPX / TCX 交给自己或骑友。\n2. 在 Garmin / iGPSPORT / 顽鹿 / Wahoo 中选择这个文件导入。\n\n公开路线也可以复制浏览器下载链接。'
      : '1. 点“发送到微信”把 GPX / TCX 发给自己。\n2. 在 Garmin / iGPSPORT / 顽鹿 / Wahoo 中选择聊天里的文件导入。\n\n私有路线不能用浏览器链接匿名下载。'
    wx.showModal({
      title: '两步导入',
      content: content,
      showCancel: false,
      confirmText: '知道了',
    })
  },
})

if (typeof module !== 'undefined') {
  module.exports = {
    buildStats: buildStats,
    buildClimbPlanView: climbPlanUi.buildView,
    buildRoutePreview: buildRoutePreview,
    canCopyAnonymousExportLink: canCopyAnonymousExportLink,
  }
}
