const api = require('../../utils/api')
const { renderMarkdown } = require('../../utils/md-render')
const { wgs84ToGcj02 } = require('../../utils/coords')
const mapTheme = require('../../utils/map-theme')

function formatDistance(value) {
  if (value === undefined || value === null) return ''
  var n = Number(value)
  if (!Number.isFinite(n)) return ''
  return n.toFixed(1) + ' km'
}

function formatClimb(value) {
  if (value === undefined || value === null) return ''
  var n = Number(value)
  if (!Number.isFinite(n)) return ''
  return '爬升 ' + Math.round(n) + ' m'
}

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

Page({
  data: Object.assign({}, mapTheme.getPaperMapData(), {
    guideId: null,
    loading: true,
    error: '',
    guide: null,
    markdownNodes: [],
    highlights: [],
    coverSrc: '/assets/route-placeholder.svg',
    distanceText: '',
    climbText: '',
    hasElevation: false,
    routePreviewVisible: false,
    routePreviewCenter: { latitude: 37.8706, longitude: 112.5489 },
    routePreviewMarkers: [],
    routePreviewPolylines: [],
    routePreviewIncludePoints: [],
  }),

  onLoad: function (options) {
    var id = Number(options && options.id)
    if (!Number.isFinite(id)) {
      this.setData({ loading: false, error: '路线不存在' })
      return
    }
    this.setData({ guideId: id })
    this.fetchGuide(id)
  },

  fetchGuide: function (id) {
    var that = this
    this.setData({ loading: true, error: '' })
    return api.get('/api/route-guides/' + id)
      .then(function (guide) {
        var preview = buildRoutePreview(guide.preview_points)
        var hasElevation = Array.isArray(guide.elevation_profile) && guide.elevation_profile.length > 1
        that.setData(Object.assign({
          guide: guide,
          markdownNodes: renderMarkdown(guide.content_md),
          highlights: Array.isArray(guide.highlights) ? guide.highlights : [],
          coverSrc: guide.cover_url || '/assets/route-placeholder.svg',
          distanceText: formatDistance(guide.distance),
          climbText: formatClimb(guide.climb),
          hasElevation: hasElevation,
          loading: false,
        }, preview), function () {
          if (hasElevation) that.drawElevation(guide.elevation_profile)
        })
      })
      .catch(function () {
        that.setData({ loading: false, error: '路线暂时加载失败' })
      })
  },

  drawElevation: function (profile) {
    if (!Array.isArray(profile) || profile.length < 2) return
    var ctx = wx.createCanvasContext('elevation-canvas', this)
    var width = 320
    var height = 128
    var pad = 18
    var distances = profile.map(function (p) { return Number(p[0]) || 0 })
    var elevations = profile.map(function (p) { return Number(p[1]) || 0 })
    var minD = Math.min.apply(null, distances)
    var maxD = Math.max.apply(null, distances)
    var minE = Math.min.apply(null, elevations)
    var maxE = Math.max.apply(null, elevations)
    var spanD = maxD - minD || 1
    var spanE = maxE - minE || 1

    ctx.clearRect(0, 0, width, height)
    ctx.setStrokeStyle('#E5E7EB')
    ctx.setLineWidth(1)
    ctx.beginPath()
    ctx.moveTo(pad, height - pad)
    ctx.lineTo(width - pad, height - pad)
    ctx.stroke()

    ctx.setStrokeStyle('#F04452')
    ctx.setLineWidth(3)
    ctx.beginPath()
    profile.forEach(function (point, index) {
      var x = pad + ((Number(point[0]) || 0) - minD) / spanD * (width - pad * 2)
      var y = height - pad - ((Number(point[1]) || 0) - minE) / spanE * (height - pad * 2)
      if (index === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()
    ctx.draw()
  },

  onStartMeetup: function () {
    var routeBookId = this.data.guide && this.data.guide.route_book_id
    if (!routeBookId) {
      wx.showToast({ title: '路线暂不可发起约骑', icon: 'none' })
      return
    }
    wx.navigateTo({ url: '/pages/meetup-create/meetup-create?route_book_id=' + encodeURIComponent(routeBookId) })
  },
})
