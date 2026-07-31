const api = require('../../utils/api')
const heatmapMap = require('../../utils/heatmap-map')
const heatmapProtocol = require('../../utils/heatmap-protocol')
const heatmapTileCache = require('../../utils/heatmap-tile-cache')
const { gcj02ToWgs84 } = require('../../utils/coords')
const MIN_TILE_ZOOM = 3
const MAX_TILE_ZOOM = 18
const MAX_VISIBLE_TILES = 16
const HEATMAP_LINE_WIDTH = 3
const HEATMAP_LINE_OPACITY = 'C8'
const LEGACY_OVERVIEW_MAX_POINTS = 9000
const GROUND_OVERLAY_ACK_TIMEOUT_MS = 4000

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

function vectorLineStyle(zoom) {
  // 开发者工具无法显示 PNG 热度瓦片，只能靠半透明矢量叠加表达密度。
  // 缩小时降低单次骑行亮度，常骑道路会因多次重叠自然变亮；放大后恢复验收过的线宽。
  if (zoom <= 10) return { width: 2, opacity: '2E' }
  if (zoom <= 11) return { width: 2, opacity: '48' }
  if (zoom <= 12) return { width: 3, opacity: '58' }
  return { width: HEATMAP_LINE_WIDTH, opacity: HEATMAP_LINE_OPACITY }
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
    // 微信开发者工具实测接受 addGroundOverlay 却不显示图片；IDE 使用同源矢量预览，
    // 真机使用版本化 PNG 瓦片。两条路径都从原始 Trackpoint 派生。
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
    this._lastVectorSetKey = ''
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
    params.push('v=' + encodeURIComponent(
      this._heatmapCacheVersion || ('g' + (this._heatmapGeneration || 0))
    ))
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
    this._lastVectorSetKey = ''
    var metadataRequestSeq = (this._metadataRequestSeq || 0) + 1
    this._metadataRequestSeq = metadataRequestSeq
    this.setData(initial ? { loading: true, error: '' } : { updating: true })

    var fallbackParams = { detail: 'full' }
    if (year !== null) fallbackParams.year = year
    var initialRequest = heatmapProtocol.shouldTryMeta()
      ? api.get(this._endpoint(), params)
        .then(function (data) { return { data: data, legacyProtocol: false } })
      : api.get(this._endpoint(), fallbackParams)
        .then(function (data) { return { data: data, legacyProtocol: true } })

    initialRequest
      .catch((error) => {
        if (
          this._pageAlive === false
          || metadataRequestSeq !== this._metadataRequestSeq
          || Number(error && error.code) !== 422
        ) {
          throw error
        }
        // 兼容尚未支持 meta/PNG 瓦片协议的线上后端。首次协商返回 422 时，
        // 用旧 full 响应完成首屏并固定走 viewport 矢量层，避免页面白屏或反复请求
        // 不存在的瓦片接口；后端升级后仍会自动使用上面的新协议。
        heatmapProtocol.markMetaUnsupported()
        return api.get(this._endpoint(), fallbackParams)
          .then(function (data) { return { data: data, legacyProtocol: true } })
      })
      .then((result) => {
        if (this._pageAlive === false || metadataRequestSeq !== this._metadataRequestSeq) return
        var data = result && result.data
        var legacyProtocol = Boolean(result && result.legacyProtocol)
        this._heatmapGeneration = Math.max(0, Number(data && data.generation) || 0)
        this._heatmapCacheVersion = String(
          data && data.cache_version || ('g' + this._heatmapGeneration)
        )
        var model = legacyProtocol
          ? heatmapMap.buildHeatmapMapModel(
            data && data.tracks,
            this.data.selectedColor,
            HEATMAP_LINE_WIDTH,
            LEGACY_OVERVIEW_MAX_POINTS,
            HEATMAP_LINE_OPACITY
          )
          : heatmapMap.buildHeatmapMetaModel(
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
        if (legacyProtocol) {
          this._preferVectorLayer = true
          this._vectorPreparedTracks = model.preparedTracks
        }
        this._focusPoints = model.focusPoints
        this._allPoints = model.allPoints
        this.setData({
          loading: false,
          updating: false,
          error: '',
          isEmpty: false,
          center: model.center,
          includePoints: model.focusPoints,
          polylines: legacyProtocol ? model.polylines : [],
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
    var vectorStyle = vectorLineStyle(this._lastVectorZoom || 13)
    this.setData({
      selectedColor: key,
      colorOptions: colorOptions(key),
      updating: !this._preferVectorLayer || prepared.length === 0,
      polylines: this._preferVectorLayer && prepared.length
        ? heatmapMap.buildPolylines(prepared, key, vectorStyle.width, vectorStyle.opacity)
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
    var requestViewport = this._vectorRequestViewport(viewport)
    if (requestViewport.key === this._lastVectorSetKey) {
      if (this.data.updating) this.setData({ updating: false })
      return
    }
    this._lastVectorSetKey = requestViewport.key
    this._lastVectorZoom = viewport.zoom
    var requestSeq = (this._vectorRequestSeq || 0) + 1
    this._vectorRequestSeq = requestSeq
    var params = {
      detail: 'viewport',
      west: requestViewport.west,
      south: requestViewport.south,
      east: requestViewport.east,
      north: requestViewport.north,
      zoom: requestViewport.zoom,
    }
    if (this.data.selectedYear !== null) params.year = this.data.selectedYear
    this.setData({ updating: !Array.isArray(this.data.polylines) || this.data.polylines.length === 0 })
    api.get(this._endpoint(), params)
      .then((data) => {
        if (this._pageAlive === false || requestSeq !== this._vectorRequestSeq) return
        var prepared = heatmapMap.prepareTracks(data && data.tracks)
        var style = vectorLineStyle(viewport.zoom)
        this._vectorPreparedTracks = prepared
        this.setData({
          updating: false,
          polylines: heatmapMap.buildPolylines(
            prepared,
            this.data.selectedColor,
            style.width,
            style.opacity
          ),
        })
      })
      .catch(() => {
        if (this._pageAlive === false || requestSeq !== this._vectorRequestSeq) return
        this._lastVectorSetKey = ''
        this.setData({ updating: false })
      })
  },

  _vectorRequestViewport(viewport) {
    // 请求边界吸附到地图瓦片网格。同一组可见瓦片内拖动只复用当前帧；跨格才请求，
    // 同时保证新视野边缘已经包含在上一次响应中，不会用“缓存”换来缺线。
    var zoom = Math.max(3, Math.min(20, Math.round(viewport.zoom)))
    var count = Math.pow(2, zoom)
    var minX = Math.max(0, tileXForLongitude(viewport.mapWest, zoom))
    var maxX = Math.min(count - 1, tileXForLongitude(viewport.mapEast, zoom))
    var minY = Math.max(0, tileYForLatitude(viewport.mapNorth, zoom))
    var maxY = Math.min(count - 1, tileYForLatitude(viewport.mapSouth, zoom))
    // 低倍率按 2x2、高倍率按 4x4 supertile 预取。z15-z19 拖动时不再每跨一个
    // 约百米小瓦片就请求一次；地图自身会裁掉块内屏幕外的轨迹。
    var vectorBlockSize = zoom >= 14 ? 4 : 2
    minX = Math.max(0, Math.floor(minX / vectorBlockSize) * vectorBlockSize)
    maxX = Math.min(
      count - 1,
      Math.ceil((maxX + 1) / vectorBlockSize) * vectorBlockSize - 1
    )
    minY = Math.max(0, Math.floor(minY / vectorBlockSize) * vectorBlockSize)
    maxY = Math.min(
      count - 1,
      Math.ceil((maxY + 1) / vectorBlockSize) * vectorBlockSize - 1
    )
    var mapWest = minX / count * 360 - 180
    var mapEast = (maxX + 1) / count * 360 - 180
    var mapNorth = latitudeForTileY(minY, zoom)
    var mapSouth = latitudeForTileY(maxY + 1, zoom)
    var southwest = gcj02ToWgs84(mapSouth, mapWest)
    var northeast = gcj02ToWgs84(mapNorth, mapEast)
    return {
      key: [zoom, minX, maxX, minY, maxY].join(':'),
      zoom: zoom,
      west: southwest[1],
      south: southwest[0],
      east: northeast[1],
      north: northeast[0],
    }
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
    var centerX = (minX + maxX) / 2
    var centerY = (minY + maxY) / 2
    return tiles.sort(function (a, b) {
      return Math.hypot(a.x - centerX, a.y - centerY) - Math.hypot(b.x - centerX, b.y - centerY)
    }).slice(0, MAX_VISIBLE_TILES)
  },

  _tileKey(tile) {
    return [
      heatmapTileCache.viewerScope(),
      heatmapTileCache.userScope(this._userId),
      heatmapTileCache.audienceScope(this._userId),
      this._heatmapCacheVersion || ('g' + (this._heatmapGeneration || 0)),
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
      }, GROUND_OVERLAY_ACK_TIMEOUT_MS)
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
    return heatmapTileCache.load(key, () => (
      api.downloadTemporaryFile(this._tileEndpoint(tile.zoom, tile.x, tile.y))
    ))
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
      // addGroundOverlay/removeGroundOverlay 的 id 合同是 Number；String 会直接 parameter error。
      var id = idSeed
      downloads.push(
        this._loadTileFile(tile, key)
          .then((filePath) => this._addGroundOverlay(tile, filePath, id))
          .then(() => ({ key: key, id: id }))
          .catch((error) => {
            console.warn('heatmap tile overlay failed:', error && error.errMsg ? error.errMsg : error)
            heatmapTileCache.remove(key)
            return null
          })
      )
    })
    this.setData({ updating: downloads.length > 0 && Object.keys(active).length === 0 })
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
      this._preferVectorLayer = false
      this.setData({ updating: false, polylines: [] })
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
