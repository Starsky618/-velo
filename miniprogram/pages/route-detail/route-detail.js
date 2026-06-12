const api = require('../../utils/api')
const { renderMarkdown, splitSections } = require('../../utils/md-render')
const { wgs84ToGcj02 } = require('../../utils/coords')
const mapTheme = require('../../utils/map-theme')
const routeThumb = require('../../utils/route-thumb')
const routeMapNav = require('../../utils/route-map-nav')

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

function buildSections(markdown) {
  return splitSections(markdown)
    .filter(function (section) {
      return section.title !== '真实画面' && String(section.body || '').trim()
    })
    .map(function (section) {
      return {
        title: section.title,
        body: section.body,
        expanded: false,
        nodes: renderMarkdown(section.body),
        hasElevationSlot: section.title === '核心数据',
        hasMapSlot: section.title === '怎么骑',
      }
    })
}

// 常显数据卡：距离/爬升/均坡——有哪项放哪项，缺的不进数组（no-dash 原则：不显示占位）
function buildStats(guide) {
  var stats = []
  var d = Number(guide.distance)
  var c = Number(guide.climb)
  if (Number.isFinite(d) && d > 0) stats.push({ v: d.toFixed(1), u: 'km', k: '距离' })
  if (Number.isFinite(c) && c > 0) stats.push({ v: String(Math.round(c)), u: 'm', k: '爬升' })
  if (Number.isFinite(d) && d > 0 && Number.isFinite(c) && c > 0) {
    // 均坡 = 爬升(米) / 距离(公里×1000) ×100；API 距离返 km、爬升返米（项目约定）
    stats.push({ v: (c / (d * 1000) * 100).toFixed(1), u: '%', k: '均坡' })
  }
  return stats
}

Page({
  data: {
    guideId: null,
    loading: true,
    error: '',
    guide: null,
    sections: [],
    highlights: [],
    introText: '',
    coverSrc: '/assets/route-placeholder.svg',
    gallerySrcs: [],   // 实景图完整 URL 数组；空 = 不渲染长廊（no-dash：缺内容整块消失）
    hasElevation: false,
    routeStats: [],
    routePreviewVisible: false,
    routePreviewCenter: { latitude: 37.8706, longitude: 112.5489 },
    routePreviewMarkers: [],
    routePreviewPolylines: [],
    routePreviewIncludePoints: [],
  },

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
        // 相对路径（/uploads/...）拼 baseUrl，与列表页同规则——封面和实景图共用这把尺子
        var base = (getApp().globalData && getApp().globalData.baseUrl) || ''
        var toFullUrl = function (url) {
          return url && url.indexOf('/uploads/') === 0 ? base + url : url
        }
        that.setData(Object.assign({
          guide: guide,
          sections: buildSections(guide.content_md),
          highlights: Array.isArray(guide.highlights) ? guide.highlights : [],
          introText: Array.isArray(guide.highlights) && guide.highlights.length ? guide.highlights[0] : '',
          coverSrc: toFullUrl(guide.cover_url) || '/assets/route-placeholder.svg',
          gallerySrcs: (Array.isArray(guide.gallery_urls) ? guide.gallery_urls : [])
            .map(toFullUrl)
            .filter(Boolean),
          hasElevation: hasElevation,
          routeStats: buildStats(guide),
          loading: false,
          // 折叠区大图不在 onLoad 画：全折叠态下 canvas 在 hidden 祖先里画了也是空白——
          // 唯一生效的绘制时机是 toggleSection 展开「核心数据」那一刻（集成审 I1）。
          // 常显缩略图不受此限：它在页面骨架上，setData 回调 + setTimeout 兜底即画（陷阱 #17）
        }, preview), function () {
          if (hasElevation) {
            setTimeout(function () {
              that.drawElevationThumb(guide.elevation_profile)
            }, 100)
          }
        })
      })
      .catch(function () {
        that.setData({ loading: false, error: '路线暂时加载失败' })
      })
  },

  toggleSection: function (event) {
    var index = Number(event.currentTarget.dataset.index)
    var sections = this.data.sections || []
    if (!Number.isInteger(index) || index < 0 || index >= sections.length) return
    var nextExpanded = !sections[index].expanded
    var that = this
    this.setData({
      ['sections[' + index + '].expanded']: nextExpanded,
    }, function () {
      if (nextExpanded && sections[index].hasElevationSlot && that.data.hasElevation && that.data.guide) {
        that.drawElevation(that.data.guide.elevation_profile)
      }
      if (nextExpanded && sections[index].hasMapSlot && that.data.routePreviewVisible) {
        that.drawRoutePreviewThumb()
      }
    })
  },

  // 展示型路线卡不再交给腾讯原生地图：免费链路画不出真实浅色底图，
  // 所以这里用自绘纸面 + 橙色轨迹，让用户第一眼看到统一的路线形状。
  drawRoutePreviewThumb: function () {
    var that = this
    if (!this.data.routePreviewVisible) return
    setTimeout(function () {
      routeThumb.drawRouteThumb('route-paper-preview', that.data.routePreviewIncludePoints, {
        width: 320,
        height: 180,
        lineWidth: 4,
        dotR: 6,
        paper: true,
      })
    }, 120)
  },

  onOpenRouteMapPage: function () {
    routeMapNav.openRouteMapPage({
      title: (this.data.guide && this.data.guide.name) || '路线地图',
      center: this.data.routePreviewCenter,
      markers: this.data.routePreviewMarkers,
      polylines: this.data.routePreviewPolylines,
      includePoints: this.data.routePreviewIncludePoints,
    })
  },

  // 常显海拔缩略线：橙线 + 浅橙面积填充，无轴无标注（坡的形状一眼可读）。
  // 旧 canvas API 坐标单位 px，必须与 wxss 尺寸严格 2:1 对应（622rpx×140rpx = 311×70px），否则拉伸变形
  drawElevationThumb: function (profile) {
    if (!Array.isArray(profile) || profile.length < 2) return
    var ctx = wx.createCanvasContext('elevation-thumb', this)
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

  // 点实景图 → 微信原生看图器全屏预览（自带左右翻页/双指缩放/长按保存，零成本）
  onTapGalleryPhoto: function (event) {
    var src = event.currentTarget.dataset.src
    var urls = this.data.gallerySrcs || []
    if (!src || !urls.length) return
    wx.previewImage({ current: src, urls: urls })
  },

  onStartMeetup: function () {
    // 按钮常显（Tim 2026-06-11 拍）：有精确轨迹 → 向导自动选好这条路线；
    // 还没轨迹（track_pending）→ 照样进向导，路线由用户在向导里自己选——
    // 不弹"不可发起"把人挡在门外，约骑的热情比预填的便利更金贵。
    var routeBookId = this.data.guide && this.data.guide.route_book_id
    var url = '/pages/meetup-create/meetup-create'
    if (routeBookId) {
      url += '?route_book_id=' + encodeURIComponent(routeBookId)
    }
    wx.navigateTo({ url: url })
  },
})
