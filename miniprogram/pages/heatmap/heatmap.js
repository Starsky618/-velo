const api = require('../../utils/api')
const heatmapMap = require('../../utils/heatmap-map')
const { gcj02ToWgs84 } = require('../../utils/coords')

const OVERVIEW_MAX_POINTS = 9000
const HEATMAP_LINE_WIDTH = 2
const HEATMAP_LINE_OPACITY = '52'
const MIN_TILE_ZOOM = 8
const MAX_TILE_ZOOM = 18
const MAX_VISIBLE_TILES = 16

function tileXForLongitude(longitude, zoom) {
  var count = Math.pow(2, zoom)
  return Math.floor((longitude + 180) / 360 * count)
}

function tileYForLatitude(latitude, zoom) {
  var count = Math.pow(2, zoom)
  var limited = Math.max(-85.05112878, Math.min(85.05112878, latitude))
  var radians = limited * Math.PI / 180
  return Math.floor((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2 * count)
}

function latitudeForTileY(tileY, zoom) {
  var mercator = Math.PI * (1 - 2 * tileY / Math.pow(2, zoom))
  return Math.atan(Math.sinh(mercator)) * 180 / Math.PI
}

function boundsForTile(zoom, x, y) {
  var count = Math.pow(2, zoom)
  return {
    southwest: {
      longitude: x / count * 360 - 180,
      latitude: latitudeForTileY(y + 1, zoom),
    },
    northeast: {
      longitude: (x + 1) / count * 360 - 180,
      latitude: latitudeForTileY(y, zoom),
    },
  }
}

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
    this._pageAlive = true
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
    this._pageReady = true
    if (this._overviewLoaded) {
      this._ensureMapContext()
      this._scheduleViewportRefresh(220)
    }
  },

  onUnload() {
    this._pageAlive = false
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    this._viewportTimer = null
    this._overviewRequestSeq = (this._overviewRequestSeq || 0) + 1
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._viewportReadSeq = (this._viewportReadSeq || 0) + 1
    this._viewportReadRetries = 0
    this._clearTileOverlays()
    this._tileFileCache = {}
    this._tileDownloadPromises = {}
  },

  _endpoint() {
    return this._userId > 0
      ? '/api/user/' + this._userId + '/heatmap'
      : '/api/user/me/heatmap'
  },

  _tileEndpoint(zoom, x, y) {
    var base = this._userId > 0
      ? '/api/user/' + this._userId + '/heatmap/tiles/'
      : '/api/user/me/heatmap/tiles/'
    var params = ['color=' + encodeURIComponent(this.data.selectedColor)]
    if (this.data.selectedYear !== null) params.push('year=' + this.data.selectedYear)
    return base + zoom + '/' + x + '/' + y + '.png?' + params.join('&')
  },

  _fetchHeatmap(year, initial) {
    var params = { detail: 'full' }
    if (year !== null) params.year = year
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    this._viewportTimer = null
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._viewportReadSeq = (this._viewportReadSeq || 0) + 1
    this._viewportReadRetries = 0
    this._lastTileSetKey = ''
    var overviewRequestSeq = (this._overviewRequestSeq || 0) + 1
    this._overviewRequestSeq = overviewRequestSeq
    this.setData(initial ? { loading: true, error: '' } : { updating: true })

    api.get(this._endpoint(), params)
      .then((data) => {
        if (this._pageAlive === false || overviewRequestSeq !== this._overviewRequestSeq) return
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
          this._clearTileOverlays()
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
        this._overviewRenderedColor = this.data.selectedColor
        this._focusPoints = model.focusPoints
        this._allPoints = model.allPoints
        this.setData({
          loading: false,
          updating: false,
          error: '',
          isEmpty: false,
          center: model.center,
          includePoints: model.focusPoints,
          polylines: this._tileLayerVisible ? [] : model.polylines,
          activityCount: Number(data && data.activity_count) || 0,
          selectedYear: year,
          selectedYearLabel: year === null ? '全部年份' : String(year) + ' 年',
          yearOptions: yearOptions(availableYears, year),
          focusMode: 'local',
        }, () => {
          this._ensureMapContext()
          this._scheduleViewportRefresh(260)
        })
      })
      .catch(() => {
        if (this._pageAlive === false || overviewRequestSeq !== this._overviewRequestSeq) return
        if (initial) {
          this.setData({ loading: false, updating: false, error: '热图暂时加载失败' })
          return
        }
        this.setData({ updating: false })
        wx.showToast({ title: '切换失败，请重试', icon: 'none' })
      })
  },

  _ensureMapContext() {
    if (!this._pageReady || this._mapContext || typeof wx.createMapContext !== 'function') {
      return this._mapContext || null
    }
    this._mapContext = wx.createMapContext('personal-heatmap-map', this)
    return this._mapContext
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
    var overviewTracks = this._overviewPreparedTracks || []
    this.setData({
      selectedColor: key,
      colorOptions: colorOptions(key),
      updating: true,
      polylines: this._tileLayerVisible
        ? this.data.polylines
        : heatmapMap.buildPolylines(
          overviewTracks,
          key,
          HEATMAP_LINE_WIDTH,
          HEATMAP_LINE_OPACITY
        ),
    }, () => {
      this._overviewRenderedColor = key
      this._lastTileSetKey = ''
      this._scheduleViewportRefresh(0)
    })
  },

  onMapRegionChange(event) {
    if (!event) return
    var eventScale = Number(event.detail && event.detail.scale)
    if (Number.isFinite(eventScale)) this._lastMapScale = eventScale
    if (event.type === 'end') this._scheduleViewportRefresh(180)
  },

  _scheduleViewportRefresh(delay) {
    if (this._pageAlive === false || !this._ensureMapContext() || !this._overviewLoaded) return
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    var readSeq = (this._viewportReadSeq || 0) + 1
    this._viewportReadSeq = readSeq
    this._viewportTimer = setTimeout(() => {
      this._viewportTimer = null
      this._readViewport().then((viewport) => {
        this._handleViewportRead(readSeq, viewport)
      })
    }, Math.max(0, Number(delay) || 0))
  },

  _handleViewportRead(readSeq, viewport) {
    if (this._pageAlive === false || readSeq !== this._viewportReadSeq) return
    if (viewport) {
      this._viewportReadRetries = 0
      this._fetchViewport(viewport)
      return
    }
    this._viewportReadRetries = (this._viewportReadRetries || 0) + 1
    if (this._viewportReadRetries <= 2) this._scheduleViewportRefresh(350)
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
              mapWest: Number(southwest.longitude),
              mapSouth: Number(southwest.latitude),
              mapEast: Number(northeast.longitude),
              mapNorth: Number(northeast.latitude),
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
    if (this._pageAlive === false) return
    // 全国视角继续用轻量总览；城市与街区改用服务端栅格瓦片，不再把 GPS 点塞进 polyline。
    if (viewport.zoom < MIN_TILE_ZOOM || viewport.east - viewport.west > 20 || viewport.north - viewport.south > 15) {
      this._showOverviewLayer()
      return
    }
    this._refreshTileLayer(viewport)
  },

  _visibleTiles(viewport) {
    var zoom = Math.max(MIN_TILE_ZOOM, Math.min(MAX_TILE_ZOOM, Math.round(viewport.zoom)))
    var count = Math.pow(2, zoom)
    var minX = Math.max(0, tileXForLongitude(viewport.mapWest, zoom))
    var maxX = Math.min(count - 1, tileXForLongitude(viewport.mapEast, zoom))
    var minY = Math.max(0, tileYForLatitude(viewport.mapNorth, zoom))
    var maxY = Math.min(count - 1, tileYForLatitude(viewport.mapSouth, zoom))
    var tiles = []
    for (var y = minY; y <= maxY; y++) {
      for (var x = minX; x <= maxX; x++) {
        tiles.push({ zoom: zoom, x: x, y: y })
      }
    }
    if (tiles.length <= MAX_VISIBLE_TILES) return tiles
    var centerX = (minX + maxX) / 2
    var centerY = (minY + maxY) / 2
    return tiles.sort(function (a, b) {
      return Math.hypot(a.x - centerX, a.y - centerY) - Math.hypot(b.x - centerX, b.y - centerY)
    }).slice(0, MAX_VISIBLE_TILES)
  },

  _tileKey(tile) {
    return [
      tile.zoom,
      tile.x,
      tile.y,
      this.data.selectedYear === null ? 'all' : this.data.selectedYear,
      this.data.selectedColor,
    ].join(':')
  },

  _addGroundOverlay(tile, filePath, id) {
    var context = this._mapContext
    if (!context || typeof context.addGroundOverlay !== 'function') {
      return Promise.reject(new Error('ground overlay unsupported'))
    }
    return new Promise(function (resolve, reject) {
      context.addGroundOverlay({
        id: id,
        src: filePath,
        bounds: boundsForTile(tile.zoom, tile.x, tile.y),
        visible: true,
        zIndex: 5,
        opacity: 1,
        success: resolve,
        fail: reject,
      })
    })
  },

  _removeGroundOverlay(id) {
    var context = this._mapContext
    if (!context || typeof context.removeGroundOverlay !== 'function') return
    context.removeGroundOverlay({ id: id })
  },

  _loadTileFile(tile, key) {
    var cache = this._tileFileCache || (this._tileFileCache = {})
    if (cache[key]) return Promise.resolve(cache[key])
    var inflight = this._tileDownloadPromises || (this._tileDownloadPromises = {})
    if (inflight[key]) return inflight[key]
    var request = api.downloadTemporaryFile(this._tileEndpoint(tile.zoom, tile.x, tile.y))
      .then(function (file) {
        var path = file && (file.filePath || file.tempFilePath)
        if (!path) throw new Error('heatmap tile has no local path')
        cache[key] = path
        delete inflight[key]
        return path
      }, function (error) {
        delete inflight[key]
        throw error
      })
    inflight[key] = request
    return request
  },

  _refreshTileLayer(viewport) {
    var tiles = this._visibleTiles(viewport)
    var setKey = tiles.map((tile) => this._tileKey(tile)).join('|')
    if (setKey && setKey === this._lastTileSetKey) {
      if (this.data.updating) this.setData({ updating: false })
      return
    }
    this._lastTileSetKey = setKey
    var requestSeq = (this._viewportRequestSeq || 0) + 1
    this._viewportRequestSeq = requestSeq
    var active = this._activeTileOverlays || {}
    var desired = {}
    var downloads = []
    tiles.forEach((tile) => {
      var key = this._tileKey(tile)
      desired[key] = true
      if (active[key]) return
      var id = (this._tileIdSeed || 1000) + 1
      this._tileIdSeed = id
      downloads.push(
        this._loadTileFile(tile, key)
          .then((filePath) => this._addGroundOverlay(tile, filePath, id))
          .then(() => ({ key: key, id: id }))
          .catch(() => null)
      )
    })
    this.setData({ updating: downloads.length > 0 })
    Promise.all(downloads).then((added) => {
      if (this._pageAlive === false || requestSeq !== this._viewportRequestSeq) {
        added.forEach((item) => { if (item) this._removeGroundOverlay(item.id) })
        return
      }
      added.forEach(function (item) { if (item) active[item.key] = item })
      var visibleCount = Object.keys(active).filter(function (key) { return desired[key] }).length
      if (visibleCount === 0 && Object.keys(active).length > 0) {
        // 新视野全部下载失败时保留上一帧图片，下一次 regionchange 再重试，不能闪成空地图。
        this._lastTileSetKey = ''
        this._activeTileOverlays = active
        this.setData({ updating: false })
        return
      }
      var desiredCount = Object.keys(desired).length
      var hasStaleFrame = Object.keys(active).some(function (key) { return !desired[key] })
      if (visibleCount < desiredCount && hasStaleFrame) {
        // 只成功一部分时继续保留旧帧；等所有新瓦片齐了再原子替换，避免拖图出现棋盘缺口。
        this._lastTileSetKey = ''
        this._activeTileOverlays = active
        this.setData({ updating: false })
        return
      }
      visibleCount = 0
      Object.keys(active).forEach((key) => {
        if (desired[key]) {
          visibleCount += 1
          return
        }
        this._removeGroundOverlay(active[key].id)
        delete active[key]
      })
      this._activeTileOverlays = active
      this._tileLayerVisible = visibleCount > 0
      // 至少一张真实瓦片成功后才撤掉旧折线，避免网络故障时整张热图闪空。
      this.setData({
        updating: false,
        polylines: visibleCount > 0 ? [] : this.data.polylines,
      })
    })
  },

  _clearTileOverlays() {
    var active = this._activeTileOverlays || {}
    Object.keys(active).forEach((key) => this._removeGroundOverlay(active[key].id))
    this._activeTileOverlays = {}
    this._lastTileSetKey = ''
    this._tileLayerVisible = false
  },

  _showOverviewLayer() {
    var tracks = this._overviewPreparedTracks || []
    var hadTileLayer = this._tileLayerVisible
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._viewportReadSeq = (this._viewportReadSeq || 0) + 1
    this._clearTileOverlays()
    if (!tracks.length) return
    if (
      this._renderedTracks === tracks
      && !hadTileLayer
      && this._overviewRenderedColor === this.data.selectedColor
    ) {
      if (this.data.updating) this.setData({ updating: false })
      return
    }
    this._renderedTracks = tracks
    this._overviewRenderedColor = this.data.selectedColor
    this.setData({
      updating: false,
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
