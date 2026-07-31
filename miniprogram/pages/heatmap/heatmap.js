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
const VECTOR_PREFETCH_CONCURRENCY = 2
const VECTOR_PREFETCH_LIMIT = 8
const VECTOR_LOD_AHEAD = 2
const MAX_VECTOR_DISPLAY_BLOCKS = 16
const MAX_VECTOR_DISPLAY_POINTS = 30000
const MAX_VECTOR_DISPLAY_LINES = 1600
const DENSE_VECTOR_POINT_THRESHOLD = 18000
const DENSE_VECTOR_LINE_THRESHOLD = 1000
const DENSE_VECTOR_PREFETCH_LIMIT = 2

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
  // 只随缩放调整线宽，不再降低透明度；否则同一条红线缩小时会褪成浅粉色。
  if (zoom <= 11) return { width: 2, opacity: HEATMAP_LINE_OPACITY }
  return { width: HEATMAP_LINE_WIDTH, opacity: HEATMAP_LINE_OPACITY }
}

function vectorLodZoom(scale) {
  var numericScale = Number(scale)
  if (!Number.isFinite(numericScale)) numericScale = 10
  // 矢量折线没有栅格瓦片的跨级缩放抗性，显示层始终提前两级取几何。
  // 例如地图 scale=12.x 时直接用 z14 曲率，避免放大旧 z12 折线时弯道变长直线。
  return Math.max(3, Math.min(20, Math.floor(numericScale + 0.001) + VECTOR_LOD_AHEAD))
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
    if (this._vectorPrefetchTimer) clearTimeout(this._vectorPrefetchTimer)
    this._viewportTimer = null
    this._vectorPrefetchTimer = null
    this._metadataRequestSeq = (this._metadataRequestSeq || 0) + 1
    this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
    this._vectorRequestSeq = (this._vectorRequestSeq || 0) + 1
    this._vectorPrefetchSeq = (this._vectorPrefetchSeq || 0) + 1
    this._viewportReadSeq = (this._viewportReadSeq || 0) + 1
    this._viewportReadRetries = 0
    this._clearTileOverlays()
    this._lastVectorSetKey = ''
    this._lastVectorScale = NaN
    this._vectorPreparedTracks = []
    this._vectorBlockFrames = {}
    this._vectorDisplayKeys = []
    this._vectorDisplayFamily = ''
    this._vectorDisplayRenderKey = ''
    this._vectorFrameTouch = 0
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
    this._vectorBlockFrames = {}
    this._vectorDisplayKeys = []
    this._vectorDisplayFamily = ''
    this._vectorDisplayRenderKey = ''
    this._vectorPreparedTracks = []
    this._vectorFrameTouch = 0
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
    if (event.type === 'end') {
      var causedBy = String(event.causedBy || (event.detail && event.detail.causedBy) || '')
      this._clearStaleVectorFrameForZoom(eventScale, causedBy === 'scale')
      this._scheduleViewportRefresh(0)
    }
  },

  _clearStaleVectorFrameForZoom(zoom, forceScaleChange) {
    if (!this._preferVectorLayer || !Number.isFinite(Number(zoom))) return false
    var numericScale = Number(zoom)
    var nextZoom = vectorLodZoom(numericScale)
    var previousZoom = Number(this._lastVectorZoom)
    if (!Number.isFinite(previousZoom) || previousZoom === nextZoom) return false
    // 旧实现会在这里先清空 polylines，随后等待接口返回再整屏重画，视觉上就是
    // “一动就闪一下”。现在保留旧帧作为前台缓冲，只取消过时请求；新 LOD 的
    // 所有可见固定块就绪后，再由 _renderVectorFrames 一次切换。
    this._lastVectorZoom = nextZoom
    this._lastVectorScale = numericScale
    this._lastVectorSetKey = ''
    this._vectorRequestSeq = (this._vectorRequestSeq || 0) + 1
    if (!Array.isArray(this.data.polylines) || this.data.polylines.length === 0) {
      this.setData({ updating: true })
    }
    return true
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
              scale: Number(scale) || fallbackScale,
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
    var requestViewports = this._vectorRequestViewports(viewport)
    if (!requestViewports.length) return
    var requestKey = requestViewports.map(function (item) { return item.key }).join('|')
    this._clearStaleVectorFrameForZoom(viewport.scale || viewport.zoom)
    if (requestKey === this._lastVectorSetKey) {
      if (this.data.updating) this.setData({ updating: false })
      return
    }
    this._vectorPrefetchSeq = (this._vectorPrefetchSeq || 0) + 1
    if (this._vectorPrefetchTimer) clearTimeout(this._vectorPrefetchTimer)
    this._vectorPrefetchTimer = null
    this._lastVectorSetKey = requestKey
    this._lastVectorZoom = requestViewports[0].zoom
    this._lastVectorScale = Number(viewport.scale || viewport.zoom)
    var requestSeq = (this._vectorRequestSeq || 0) + 1
    this._vectorRequestSeq = requestSeq
    this.setData({ updating: !Array.isArray(this.data.polylines) || this.data.polylines.length === 0 })
    Promise.all(requestViewports.map((item) => this._loadVectorData(item)))
      .then((responses) => {
        if (this._pageAlive === false || requestSeq !== this._vectorRequestSeq) return
        this._storeVectorFrames(requestViewports, responses)
        this._renderVectorFrames(requestViewports, viewport)
        this._prefetchVectorNeighbors(requestViewports, viewport)
      })
      .catch(() => {
        if (this._pageAlive === false || requestSeq !== this._vectorRequestSeq) return
        this._lastVectorSetKey = ''
        this.setData({ updating: false })
      })
  },

  _storeVectorFrames(requestViewports, responses) {
    var frames = this._vectorBlockFrames || {}
    var touch = Number(this._vectorFrameTouch) || 0
    requestViewports.forEach(function (requestViewport, index) {
      var data = responses[index]
      var tracks = data && Array.isArray(data.tracks) ? data.tracks : []
      touch += 1
      if (frames[requestViewport.key]) {
        frames[requestViewport.key].touched = touch
        return
      }
      frames[requestViewport.key] = {
        family: requestViewport.gridZoom + ':' + requestViewport.zoom,
        preparedTracks: heatmapMap.prepareTracks(tracks),
        touched: touch,
      }
      frames[requestViewport.key].pointCount = frames[requestViewport.key].preparedTracks
        .reduce(function (sum, track) { return sum + track.length }, 0)
      frames[requestViewport.key].lineCount = frames[requestViewport.key].preparedTracks.length
    })
    this._vectorBlockFrames = frames
    this._vectorFrameTouch = touch
  },

  _renderVectorFrames(requestViewports, viewport, prefetchedViewports) {
    var frames = this._vectorBlockFrames || {}
    var visibleKeys = requestViewports.map(function (item) { return item.key })
    var visible = {}
    visibleKeys.forEach(function (key) { visible[key] = true })
    var family = requestViewports[0].gridZoom + ':' + requestViewports[0].zoom
    var sameFamily = family === this._vectorDisplayFamily
    var previousKeys = sameFamily && Array.isArray(this._vectorDisplayKeys)
      ? this._vectorDisplayKeys.filter(function (key) { return Boolean(frames[key]) })
      : []

    // 同倍率平移只追加新固定块。达到上限时先保留当前屏幕，再保留最近访问的
    // 旧块；这样连续拖动不会反复销毁并重建仍在附近的折线。
    var candidateKeys = previousKeys.slice()
    visibleKeys.forEach(function (key) {
      if (candidateKeys.indexOf(key) < 0) candidateKeys.push(key)
    })
    ;(Array.isArray(prefetchedViewports) ? prefetchedViewports : []).forEach(function (item) {
      if (item && candidateKeys.indexOf(item.key) < 0) candidateKeys.push(item.key)
    })

    var keep = visibleKeys.filter(function (key, index) {
      return Boolean(frames[key]) && visibleKeys.indexOf(key) === index
    })
    var usedPoints = keep.reduce(function (sum, key) {
      return sum + (frames[key].pointCount || 0)
    }, 0)
    var usedLines = keep.reduce(function (sum, key) {
      return sum + (frames[key].lineCount || 0)
    }, 0)
    candidateKeys.filter(function (key) { return !visible[key] && frames[key] })
      .sort(function (left, right) { return frames[right].touched - frames[left].touched })
      .forEach(function (key) {
        var nextPoints = usedPoints + (frames[key].pointCount || 0)
        var nextLines = usedLines + (frames[key].lineCount || 0)
        if (
          keep.length >= MAX_VECTOR_DISPLAY_BLOCKS
          || nextPoints > MAX_VECTOR_DISPLAY_POINTS
          || nextLines > MAX_VECTOR_DISPLAY_LINES
        ) return
        keep.push(key)
        usedPoints = nextPoints
        usedLines = nextLines
      })
    if (candidateKeys.length !== keep.length) {
      var allowed = {}
      keep.forEach(function (key) { allowed[key] = true })
      candidateKeys = candidateKeys.filter(function (key) { return allowed[key] })
    }

    var style = vectorLineStyle(Number(viewport.scale || viewport.zoom))
    var prepared = []
    var polylines = []
    var renderKey = [
      this.data.selectedColor,
      style.width,
      style.opacity,
    ].join(':')
    var previousDisplayKeys = Array.isArray(this._vectorDisplayKeys)
      ? this._vectorDisplayKeys
      : []
    var displayUnchanged = sameFamily
      && renderKey === this._vectorDisplayRenderKey
      && candidateKeys.length === previousDisplayKeys.length
      && candidateKeys.every(function (key, index) { return key === previousDisplayKeys[index] })
    if (displayUnchanged) {
      if (this.data.updating) this.setData({ updating: false })
      return false
    }
    candidateKeys.forEach(function (key) {
      var frame = frames[key]
      if (!frame) return
      prepared.push.apply(prepared, frame.preparedTracks)
      if (frame.renderKey !== renderKey) {
        frame.renderKey = renderKey
        frame.polylines = heatmapMap.buildPolylines(
          frame.preparedTracks,
          this.data.selectedColor,
          style.width,
          style.opacity
        )
      }
      polylines.push.apply(polylines, frame.polylines)
    }, this)
    this._vectorDisplayKeys = candidateKeys
    this._vectorDisplayFamily = family
    this._vectorDisplayRenderKey = renderKey
    this._vectorPreparedTracks = prepared
    this.setData({
      updating: false,
      polylines: polylines,
    })
    return true
  },

  _vectorDataKey(requestViewport) {
    return [
      'vector',
      heatmapTileCache.viewerScope(),
      heatmapTileCache.userScope(this._userId),
      heatmapTileCache.audienceScope(this._userId),
      this._heatmapCacheVersion || ('g' + (this._heatmapGeneration || 0)),
      this.data.selectedYear === null ? 'all' : this.data.selectedYear,
      requestViewport.key,
    ].join(':')
  },

  _loadVectorData(requestViewport) {
    var params = {
      detail: 'viewport',
      west: requestViewport.west,
      south: requestViewport.south,
      east: requestViewport.east,
      north: requestViewport.north,
      zoom: requestViewport.zoom,
    }
    if (this.data.selectedYear !== null) params.year = this.data.selectedYear
    return heatmapTileCache.loadData(this._vectorDataKey(requestViewport), () => (
      api.get(this._endpoint(), params)
    ))
  },

  _prefetchVectorNeighbors(requestViewports, viewport) {
    if (
      !Array.isArray(requestViewports) || !requestViewports.length
      || requestViewports[0].gridZoom < 10 || this._pageAlive === false
    ) return
    if (this._vectorPrefetchTimer) clearTimeout(this._vectorPrefetchTimer)
    var prefetchSeq = (this._vectorPrefetchSeq || 0) + 1
    this._vectorPrefetchSeq = prefetchSeq
    this._vectorPrefetchTimer = setTimeout(() => {
      this._vectorPrefetchTimer = null
      if (this._pageAlive === false || prefetchSeq !== this._vectorPrefetchSeq) return
      var visible = {}
      requestViewports.forEach(function (item) { visible[item.key] = true })
      var candidates = {}
      requestViewports.forEach((item) => {
        var width = item.maxX - item.minX + 1
        var height = item.maxY - item.minY + 1
        ;[
          [-1, 0], [1, 0], [0, -1], [0, 1],
          [-1, -1], [1, -1], [-1, 1], [1, 1],
        ].forEach((offset) => {
          var minX = item.minX + offset[0] * width
          var minY = item.minY + offset[1] * height
          var maxX = minX + width - 1
          var maxY = minY + height - 1
          if (
            minX < 0 || minY < 0
            || maxX >= item.count || maxY >= item.count
          ) return
          var neighbor = this._vectorViewportForTileRange(
            item.gridZoom, minX, maxX, minY, maxY, item.zoom
          )
          if (!visible[neighbor.key]) candidates[neighbor.key] = neighbor
        })
      })
      var centerX = requestViewports.reduce(function (sum, item) {
        return sum + (item.minX + item.maxX) / 2
      }, 0) / requestViewports.length
      var centerY = requestViewports.reduce(function (sum, item) {
        return sum + (item.minY + item.maxY) / 2
      }, 0) / requestViewports.length
      var mapCenter = {
        x: (Number(viewport.mapWest) + Number(viewport.mapEast)) / 2,
        y: (Number(viewport.mapSouth) + Number(viewport.mapNorth)) / 2,
      }
      var previousCenter = this._lastVectorViewportCenter
      var directionX = previousCenter ? mapCenter.x - previousCenter.x : 0
      var directionY = previousCenter ? mapCenter.y - previousCenter.y : 0
      this._lastVectorViewportCenter = mapCenter
      var queue = Object.keys(candidates).map(function (key) { return candidates[key] })
      queue.sort(function (left, right) {
        var leftX = (left.minX + left.maxX) / 2 - centerX
        var leftY = (left.minY + left.maxY) / 2 - centerY
        var rightX = (right.minX + right.maxX) / 2 - centerX
        var rightY = (right.minY + right.maxY) / 2 - centerY
        var leftForward = leftX * directionX - leftY * directionY
        var rightForward = rightX * directionX - rightY * directionY
        if (leftForward !== rightForward) return rightForward - leftForward
        return Math.hypot(leftX, leftY) - Math.hypot(rightX, rightY)
      })
      queue = queue.slice(0, VECTOR_PREFETCH_LIMIT)
      var visiblePoints = requestViewports.reduce((sum, item) => {
        var frame = (this._vectorBlockFrames || {})[item.key]
        return sum + (frame && frame.pointCount || 0)
      }, 0)
      var visibleLines = requestViewports.reduce((sum, item) => {
        var frame = (this._vectorBlockFrames || {})[item.key]
        return sum + (frame && frame.lineCount || 0)
      }, 0)
      if (
        visiblePoints >= DENSE_VECTOR_POINT_THRESHOLD
        || visibleLines >= DENSE_VECTOR_LINE_THRESHOLD
      ) {
        queue = queue.slice(0, DENSE_VECTOR_PREFETCH_LIMIT)
      }
      var pending = queue.length
      var prefetched = []
      var visibleRequestKey = requestViewports.map(function (item) { return item.key }).join('|')
      if (!pending) return
      var finishOne = (requestViewport, data) => {
        if (data) {
          this._storeVectorFrames([requestViewport], [data])
          prefetched.push(requestViewport)
        }
        pending -= 1
        if (
          pending === 0 && prefetched.length
          && this._pageAlive !== false
          && prefetchSeq === this._vectorPrefetchSeq
          && visibleRequestKey === this._lastVectorSetKey
        ) {
          // 邻块在用户静止时一次并入持久图层。之后在这一圈内平移，
          // requestKey 即使变化也不会再触碰 polylines，更不会切帧。
          this._renderVectorFrames(requestViewports, viewport, prefetched)
        }
      }
      var runNext = () => {
        if (
          this._pageAlive === false || prefetchSeq !== this._vectorPrefetchSeq
          || !queue.length
        ) return
        var next = queue.shift()
        this._loadVectorData(next)
          .then((data) => { finishOne(next, data) })
          .catch(() => { finishOne(next, null) })
          .then(runNext)
      }
      for (var worker = 0; worker < VECTOR_PREFETCH_CONCURRENCY; worker++) runNext()
    }, 0)
  },

  _vectorViewportForTileRange(gridZoom, minX, maxX, minY, maxY, lodZoom) {
    var renderZoom = Number.isFinite(Number(lodZoom)) ? Number(lodZoom) : gridZoom
    var count = Math.pow(2, gridZoom)
    var mapWest = minX / count * 360 - 180
    var mapEast = (maxX + 1) / count * 360 - 180
    var mapNorth = latitudeForTileY(minY, gridZoom)
    var mapSouth = latitudeForTileY(maxY + 1, gridZoom)
    var southwest = gcj02ToWgs84(mapSouth, mapWest)
    var northeast = gcj02ToWgs84(mapNorth, mapEast)
    return {
      key: [gridZoom, renderZoom, minX, maxX, minY, maxY].join(':'),
      zoom: renderZoom,
      gridZoom: gridZoom,
      count: count,
      minX: minX,
      maxX: maxX,
      minY: minY,
      maxY: maxY,
      west: southwest[1],
      south: southwest[0],
      east: northeast[1],
      north: northeast[0],
    }
  },

  _vectorRequestViewports(viewport) {
    // 固定块可以像真正的 z/x/y 瓦片一样拼装。旧实现把整个可见范围缓存成一个
    // 可变长矩形；跨边界后 4x4 会变成 8x4，刚预取的邻块完全无法复用。
    var visualScale = Number(viewport.scale || viewport.zoom)
    var gridZoom = Math.max(3, Math.min(20, Math.round(visualScale)))
    var lodZoom = vectorLodZoom(visualScale)
    var count = Math.pow(2, gridZoom)
    var minX = Math.max(0, tileXForLongitude(viewport.mapWest, gridZoom))
    var maxX = Math.min(count - 1, tileXForLongitude(viewport.mapEast, gridZoom))
    var minY = Math.max(0, tileYForLatitude(viewport.mapNorth, gridZoom))
    var maxY = Math.min(count - 1, tileYForLatitude(viewport.mapSouth, gridZoom))
    // 所有常用倍率都使用固定且互不重叠的块。原先 z<14 会把视野动态扩成
    // 2/4/6... 个瓦片宽，移动一点缓存键就变，旧块也无法与新块拼接。
    // 城市总览用 8x8 覆盖更大范围；z14-z15 用 4x4 控制密集区点数。
    var vectorBlockSize = gridZoom >= 16 || gridZoom <= 13 ? 8 : 4
    var firstX = Math.max(0, Math.floor(minX / vectorBlockSize) * vectorBlockSize)
    var lastX = Math.min(count - 1, Math.floor(maxX / vectorBlockSize) * vectorBlockSize)
    var firstY = Math.max(0, Math.floor(minY / vectorBlockSize) * vectorBlockSize)
    var lastY = Math.min(count - 1, Math.floor(maxY / vectorBlockSize) * vectorBlockSize)
    var blocks = []
    for (var blockY = firstY; blockY <= lastY; blockY += vectorBlockSize) {
      for (var blockX = firstX; blockX <= lastX; blockX += vectorBlockSize) {
        blocks.push(this._vectorViewportForTileRange(
          gridZoom,
          blockX,
          Math.min(count - 1, blockX + vectorBlockSize - 1),
          blockY,
          Math.min(count - 1, blockY + vectorBlockSize - 1),
          lodZoom
        ))
      }
    }
    return blocks
  },

  _vectorRequestViewport(viewport) {
    return this._vectorRequestViewports(viewport)[0]
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
