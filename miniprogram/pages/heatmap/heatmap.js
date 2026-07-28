const api = require('../../utils/api')
const heatmapMap = require('../../utils/heatmap-map')
const { gcj02ToWgs84 } = require('../../utils/coords')

const OVERVIEW_MAX_POINTS = 9000
const VIEWPORT_MAX_POINTS = 36000
const HEATMAP_LINE_WIDTH = 2
const HEATMAP_LINE_OPACITY = '52'

function colorOptions(selectedKey) {
  return heatmapMap.HEATMAP_COLORS.map(function (item) {
    return {
      key: item.key,
      label: item.label,
      selected: item.key === selectedKey,
    }
  })
}

function yearOptions(years, selectedYear) {
  var options = [{ value: 'all', label: '全部', selected: selectedYear === null }]
  ;(Array.isArray(years) ? years : []).forEach(function (year) {
    options.push({
      value: String(year),
      label: String(year),
      selected: year === selectedYear,
    })
  })
  return options
}

function isKnownColor(key) {
  return heatmapMap.HEATMAP_COLORS.some(function (item) { return item.key === key })
}

Page({
  data: {
    loading: true,
    updating: false,
    error: '',
    isEmpty: false,
    center: { latitude: 39.9042, longitude: 116.4074 },
    includePoints: [],
    polylines: [],
    activityCount: 0,
    selectedYear: null,
    selectedYearLabel: '全部年份',
    yearOptions: [{ value: 'all', label: '全部', selected: true }],
    selectedColor: 'orange',
    colorOptions: colorOptions('orange'),
    layerOpen: false,
    focusMode: 'local',
  },

  onLoad(options) {
    var requestedUserId = Number(options && options.userId)
    this._userId = Number.isInteger(requestedUserId) && requestedUserId > 0 ? requestedUserId : 0
    var savedColor = wx.getStorageSync('heatmapColor')
    var selectedColor = isKnownColor(savedColor) ? savedColor : 'orange'
    this.setData({
      selectedColor: selectedColor,
      colorOptions: colorOptions(selectedColor),
    })
    wx.setNavigationBarTitle({ title: this._userId > 0 ? '骑行热图' : '我的骑行热图' })
    this._fetchHeatmap(null, true)
  },

  onReady() {
    if (typeof wx.createMapContext === 'function') {
      this._mapContext = wx.createMapContext('personal-heatmap-map', this)
    }
    if (this._overviewLoaded) this._scheduleViewportRefresh(220)
  },

  onUnload() {
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
  },

  _endpoint() {
    return this._userId > 0
      ? '/api/user/' + this._userId + '/heatmap'
      : '/api/user/me/heatmap'
  },

  _fetchHeatmap(year, initial) {
    var params = { detail: 'full' }
    if (year !== null) params.year = year
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    this._viewportTimer = null
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._lastViewportKey = ''
    this.setData(initial ? { loading: true, error: '' } : { updating: true })

    api.get(this._endpoint(), params)
      .then((data) => {
        var tracks = data && Array.isArray(data.tracks) ? data.tracks : []
        // 全屏比个人页精细，但仍控制渲染层体积；缩放探索不需要原始 GPS 采样率。
        var model = heatmapMap.buildHeatmapMapModel(
          tracks,
          this.data.selectedColor,
          HEATMAP_LINE_WIDTH,
          OVERVIEW_MAX_POINTS,
          HEATMAP_LINE_OPACITY
        )
        var availableYears = data && Array.isArray(data.available_years) ? data.available_years : []
        if (!model) {
          this._overviewLoaded = false
          this._overviewPreparedTracks = []
          this._renderedTracks = []
          this._focusPoints = []
          this._allPoints = []
          this.setData({
            loading: false,
            updating: false,
            error: '',
            isEmpty: true,
            polylines: [],
            activityCount: 0,
            selectedYear: year,
            selectedYearLabel: year === null ? '全部年份' : String(year) + ' 年',
            yearOptions: yearOptions(availableYears, year),
          })
          return
        }

        this._overviewLoaded = true
        this._overviewPreparedTracks = model.preparedTracks
        this._renderedTracks = model.preparedTracks
        this._focusPoints = model.focusPoints
        this._allPoints = model.allPoints
        this.setData({
          loading: false,
          updating: false,
          error: '',
          isEmpty: false,
          center: model.center,
          includePoints: model.focusPoints,
          polylines: model.polylines,
          activityCount: Number(data && data.activity_count) || 0,
          selectedYear: year,
          selectedYearLabel: year === null ? '全部年份' : String(year) + ' 年',
          yearOptions: yearOptions(availableYears, year),
          focusMode: 'local',
        }, () => this._scheduleViewportRefresh(260))
      })
      .catch(() => {
        if (initial) {
          this.setData({ loading: false, updating: false, error: '热图暂时加载失败' })
          return
        }
        this.setData({ updating: false })
        wx.showToast({ title: '切换失败，请重试', icon: 'none' })
      })
  },

  onRetry() {
    this._fetchHeatmap(this.data.selectedYear, true)
  },

  onToggleLayer() {
    this.setData({ layerOpen: !this.data.layerOpen })
  },

  onCloseLayer() {
    this.setData({ layerOpen: false })
  },

  onSelectYear(event) {
    var raw = event.currentTarget.dataset.year
    var year = raw === 'all' ? null : Number(raw)
    if (year === this.data.selectedYear || (!Number.isInteger(year) && year !== null)) return
    this._fetchHeatmap(year, false)
  },

  onSelectColor(event) {
    var key = event.currentTarget.dataset.color
    if (!isKnownColor(key) || key === this.data.selectedColor) return
    wx.setStorageSync('heatmapColor', key)
    this.setData({
      selectedColor: key,
      colorOptions: colorOptions(key),
      polylines: heatmapMap.buildPolylines(
        this._renderedTracks || this._overviewPreparedTracks || [],
        key,
        HEATMAP_LINE_WIDTH,
        HEATMAP_LINE_OPACITY
      ),
    })
  },

  onMapRegionChange(event) {
    if (!event) return
    var eventScale = Number(event.detail && event.detail.scale)
    if (Number.isFinite(eventScale)) this._lastMapScale = eventScale
    if (event.type === 'end') this._scheduleViewportRefresh(180)
  },

  _scheduleViewportRefresh(delay) {
    if (!this._mapContext || !this._overviewLoaded) return
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    this._viewportTimer = setTimeout(() => {
      this._viewportTimer = null
      this._readViewport().then((viewport) => {
        if (viewport) this._fetchViewport(viewport)
      })
    }, Math.max(0, Number(delay) || 0))
  },

  _readViewport() {
    var context = this._mapContext
    if (!context || typeof context.getRegion !== 'function') return Promise.resolve(null)
    var fallbackScale = Number(this._lastMapScale) || 10
    return new Promise(function (resolve) {
      context.getRegion({
        success: function (region) {
          var southwest = region && region.southwest
          var northeast = region && region.northeast
          if (!southwest || !northeast) {
            resolve(null)
            return
          }
          var finish = function (scale) {
            var swWgs = gcj02ToWgs84(Number(southwest.latitude), Number(southwest.longitude))
            var neWgs = gcj02ToWgs84(Number(northeast.latitude), Number(northeast.longitude))
            var viewport = {
              west: swWgs[1],
              south: swWgs[0],
              east: neWgs[1],
              north: neWgs[0],
              zoom: Math.max(3, Math.min(20, Math.round(Number(scale) || fallbackScale))),
            }
            if (
              !Number.isFinite(viewport.west) || !Number.isFinite(viewport.south)
              || !Number.isFinite(viewport.east) || !Number.isFinite(viewport.north)
              || viewport.west >= viewport.east || viewport.south >= viewport.north
            ) {
              resolve(null)
              return
            }
            resolve(viewport)
          }
          if (typeof context.getScale !== 'function') {
            finish(fallbackScale)
            return
          }
          context.getScale({
            success: function (result) { finish(result && result.scale) },
            fail: function () { finish(fallbackScale) },
          })
        },
        fail: function () { resolve(null) },
      })
    })
  },

  _fetchViewport(viewport) {
    // 跨省/全国视角继续使用首屏总览；城市及街区视角才请求高精度视野数据。
    if (viewport.zoom < 8 || viewport.east - viewport.west > 20 || viewport.north - viewport.south > 15) {
      this._showOverviewLayer()
      return
    }
    var key = [
      viewport.zoom,
      viewport.west.toFixed(4),
      viewport.south.toFixed(4),
      viewport.east.toFixed(4),
      viewport.north.toFixed(4),
      this.data.selectedYear === null ? 'all' : this.data.selectedYear,
    ].join(':')
    if (key === this._lastViewportKey) return
    this._lastViewportKey = key
    var requestSeq = (this._viewportRequestSeq || 0) + 1
    this._viewportRequestSeq = requestSeq
    var params = {
      detail: 'viewport',
      west: Number(viewport.west.toFixed(5)),
      south: Number(viewport.south.toFixed(5)),
      east: Number(viewport.east.toFixed(5)),
      north: Number(viewport.north.toFixed(5)),
      zoom: viewport.zoom,
    }
    if (this.data.selectedYear !== null) params.year = this.data.selectedYear

    api.get(this._endpoint(), params)
      .then((data) => {
        if (requestSeq !== this._viewportRequestSeq) return
        var tracks = data && Array.isArray(data.tracks) ? data.tracks : []
        var model = heatmapMap.buildHeatmapMapModel(
          tracks,
          this.data.selectedColor,
          HEATMAP_LINE_WIDTH,
          VIEWPORT_MAX_POINTS,
          HEATMAP_LINE_OPACITY
        )
        this._renderedTracks = model ? model.preparedTracks : []
        this.setData({ polylines: model ? model.polylines : [] })
      })
      .catch(() => {
        if (requestSeq === this._viewportRequestSeq) this._lastViewportKey = ''
        // 保留上一帧图层：移动地图时网络抖动不闪白，也不打断用户继续探索。
      })
  },

  _showOverviewLayer() {
    var tracks = this._overviewPreparedTracks || []
    if (!tracks.length || this._renderedTracks === tracks) return
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._lastViewportKey = ''
    this._renderedTracks = tracks
    this.setData({
      polylines: heatmapMap.buildPolylines(
        tracks,
        this.data.selectedColor,
        HEATMAP_LINE_WIDTH,
        HEATMAP_LINE_OPACITY
      ),
    })
  },

  _fit(points, mode) {
    if (!Array.isArray(points) || points.length < 2) return
    // 不先写空数组：腾讯地图渲染层在 include-points 从 [] 切换时会读到
    // undefined.lat，导致“全部足迹”按钮报错并停止缩放。
    this.setData({ includePoints: points, focusMode: mode }, () => {
      if (this._mapContext && typeof this._mapContext.includePoints === 'function') {
        this._mapContext.includePoints({
          points: points,
          padding: [80, 48, 150, 48],
          complete: () => this._scheduleViewportRefresh(220),
        })
      }
    })
  },

  onFitLocal() {
    this._fit(this._focusPoints, 'local')
  },

  onFitAll() {
    this._fit(this._allPoints, 'all')
  },
})
