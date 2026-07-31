/**
 * 个人页骑行热图卡片：首屏只取范围元数据，轨迹按当前视野加载透明瓦片。
 * 原生地图只承载底图和手势，不再接收数千个 polyline 点。
 */

const api = require('../../utils/api')
const heatmapMap = require('../../utils/heatmap-map')
const heatmapProtocol = require('../../utils/heatmap-protocol')
const heatmapTileCache = require('../../utils/heatmap-tile-cache')
const { gcj02ToWgs84 } = require('../../utils/coords')

const MIN_TILE_ZOOM = 3
const MAX_TILE_ZOOM = 18
const MAX_VISIBLE_TILES = 12
const HEATMAP_LINE_WIDTH = 3
const HEATMAP_LINE_OPACITY = 'C8'
const LEGACY_CARD_MAX_POINTS = 4000
const GROUND_OVERLAY_ACK_TIMEOUT_MS = 4000
const VECTOR_LOD_AHEAD = 2
const MAX_VECTOR_DISPLAY_BLOCKS = 8
const MAX_VECTOR_DISPLAY_POINTS = 20000
const MAX_VECTOR_DISPLAY_LINES = 1000

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
  return Math.floor((longitude + 180) / 360 * Math.pow(2, zoom))
}

function tileYForLatitude(latitude, zoom) {
  var limited = Math.max(-85.05112878, Math.min(85.05112878, latitude))
  var radians = limited * Math.PI / 180
  return Math.floor((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2 * Math.pow(2, zoom))
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
  if (zoom <= 11) return { width: 2, opacity: HEATMAP_LINE_OPACITY }
  return { width: HEATMAP_LINE_WIDTH, opacity: HEATMAP_LINE_OPACITY }
}

function vectorLodZoom(scale) {
  var numericScale = Number(scale)
  if (!Number.isFinite(numericScale)) numericScale = 10
  return Math.max(3, Math.min(20, Math.floor(numericScale + 0.001) + VECTOR_LOD_AHEAD))
}

Component({
  properties: {
    userId: {
      type: Number,
      value: 0,
      observer: '_onPropsChange',
    },
  },

  data: {
    loading: true,
    updating: false,
    error: false,
    tileError: false,
    isEmpty: false,
    center: { latitude: 39.9042, longitude: 116.4074 },
    includePoints: [],
    polylines: [],
    activityCount: 0,
  },

  lifetimes: {
    attached() {
      this._componentAlive = true
      // 开发者工具不显示图片覆盖层；IDE 用原始点派生的密度矢量，真机用 PNG 瓦片。
      this._preferVectorLayer = isDeveloperTools()
      this._fetchHeatmap()
    },
    ready() {
      this._componentReady = true
      if (this._metadataLoaded) {
        this._ensureMapContext()
        this._scheduleViewportRefresh(180)
      }
    },
    detached() {
      this._componentAlive = false
      if (this._viewportTimer) clearTimeout(this._viewportTimer)
      this._viewportTimer = null
      this._metadataRequestSeq = (this._metadataRequestSeq || 0) + 1
      this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1
      this._vectorRequestSeq = (this._vectorRequestSeq || 0) + 1
      this._viewportReadSeq = (this._viewportReadSeq || 0) + 1
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
  },

  methods: {
    _onPropsChange() {
      if (!this._fetchedOnce) return
      this._clearTileOverlays()
      this._preferVectorLayer = isDeveloperTools()
      this._lastVectorSetKey = ''
      this._vectorPreparedTracks = []
      this._vectorBlockFrames = {}
      this._vectorDisplayKeys = []
      this._vectorDisplayFamily = ''
      this._vectorDisplayRenderKey = ''
      this._vectorFrameTouch = 0
      this.setData({ polylines: [] })
      this._fetchHeatmap()
    },

    _endpoint() {
      return this.data.userId === 0
        ? '/api/user/me/heatmap'
        : '/api/user/' + this.data.userId + '/heatmap'
    },

    _tileEndpoint(zoom, x, y) {
      var base = this.data.userId === 0
        ? '/api/user/me/heatmap/tiles/'
        : '/api/user/' + this.data.userId + '/heatmap/tiles/'
      var cacheVersion = this._heatmapCacheVersion || ('g' + (this._heatmapGeneration || 0))
      return base + zoom + '/' + x + '/' + y + '.png?color=orange&v=' + encodeURIComponent(cacheVersion)
    },

    _fetchHeatmap() {
      this._fetchedOnce = true
      var requestSeq = (this._metadataRequestSeq || 0) + 1
      this._metadataRequestSeq = requestSeq
      this._lastVectorSetKey = ''
      this._vectorBlockFrames = {}
      this._vectorDisplayKeys = []
      this._vectorDisplayFamily = ''
      this._vectorDisplayRenderKey = ''
      this._vectorPreparedTracks = []
      this._vectorFrameTouch = 0
      this.setData({ loading: true, error: false, tileError: false, isEmpty: false })

      var initialRequest = heatmapProtocol.shouldTryMeta()
        ? api.get(this._endpoint(), { detail: 'meta' })
          .then(function (data) { return { data: data, legacyProtocol: false } })
        : api.get(this._endpoint(), { detail: 'card' })
          .then(function (data) { return { data: data, legacyProtocol: true } })

      initialRequest
        .catch((error) => {
          if (
            this._componentAlive === false
            || requestSeq !== this._metadataRequestSeq
            || Number(error && error.code) !== 422
          ) {
            throw error
          }
          // 小程序前端可能先于热图瓦片后端进入体验版。旧后端不认识 detail=meta，
          // 但仍支持 card/full/viewport；协议协商失败时直接退回既有矢量链路，
          // 不能让个人页因为分步发布而整卡打不开。
          heatmapProtocol.markMetaUnsupported()
          return api.get(this._endpoint(), { detail: 'card' })
            .then(function (data) { return { data: data, legacyProtocol: true } })
        })
        .then((result) => {
          if (this._componentAlive === false || requestSeq !== this._metadataRequestSeq) return
          var data = result && result.data
          var legacyProtocol = Boolean(result && result.legacyProtocol)
          this._heatmapGeneration = Math.max(0, Number(data && data.generation) || 0)
          this._heatmapCacheVersion = String(
            data && data.cache_version || ('g' + this._heatmapGeneration)
          )
          var activityCount = Number(data && data.activity_count) || 0
          var model = legacyProtocol
            ? heatmapMap.buildHeatmapMapModel(
              data && data.tracks,
              'orange',
              HEATMAP_LINE_WIDTH,
              LEGACY_CARD_MAX_POINTS,
              HEATMAP_LINE_OPACITY
            )
            : heatmapMap.buildHeatmapMetaModel(
              data && data.focus_points,
              data && data.all_points
            )
          if (!model || activityCount === 0) {
            this._metadataLoaded = false
            this._clearTileOverlays()
            this.setData({
              loading: false,
              error: false,
              isEmpty: true,
              polylines: [],
              activityCount: 0,
            })
            return
          }

          this._metadataLoaded = true
          if (legacyProtocol) {
            this._preferVectorLayer = true
            this._vectorPreparedTracks = model.preparedTracks
          }
          this.setData({
            loading: false,
            error: false,
            tileError: false,
            isEmpty: false,
            center: model.center,
            includePoints: model.focusPoints,
            polylines: legacyProtocol ? model.polylines : [],
            activityCount: activityCount,
          }, () => {
            if (!this._componentReady) return
            this._ensureMapContext()
            this._scheduleViewportRefresh(180)
          })
        })
        .catch(() => {
          if (this._componentAlive === false || requestSeq !== this._metadataRequestSeq) return
          this.setData({ loading: false, error: true, isEmpty: false })
        })
    },

    _ensureMapContext() {
      if (!this._componentReady || this._mapContext || typeof wx.createMapContext !== 'function') {
        return this._mapContext || null
      }
      this._mapContext = wx.createMapContext('heatmap-card-map', this)
      return this._mapContext
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
      if (this._componentAlive === false || !this._metadataLoaded || !this._ensureMapContext()) return
      if (this._viewportTimer) clearTimeout(this._viewportTimer)
      var readSeq = (this._viewportReadSeq || 0) + 1
      this._viewportReadSeq = readSeq
      this._viewportTimer = setTimeout(() => {
        this._viewportTimer = null
        this._readViewport().then((viewport) => {
          if (this._componentAlive === false || readSeq !== this._viewportReadSeq || !viewport) return
          this._fetchViewport(viewport)
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
                scale: Number(scale) || fallbackScale,
                zoom: Math.max(MIN_TILE_ZOOM, Math.min(MAX_TILE_ZOOM, Math.round(Number(scale) || fallbackScale))),
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
      if (this._componentAlive === false) return
      if (this._preferVectorLayer) {
        this._refreshVectorLayer(viewport)
        return
      }
      this._refreshTileLayer(viewport)
    },

    _refreshVectorLayer(viewport) {
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
      this._lastVectorSetKey = requestKey
      this._lastVectorZoom = requestViewports[0].zoom
      this._lastVectorScale = Number(viewport.scale || viewport.zoom)
      var requestSeq = (this._vectorRequestSeq || 0) + 1
      this._vectorRequestSeq = requestSeq
      this.setData({
        updating: !Array.isArray(this.data.polylines) || this.data.polylines.length === 0,
        tileError: false,
      })
      Promise.all(requestViewports.map((requestViewport) => this._loadVectorData(requestViewport)))
        .then((responses) => {
          if (this._componentAlive === false || requestSeq !== this._vectorRequestSeq) return
          this._storeVectorFrames(requestViewports, responses)
          this._renderVectorFrames(requestViewports, viewport)
        })
        .catch(() => {
          if (this._componentAlive === false || requestSeq !== this._vectorRequestSeq) return
          this._lastVectorSetKey = ''
          this.setData({ updating: false, tileError: true })
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

    _renderVectorFrames(requestViewports, viewport) {
      var frames = this._vectorBlockFrames || {}
      var visibleKeys = requestViewports.map(function (item) { return item.key })
      var visible = {}
      visibleKeys.forEach(function (key) { visible[key] = true })
      var family = requestViewports[0].gridZoom + ':' + requestViewports[0].zoom
      var sameFamily = family === this._vectorDisplayFamily
      var previousKeys = sameFamily && Array.isArray(this._vectorDisplayKeys)
        ? this._vectorDisplayKeys.filter(function (key) { return Boolean(frames[key]) })
        : []
      var candidateKeys = previousKeys.slice()
      visibleKeys.forEach(function (key) {
        if (candidateKeys.indexOf(key) < 0) candidateKeys.push(key)
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
      var renderKey = ['orange', style.width, style.opacity].join(':')
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
      var prepared = []
      var polylines = []
      candidateKeys.forEach(function (key) {
        var frame = frames[key]
        if (!frame) return
        prepared.push.apply(prepared, frame.preparedTracks)
        if (frame.renderKey !== renderKey) {
          frame.renderKey = renderKey
          frame.polylines = heatmapMap.buildPolylines(
            frame.preparedTracks,
            'orange',
            style.width,
            style.opacity
          )
        }
        polylines.push.apply(polylines, frame.polylines)
      })
      this._vectorDisplayKeys = candidateKeys
      this._vectorDisplayFamily = family
      this._vectorDisplayRenderKey = renderKey
      this._vectorPreparedTracks = prepared
      this.setData({
        updating: false,
        tileError: false,
        polylines: polylines,
      })
      return true
    },

    _vectorDataKey(requestViewport) {
      return [
        'vector',
        heatmapTileCache.viewerScope(),
        heatmapTileCache.userScope(this.data.userId),
        heatmapTileCache.audienceScope(this.data.userId),
        this._heatmapCacheVersion || ('g' + (this._heatmapGeneration || 0)),
        'all',
        requestViewport.key,
      ].join(':')
    },

    _loadVectorData(requestViewport) {
      return heatmapTileCache.loadData(this._vectorDataKey(requestViewport), () => api.get(
        this._endpoint(), {
          detail: 'viewport',
          west: requestViewport.west,
          south: requestViewport.south,
          east: requestViewport.east,
          north: requestViewport.north,
          zoom: requestViewport.zoom,
        }
      ))
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
      var visualScale = Number(viewport.scale || viewport.zoom)
      var gridZoom = Math.max(MIN_TILE_ZOOM, Math.min(20, Math.round(visualScale)))
      var lodZoom = vectorLodZoom(visualScale)
      var count = Math.pow(2, gridZoom)
      var minX = Math.max(0, tileXForLongitude(viewport.mapWest, gridZoom))
      var maxX = Math.min(count - 1, tileXForLongitude(viewport.mapEast, gridZoom))
      var minY = Math.max(0, tileYForLatitude(viewport.mapNorth, gridZoom))
      var maxY = Math.min(count - 1, tileYForLatitude(viewport.mapSouth, gridZoom))
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
      var zoom = viewport.zoom
      var count = Math.pow(2, zoom)
      var minX = Math.max(0, tileXForLongitude(viewport.mapWest, zoom))
      var maxX = Math.min(count - 1, tileXForLongitude(viewport.mapEast, zoom))
      var minY = Math.max(0, tileYForLatitude(viewport.mapNorth, zoom))
      var maxY = Math.min(count - 1, tileYForLatitude(viewport.mapSouth, zoom))
      var tiles = []
      for (var y = minY; y <= maxY; y++) {
        for (var x = minX; x <= maxX; x++) tiles.push({ zoom: zoom, x: x, y: y })
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
        heatmapTileCache.userScope(this.data.userId),
        heatmapTileCache.audienceScope(this.data.userId),
        this._heatmapCacheVersion || ('g' + (this._heatmapGeneration || 0)),
        tile.zoom,
        tile.x,
        tile.y,
        'all',
        'orange',
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
      if (!this._mapContext || typeof this._mapContext.removeGroundOverlay !== 'function') return
      this._mapContext.removeGroundOverlay({ id: id })
    },

    _loadTileFile(tile, key) {
      return heatmapTileCache.load(key, () => (
        api.downloadTemporaryFile(this._tileEndpoint(tile.zoom, tile.x, tile.y))
      ))
    },

    _refreshTileLayer(viewport) {
      var tiles = this._visibleTiles(viewport)
      var setKey = tiles.map((tile) => this._tileKey(tile)).join('|')
      if (setKey && setKey === this._lastTileSetKey) return
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
        var idSeed = (this._tileIdSeed || 20000) + 1
        this._tileIdSeed = idSeed
        var id = idSeed
        downloads.push(
          this._loadTileFile(tile, key)
            .then((filePath) => this._addGroundOverlay(tile, filePath, id))
            .then(() => ({ key: key, id: id }))
            .catch((error) => {
              console.warn('heatmap card tile overlay failed:', error && error.errMsg ? error.errMsg : error)
              heatmapTileCache.remove(key)
              return null
            })
        )
      })
      this.setData({
        updating: downloads.length > 0 && Object.keys(active).length === 0,
        tileError: false,
      })
      Promise.all(downloads).then((added) => {
        if (this._componentAlive === false || requestSeq !== this._viewportRequestSeq) {
          added.forEach((item) => { if (item) this._removeGroundOverlay(item.id) })
          return
        }
        added.forEach(function (item) { if (item) active[item.key] = item })
        var complete = Object.keys(desired).every(function (key) { return Boolean(active[key]) })
        if (!complete) {
          added.forEach((item) => {
            if (!item) return
            this._removeGroundOverlay(item.id)
            delete active[item.key]
          })
          this._lastTileSetKey = ''
          this._activeTileOverlays = active
          if (Object.keys(active).length === 0) {
            this._preferVectorLayer = true
            this._refreshVectorLayer(viewport)
            return
          }
          this.setData({ updating: false, tileError: false })
          return
        }
        Object.keys(active).forEach((key) => {
          if (desired[key]) return
          this._removeGroundOverlay(active[key].id)
          delete active[key]
        })
        this._activeTileOverlays = active
        this._preferVectorLayer = false
        this.setData({ updating: false, tileError: false, polylines: [] })
      })
    },

    _clearTileOverlays() {
      var active = this._activeTileOverlays || {}
      Object.keys(active).forEach((key) => this._removeGroundOverlay(active[key].id))
      this._activeTileOverlays = {}
      this._lastTileSetKey = ''
    },

    _retryFetch() {
      this._fetchHeatmap()
    },

    _retryTiles() {
      this._preferVectorLayer = false
      this._lastTileSetKey = ''
      this._scheduleViewportRefresh(0)
    },

    _openFullScreen() {
      var userQuery = this.data.userId > 0 ? '?userId=' + this.data.userId : ''
      wx.navigateTo({ url: '/pages/heatmap/heatmap' + userQuery })
    },
  },
})
