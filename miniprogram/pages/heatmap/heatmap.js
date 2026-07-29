const api = require('../../utils/api')
const heatmapMap = require('../../utils/heatmap-map')
const { gcj02ToWgs84 } = require('../../utils/coords')
const MIN_TILE_ZOOM = 3
const MAX_TILE_ZOOM = 18
const MAX_VISIBLE_TILES = 16
const HEATMAP_LINE_WIDTH = 3
const HEATMAP_LINE_OPACITY = 'C8'

function isDeveloperTools() {
  try {
    if (typeof wx.getDeviceInfo === 'function') {
      return wx.getDeviceInfo().platform === 'devtools'
    }
    return wx.getSystemInfoSync().platform === 'devtools'
  } catch (error) {
    return false
  }
}

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
    // 微信开发者工具至今不渲染 addGroundOverlay；IDE 走同源原始轨迹 LOD，真机走 PNG 瓦片。
    this._preferVectorLayer = isDeveloperTools()
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
    if (this._metadataLoaded) {
      this._ensureMapContext()
      this._scheduleViewportRefresh(220)
    }
  },

  onUnload() {
    this._pageAlive = false
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    this._viewportTimer = null
    this._metadataRequestSeq = (this._metadataRequestSeq || 0) + 1
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._vectorRequestSeq = (this._vectorRequestSeq || 0) + 1
    this._viewportReadSeq = (this._viewportReadSeq || 0) + 1
    this._viewportReadRetries = 0
    this._clearTileOverlays()
    this._tileFileCache = {}
    this._tileDownloadPromises = {}
    this._vectorPreparedTracks = []
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
    var params = { detail: 'meta' }
    if (year !== null) params.year = year
    if (this._viewportTimer) clearTimeout(this._viewportTimer)
    this._viewportTimer = null
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._vectorRequestSeq = (this._vectorRequestSeq || 0) + 1
    this._viewportReadSeq = (this._viewportReadSeq || 0) + 1
    this._viewportReadRetries = 0
    this._lastTileSetKey = ''
    var metadataRequestSeq = (this._metadataRequestSeq || 0) + 1
    this._metadataRequestSeq = metadataRequestSeq
    this.setData(initial ? { loading: true, error: '' } : { updating: true })

    api.get(this._endpoint(), params)
      .then((data) => {
        if (this._pageAlive === false || metadataRequestSeq !== this._metadataRequestSeq) return
        var model = heatmapMap.buildHeatmapMetaModel(
          data && data.focus_points,
          data && data.all_points
        )
        var availableYears = data && Array.isArray(data.available_years) ? data.available_years : []
        var activityCount = Number(data && data.activity_count) || 0
        if (!model || activityCount === 0) {
          this._metadataLoaded = false
          this._focusPoints = []
          this._allPoints = []
          this._vectorPreparedTracks = []
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

        this._metadataLoaded = true
        this._focusPoints = model.focusPoints
        this._allPoints = model.allPoints
        this.setData({
          loading: false,
          updating: false,
          error: '',
          isEmpty: false,
          center: model.center,
          includePoints: model.focusPoints,
          activityCount: activityCount,
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
        if (this._pageAlive === false || metadataRequestSeq !== this._metadataRequestSeq) return
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
    var prepared = this._vectorPreparedTracks || []
    this.setData({
      selectedColor: key,
      colorOptions: colorOptions(key),
      updating: !this._preferVectorLayer || prepared.length === 0,
      polylines: this._preferVectorLayer && prepared.length
        ? heatmapMap.buildPolylines(prepared, key, HEATMAP_LINE_WIDTH, HEATMAP_LINE_OPACITY)
        : this.data.polylines,
    }, () => {
      if (this._preferVectorLayer && prepared.length) return
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
    if (this._pageAlive === false || !this._ensureMapContext() || !this._metadataLoaded) return
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
              zoom: Math.max(3, Math.min(20, Math.round(Number(scale) || fallbackScale))),
              west: swWgs[1],
              south: swWgs[0],
              east: neWgs[1],
              north: neWgs[0],
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
    if (this._preferVectorLayer) {
      this._refreshVectorLayer(viewport)
      return
    }
    this._refreshTileLayer(viewport)
  },

  _refreshVectorLayer(viewport) {
    // 全国视角超出视野接口边界时保持当前帧；用户回到城市/街区后立即恢复高精度 LOD。
    if (viewport.east - viewport.west > 20 || viewport.north - viewport.south > 15) {
      if (this.data.updating) this.setData({ updating: false })
      return
    }
    var requestSeq = (this._vectorRequestSeq || 0) + 1
    this._vectorRequestSeq = requestSeq
    var params = {
      detail: 'viewport',
      west: viewport.west,
      south: viewport.south,
      east: viewport.east,
      north: viewport.north,
      zoom: viewport.zoom,
    }
    if (this.data.selectedYear !== null) params.year = this.data.selectedYear
    this.setData({ updating: true })
    api.get(this._endpoint(), params)
      .then((data) => {
        if (this._pageAlive === false || requestSeq !== this._vectorRequestSeq) return
        var prepared = heatmapMap.prepareTracks(data && data.tracks)
        this._vectorPreparedTracks = prepared
        this.setData({
          updating: false,
          polylines: heatmapMap.buildPolylines(
            prepared,
            this.data.selectedColor,
            HEATMAP_LINE_WIDTH,
            HEATMAP_LINE_OPACITY
          ),
        })
      })
      .catch(() => {
        if (this._pageAlive === false || requestSeq !== this._vectorRequestSeq) return
        this.setData({ updating: false })
      })
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
      var settled = false
      var timeout = setTimeout(function () {
        rejectOnce(new Error('ground overlay timed out'))
      }, 4000)
      var resolveOnce = function () {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        resolve()
      }
      var rejectOnce = function (error) {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        reject(error)
      }
      context.addGroundOverlay({
        id: id,
        src: filePath,
        bounds: boundsForTile(tile.zoom, tile.x, tile.y),
        visible: true,
        zIndex: 5,
        opacity: 1,
        success: resolveOnce,
        fail: rejectOnce,
        // 开发者工具 2.02.2607161 实测图层已出现但 success 不回调；complete 才是稳定收口。
        complete: function (result) {
          if (result && /:fail/.test(result.errMsg || '')) rejectOnce(result)
          else resolveOnce()
        },
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
      var idSeed = (this._tileIdSeed || 1000) + 1
      this._tileIdSeed = idSeed
      // 微信 MapContext 合同要求 String id；传 Number 会静默不渲染且不回调。
      var id = 'heatmap-full-' + idSeed
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
      var desiredCount = Object.keys(desired).length
      if (visibleCount === 0 && added.every(function (item) { return !item })) {
        // 某些微信运行环境不实现图片图层；自动降级到同源原始轨迹 LOD，不能留空白地图。
        this._lastTileSetKey = ''
        this._activeTileOverlays = active
        this._preferVectorLayer = true
        this._refreshVectorLayer(viewport)
        return
      }
      if (visibleCount < desiredCount) {
        // 任一图片失败就保留上一套完整瓦片，避免颜色/年份切换时混成半帧。
        added.forEach((item) => {
          if (!item) return
          this._removeGroundOverlay(item.id)
          delete active[item.key]
        })
        this._lastTileSetKey = ''
        this._activeTileOverlays = active
        if (Object.keys(active).length === 0) {
          // 首帧只成功一部分时，上面会撤回半帧；此时必须降级为矢量层，不能留下空白地图。
          this._preferVectorLayer = true
          this._refreshVectorLayer(viewport)
          return
        }
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
      this.setData({ updating: false })
    })
  },

  _clearTileOverlays() {
    var active = this._activeTileOverlays || {}
    Object.keys(active).forEach((key) => this._removeGroundOverlay(active[key].id))
    this._activeTileOverlays = {}
    this._lastTileSetKey = ''
    this._tileLayerVisible = false
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
