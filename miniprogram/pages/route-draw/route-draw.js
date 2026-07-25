const api = require('../../utils/api')

const DEFAULT_CENTER = { latitude: 37.8706, longitude: 112.5489 }
const MAX_SNAP_POINTS = 120
const MAX_SAVE_POINTS = 500
const TOUCH_SAMPLE_INTERVAL_MS = 45
const TOUCH_SAMPLE_DISTANCE_PX = 7
const SKETCH_AUTO_FINISH_MS = 900
const SKETCH_LOCATION_TIMEOUT_MS = 500
const SNAP_COLOR = '#FF9500'
const RAW_COLOR = '#8E8E93'
const PREVIEW_COLOR = '#30B0C7'
const PENDING_SAVE_STORAGE_PREFIX = 'route_draw_pending_save_v1:'
const MAX_PENDING_SAVE_BYTES = 64 * 1024

var memoryPendingSave = null

function finiteNumber(value, fallback) {
  var n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function normalizeLonLatPoint(point) {
  if (Array.isArray(point)) {
    var lon = Number(point[0])
    var lat = Number(point[1])
    if (Number.isFinite(lon) && Number.isFinite(lat)) return [lon, lat]
    return null
  }
  if (point && typeof point === 'object') {
    var objLon = Number(point.longitude !== undefined ? point.longitude : point.lon)
    var objLat = Number(point.latitude !== undefined ? point.latitude : point.lat)
    if (Number.isFinite(objLon) && Number.isFinite(objLat)) return [objLon, objLat]
  }
  return null
}

function normalizeLonLatPoints(points) {
  if (!Array.isArray(points)) return []
  var result = []
  points.forEach(function (point) {
    var normalized = normalizeLonLatPoint(point)
    if (normalized) result.push(normalized)
  })
  return result
}

function cloneLonLatPoints(points) {
  return normalizeLonLatPoints(points).map(function (point) {
    return [point[0], point[1]]
  })
}

function samePoint(a, b) {
  if (!a || !b) return false
  return Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9
}

function lonLatToMapPoint(point) {
  return { longitude: point[0], latitude: point[1] }
}

function mapPointsFromLonLat(points) {
  return normalizeLonLatPoints(points).map(lonLatToMapPoint)
}

function buildDrawPolylines(confirmedPoints, currentRawPoints, previewPoints) {
  var polylines = []
  var confirmed = mapPointsFromLonLat(confirmedPoints)
  var raw = mapPointsFromLonLat(currentRawPoints)
  var preview = mapPointsFromLonLat(previewPoints)

  if (confirmed.length >= 2) {
    polylines.push({
      role: 'confirmedPolyline',
      points: confirmed,
      color: SNAP_COLOR,
      width: 8,
      borderColor: '#FFFFFF',
      borderWidth: 3,
      arrowLine: false,
      level: 'abovelabels',
    })
  }
  if (raw.length >= 2) {
    polylines.push({
      role: 'rawPolyline',
      points: raw,
      color: RAW_COLOR,
      width: 4,
      dottedLine: true,
      arrowLine: false,
      level: 'abovelabels',
    })
  }
  if (preview.length >= 2) {
    polylines.push({
      role: 'previewPolyline',
      points: preview,
      color: PREVIEW_COLOR,
      width: 7,
      borderColor: '#FFFFFF',
      borderWidth: 2,
      arrowLine: false,
      level: 'abovelabels',
    })
  }
  return polylines
}

function toRadians(deg) {
  return deg * Math.PI / 180
}

function distanceBetween(a, b) {
  var lat1 = toRadians(a[1])
  var lat2 = toRadians(b[1])
  var dLat = toRadians(b[1] - a[1])
  var dLon = toRadians(b[0] - a[0])
  var sinLat = Math.sin(dLat / 2)
  var sinLon = Math.sin(dLon / 2)
  var h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon
  return 6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h))
}

function distanceOf(points) {
  var normalized = normalizeLonLatPoints(points)
  var total = 0
  for (var i = 1; i < normalized.length; i += 1) {
    total += distanceBetween(normalized[i - 1], normalized[i])
  }
  return total
}

function buildRouteStats(points) {
  var normalized = normalizeLonLatPoints(points)
  var distanceM = distanceOf(normalized)
  var km = distanceM / 1000
  var estimatedMinutes = distanceM > 0 ? Math.max(1, Math.round(distanceM / 1000 / 20 * 60)) : 0
  return {
    distanceM: distanceM,
    distanceText: distanceM > 0 ? (km >= 10 ? km.toFixed(1) : km.toFixed(2)) + ' km' : '0 km',
    pointCount: normalized.length,
    climbText: '保存后生成',
    etaText: estimatedMinutes > 0 ? estimatedMinutes + ' 分钟' : '0 分钟',
  }
}

function pointDistanceToLine(point, start, end) {
  var originLon = start[0]
  var originLat = start[1]
  var latScale = 111320
  var lonScale = 111320 * Math.cos(toRadians(originLat))
  var px = (point[0] - originLon) * lonScale
  var py = (point[1] - originLat) * latScale
  var ex = (end[0] - originLon) * lonScale
  var ey = (end[1] - originLat) * latScale
  var length2 = ex * ex + ey * ey
  if (length2 === 0) return Math.sqrt(px * px + py * py)
  var t = (px * ex + py * ey) / length2
  t = Math.max(0, Math.min(1, t))
  var nx = t * ex
  var ny = t * ey
  var dx = px - nx
  var dy = py - ny
  return Math.sqrt(dx * dx + dy * dy)
}

function rdpIndices(points, start, end, toleranceM) {
  var maxDistance = -1
  var maxIndex = start
  for (var i = start + 1; i < end; i += 1) {
    var distance = pointDistanceToLine(points[i], points[start], points[end])
    if (distance > maxDistance) {
      maxDistance = distance
      maxIndex = i
    }
  }
  if (maxDistance > toleranceM) {
    var left = rdpIndices(points, start, maxIndex, toleranceM)
    var right = rdpIndices(points, maxIndex, end, toleranceM)
    return left.slice(0, -1).concat(right)
  }
  return [start, end]
}

function rdpSimplify(points, toleranceM) {
  var normalized = normalizeLonLatPoints(points)
  if (normalized.length <= 2) return normalized
  var indices = rdpIndices(normalized, 0, normalized.length - 1, toleranceM)
  return indices.map(function (index) { return normalized[index] })
}

function simplifyForSnap(points) {
  var normalized = normalizeLonLatPoints(points)
  if (normalized.length <= MAX_SNAP_POINTS) return normalized
  var tolerances = [3, 6, 12, 24, 48]
  for (var i = 0; i < tolerances.length; i += 1) {
    var simplified = rdpSimplify(normalized, tolerances[i])
    if (simplified.length <= MAX_SNAP_POINTS) return simplified
  }
  var sampled = [normalized[0]]
  var step = (normalized.length - 1) / (MAX_SNAP_POINTS - 1)
  for (var j = 1; j < MAX_SNAP_POINTS - 1; j += 1) {
    sampled.push(normalized[Math.round(j * step)])
  }
  sampled.push(normalized[normalized.length - 1])
  return sampled
}

function simplifyForSave(points) {
  var normalized = normalizeLonLatPoints(points)
  if (normalized.length <= MAX_SAVE_POINTS) return normalized
  var tolerances = [5, 10, 20, 40, 80]
  for (var i = 0; i < tolerances.length; i += 1) {
    var simplified = rdpSimplify(normalized, tolerances[i])
    if (simplified.length <= MAX_SAVE_POINTS) return simplified
  }
  return normalized
}

function mergeSegments(segments) {
  var merged = []
  ;(segments || []).forEach(function (segment) {
    var points = normalizeLonLatPoints(segment)
    points.forEach(function (point, index) {
      if (index === 0 && merged.length && samePoint(merged[merged.length - 1], point)) return
      merged.push(point)
    })
  })
  return merged
}

function normalizeRouteParts(parts) {
  if (!Array.isArray(parts) || !parts.length || parts.length > 500) return null
  var normalized = []
  for (var i = 0; i < parts.length; i += 1) {
    var part = parts[i]
    if (!part || typeof part !== 'object') return null
    if (part.mode === 'snap') {
      var receipt = String(part.routing_receipt || '')
      if (!receipt || receipt.length > 512) return null
      var rawPoints = part.raw_points === undefined
        ? []
        : normalizeLonLatPoints(part.raw_points)
      if (part.raw_points !== undefined && (rawPoints.length < 2 || rawPoints.length > MAX_SNAP_POINTS)) return null
      normalized.push({ mode: 'snap', routing_receipt: receipt, points: [], raw_points: rawPoints })
      continue
    }
    if (part.mode !== 'freehand') return null
    var points = normalizeLonLatPoints(part.points)
    if (points.length < 2 || points.length > 120) return null
    normalized.push({ mode: 'freehand', points: points })
  }
  return normalized
}

function buildRouteParts(actions) {
  var parts = []
  var invalid = false
  cloneActions(actions).forEach(function (action) {
    if (action.kind !== 'segment') return
    if (action.mode === 'snap') {
      if (!action.routingReceipt) {
        invalid = true
        return
      }
      parts.push({
        mode: 'snap',
        routing_receipt: action.routingReceipt,
        points: [],
        raw_points: simplifyForSnap(action.rawPoints),
      })
      return
    }
    parts.push({ mode: 'freehand', points: simplifyForSnap(action.points) })
  })
  if (invalid) return null
  return normalizeRouteParts(parts)
}

function routePartsForRequest(parts) {
  var normalized = normalizeRouteParts(parts)
  if (!normalized) return null
  return normalized.map(function (part) {
    if (part.mode === 'snap') {
      return { mode: 'snap', routing_receipt: part.routing_receipt, points: [] }
    }
    return { mode: 'freehand', points: cloneLonLatPoints(part.points) }
  })
}

function isRoutingReceiptError(err) {
  return Boolean(
    err &&
    Number(err.code) === 422 &&
    err.detail &&
    err.detail.code === 'routing_receipt_invalid'
  )
}

function refreshActionsFromRouteParts(parts, snapper) {
  var normalized = normalizeRouteParts(parts)
  if (!normalized) return Promise.reject(new Error('路线片段已损坏'))
  return normalized.reduce(function (chain, part) {
    return chain.then(function (actions) {
      if (part.mode === 'freehand') {
        actions.push({
          kind: 'segment',
          mode: 'freehand',
          rawPoints: cloneLonLatPoints(part.points),
          points: cloneLonLatPoints(part.points),
          warnings: [],
          routingReceipt: '',
        })
        return actions
      }
      if (part.raw_points.length < 2) throw new Error('旧贴路片段缺少重算点')
      return snapper({
        coordinate_system: 'gcj02',
        mode: 'snap',
        points: cloneLonLatPoints(part.raw_points),
      }).then(function (result) {
        var preview = normalizeLonLatPoints(result && result.snapped_points)
        var receipt = String(result && result.routing_receipt || '')
        if (preview.length < 2 || !receipt) throw new Error('智能贴路刷新失败')
        actions.push({
          kind: 'segment',
          mode: 'snap',
          rawPoints: cloneLonLatPoints(part.raw_points),
          points: preview,
          warnings: result && Array.isArray(result.warnings) ? result.warnings : [],
          routingReceipt: receipt,
        })
        return actions
      })
    })
  }, Promise.resolve([]))
}

function samplePoints(points, limit) {
  var normalized = normalizeLonLatPoints(points)
  if (normalized.length <= limit) return normalized
  var result = []
  var step = (normalized.length - 1) / (limit - 1)
  for (var i = 0; i < limit; i += 1) {
    result.push(normalized[Math.round(i * step)])
  }
  return result
}

function flattenWarnings(segmentWarnings, currentWarnings) {
  var result = []
  ;(segmentWarnings || []).forEach(function (warnings) {
    ;(warnings || []).forEach(function (warning) {
      if (warning && result.length < 20) result.push(warning)
    })
  })
  ;(currentWarnings || []).forEach(function (warning) {
    if (warning && result.length < 20) result.push(warning)
  })
  return result
}

function buildDrawMetadata(segmentModes, rawSegments, segmentWarnings) {
  var modes = Array.isArray(segmentModes) ? segmentModes : []
  var rawPoints = mergeSegments(rawSegments || [])
  var freehandCount = modes.filter(function (mode) { return mode === 'freehand' }).length
  return {
    tool: 'route_draw_v0',
    snap_provider: freehandCount === modes.length ? 'freehand' : 'tencent_bicycling',
    segment_count: modes.length,
    freehand_segment_count: freehandCount,
    warnings: flattenWarnings(segmentWarnings, []),
    raw_points_summary: {
      total_raw_points: rawPoints.length,
      sample: samplePoints(rawPoints, 20),
    },
  }
}

function screenPointFromEvent(event) {
  var touch = event && event.touches && event.touches[0]
  if (!touch && event && event.changedTouches) touch = event.changedTouches[0]
  if (!touch) return null
  var x = finiteNumber(touch.x !== undefined ? touch.x : touch.clientX, NaN)
  var y = finiteNumber(touch.y !== undefined ? touch.y : touch.clientY, NaN)
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  return { x: x, y: y }
}

function screenDistance(a, b) {
  if (!a || !b) return Infinity
  var dx = a.x - b.x
  var dy = a.y - b.y
  return Math.sqrt(dx * dx + dy * dy)
}

function mapPointFromTapEvent(event) {
  var detail = event && event.detail
  if (!detail) return null
  return normalizeLonLatPoint({
    longitude: detail.longitude,
    latitude: detail.latitude,
  })
}

function mapContextFromScreenLocation(context, screenPoint) {
  return new Promise(function (resolve, reject) {
    if (!context || typeof context.fromScreenLocation !== 'function') {
      reject(new Error('fromScreenLocation unavailable'))
      return
    }
    var settled = false
    var timeout = setTimeout(function () {
      if (settled) return
      settled = true
      reject(new Error('fromScreenLocation timeout'))
    }, SKETCH_LOCATION_TIMEOUT_MS)
    function settle(fn, value) {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      fn(value)
    }
    context.fromScreenLocation({
      x: screenPoint.x,
      y: screenPoint.y,
      success: function (res) {
        var lon = Number(res && res.longitude)
        var lat = Number(res && res.latitude)
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
          settle(reject, new Error('bad location'))
          return
        }
        settle(resolve, [lon, lat])
      },
      fail: function (err) {
        settle(reject, err || new Error('fromScreenLocation failed'))
      },
    })
  })
}

function snapErrorMessage(err) {
  if (err && err.code === -1) return '网络断了，这段没有贴上路，可以切 Manual Mode 直连。'
  if (err && err.code === 404) return '贴路服务还没上线，可以切 Manual Mode 继续画。'
  if (err && err.code === 429 && err.detail && err.detail.code === 'routing_receipt_quota') {
    return '智能贴路草稿已达当前上限，可以切 Manual Mode 继续画。'
  }
  if (err && err.code === 429) return '贴路操作太快，稍等再试，或切 Manual Mode 继续画。'
  if (err && err.code === 503) return '贴路服务暂时不可用，可以先用 Manual Mode 保存。'
  if (err && err.code === 422) return '这段附近没有找到合适的路，缩短一点或切 Manual Mode。'
  if (err && err.code >= 500) return '贴路服务暂时不可用，可以先用 Manual Mode 保存。'
  return '这一段没有贴好，缩短一点或切 Manual Mode。'
}

function saveErrorMessage(err) {
  if (err && err.code === -1) return '网络断了，路线没有保存成功。'
  if (err && err.code === 409) return '保存记录冲突，请重新确认这条路线。'
  if (err && err.code === 410) return '上次保存的路线已删除，请重新保存。'
  if (err && (err.code === 404 || err.code === 405)) return '路线保存服务还没上线，先更新服务后再试。'
  if (err && err.code === 422 && err.message && err.message.indexOf('海拔') >= 0) {
    return '路线海拔还没算好，请稍后再试。'
  }
  return '路线没有保存成功，请稍后再试'
}

function twoDigit(value) {
  return value < 10 ? '0' + value : String(value)
}

function defaultRouteName(now) {
  var date = now instanceof Date ? now : new Date()
  return '手画路线 ' + twoDigit(date.getMonth() + 1) + '-' + twoDigit(date.getDate()) + ' ' + twoDigit(date.getHours()) + ':' + twoDigit(date.getMinutes())
}

function currentUserId() {
  var app = typeof getApp === 'function' ? getApp() : null
  var userId = Number(app && app.globalData && app.globalData.userId)
  if (!userId && typeof wx !== 'undefined' && typeof wx.getStorageSync === 'function') {
    userId = Number(wx.getStorageSync('userId'))
  }
  return Number.isInteger(userId) && userId > 0 ? userId : 0
}

function newClientRequestId() {
  return [
    'rd',
    Date.now().toString(36),
    Math.random().toString(36).slice(2, 12),
    Math.random().toString(36).slice(2, 12),
  ].join('-')
}

function normalizePendingSavePayload(value) {
  if (!value || typeof value !== 'object') return null
  var clientRequestId = String(value.client_request_id || '')
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(clientRequestId)) return null
  var name = String(value.name || '').trim().slice(0, 128)
  if (!name) return null
  if (value.coordinate_system !== 'gcj02' && value.coordinate_system !== 'wgs84') return null
  var points = normalizeLonLatPoints(value.points)
  if (points.length < 2 || points.length > MAX_SAVE_POINTS) return null
  var routeParts = value.route_parts === undefined || value.route_parts === null
    ? null
    : normalizeRouteParts(value.route_parts)
  if (value.route_parts !== undefined && value.route_parts !== null && !routeParts) return null
  var normalized = {
    name: name,
    client_request_id: clientRequestId,
    coordinate_system: value.coordinate_system,
    points: points,
    draw_metadata: value.draw_metadata && typeof value.draw_metadata === 'object'
      ? value.draw_metadata
      : null,
  }
  // 线上旧版保存接口还不认识 route_parts；没有 receipt 时必须完全省略字段，不能发送 null。
  if (routeParts) normalized.route_parts = routeParts
  return normalized
}

function pendingSaveStorageKey() {
  var userId = currentUserId()
  return userId ? PENDING_SAVE_STORAGE_PREFIX + userId : ''
}

function persistPendingSave(payload) {
  var normalized = normalizePendingSavePayload(payload)
  if (!normalized) return false
  if (JSON.stringify(normalized).length > MAX_PENDING_SAVE_BYTES) return false
  if (typeof wx === 'undefined' || typeof wx.setStorageSync !== 'function') {
    memoryPendingSave = normalized
    return true
  }
  var key = pendingSaveStorageKey()
  if (!key) return false
  try {
    wx.setStorageSync(key, normalized)
    return true
  } catch (err) {
    return false
  }
}

function readPendingSave() {
  if (typeof wx === 'undefined' || typeof wx.getStorageSync !== 'function') {
    return normalizePendingSavePayload(memoryPendingSave)
  }
  var key = pendingSaveStorageKey()
  if (!key) return null
  var value = null
  try {
    value = wx.getStorageSync(key)
  } catch (err) {
    return null
  }
  return normalizePendingSavePayload(value)
}

function clearPendingSave() {
  memoryPendingSave = null
  if (typeof wx === 'undefined' || typeof wx.removeStorageSync !== 'function') return
  var key = pendingSaveStorageKey()
  if (!key) return
  try {
    wx.removeStorageSync(key)
  } catch (err) {}
}

function modeTitle(mode) {
  if (mode === 'manual') return 'Manual Mode'
  if (mode === 'sketch') return '铅笔手绘'
  return '智能贴路'
}

function modeHelp(mode) {
  if (mode === 'manual') return '拖动地图对准路口后点添加点，会按直线接上。'
  if (mode === 'sketch') return '按住地图画一小段，松手后自动处理。'
  return '拖动地图对准路口后点添加点；也可以直接点地图。'
}

function cloneAction(action) {
  if (!action || typeof action !== 'object') return null
  if (action.kind === 'anchor') {
    var anchor = normalizeLonLatPoint(action.point)
    if (!anchor) return null
    return { kind: 'anchor', point: anchor }
  }
  if (action.kind === 'segment') {
    return {
      kind: 'segment',
      mode: action.mode === 'freehand' ? 'freehand' : 'snap',
      rawPoints: cloneLonLatPoints(action.rawPoints),
      points: cloneLonLatPoints(action.points),
      warnings: Array.isArray(action.warnings) ? action.warnings.slice(0, 20) : [],
      routingReceipt: typeof action.routingReceipt === 'string' ? action.routingReceipt.slice(0, 512) : '',
    }
  }
  return null
}

function cloneActions(actions) {
  var result = []
  ;(actions || []).forEach(function (action) {
    var cloned = cloneAction(action)
    if (cloned) result.push(cloned)
  })
  return result
}

function clonePending(pending) {
  if (!pending) return null
  return {
    mode: pending.mode === 'freehand' ? 'freehand' : 'snap',
    rawPoints: cloneLonLatPoints(pending.rawPoints),
    previewPoints: cloneLonLatPoints(pending.previewPoints),
    warnings: Array.isArray(pending.warnings) ? pending.warnings.slice(0, 20) : [],
  }
}

function buildMarkers(actions) {
  var markerPoints = []
  cloneActions(actions).forEach(function (action) {
    if (action.kind === 'anchor') {
      markerPoints.push(action.point)
      return
    }
    if (action.kind === 'segment') {
      var points = normalizeLonLatPoints(action.points)
      if (!points.length) return
      if (!markerPoints.length) markerPoints.push(points[0])
      markerPoints.push(points[points.length - 1])
    }
  })
  return markerPoints.map(function (point, index) {
    return {
      id: index + 1,
      longitude: point[0],
      latitude: point[1],
      width: 18,
      height: 18,
      callout: {
        content: index === 0 ? '起点' : String(index + 1),
        color: '#1C1C1E',
        fontSize: 12,
        borderRadius: 6,
        bgColor: '#FFFFFF',
        padding: 4,
        display: 'BYCLICK',
      },
    }
  })
}

function deriveDraftView(actions, pending) {
  var safeActions = cloneActions(actions)
  var safePending = clonePending(pending)
  var segments = []
  var modes = []
  var rawSegments = []
  var segmentWarnings = []

  safeActions.forEach(function (action) {
    if (action.kind !== 'segment') return
    var segmentPoints = cloneLonLatPoints(action.points)
    if (segmentPoints.length < 2) return
    segments.push(segmentPoints)
    modes.push(action.mode)
    rawSegments.push(cloneLonLatPoints(action.rawPoints))
    segmentWarnings.push(Array.isArray(action.warnings) ? action.warnings.slice(0, 20) : [])
  })

  var confirmedPoints = segments.length ? mergeSegments(segments) : []
  if (!confirmedPoints.length) {
    safeActions.some(function (action) {
      if (action.kind !== 'anchor') return false
      confirmedPoints = [action.point]
      return true
    })
  }

  return {
    actions: safeActions,
    segments: segments,
    modes: modes,
    rawSegments: rawSegments,
    segmentWarnings: segmentWarnings,
    confirmedPoints: confirmedPoints,
    pending: safePending,
    currentRawPoints: safePending ? safePending.rawPoints : [],
    previewPoints: safePending ? safePending.previewPoints : [],
    pendingWarnings: safePending ? safePending.warnings : [],
    markers: buildMarkers(safeActions),
  }
}

function buildRouteDraft(actions, pending, segments) {
  return {
    actions: cloneActions(actions),
    segments: (segments || []).map(cloneLonLatPoints),
    pending: clonePending(pending),
  }
}

Page({
  data: {
    notLoggedIn: false,
    gestureSupported: true,
    builderMode: 'smart',
    requestStatus: 'idle',
    statusText: '拖动地图对准起点，点添加点',
    modeTitle: modeTitle('smart'),
    modeHelp: modeHelp('smart'),
    errorMessage: '',
    latitude: DEFAULT_CENTER.latitude,
    longitude: DEFAULT_CENTER.longitude,
    mapScrollEnabled: true,
    centerAddBusy: false,
    showSketchLayer: false,
    isSketching: false,
    routeDraft: {
      actions: [],
      segments: [],
      pending: null,
    },
    confirmedSegments: [],
    confirmedSegmentModes: [],
    confirmedRawSegments: [],
    confirmedSegmentWarnings: [],
    confirmedPoints: [],
    markers: [],
    currentRawPoints: [],
    previewPoints: [],
    drawPolylines: [],
    routeStats: buildRouteStats([]),
    routeName: '',
    warnings: [],
    currentWarnings: [],
    saving: false,
    pendingSaveLocked: false,
    savedRouteBookId: null,
    saveError: '',
    canSaveRoute: false,
  },

  onLoad: function () {
    if (this.ensureLoggedIn()) this.restorePendingSave()
  },

  onReady: function () {
    if (typeof wx.createMapContext === 'function') {
      this.mapContext = wx.createMapContext('route-draw-map', this)
    }
  },

  ensureLoggedIn: function () {
    var app = typeof getApp === 'function' ? getApp() : null
    var token = app && app.globalData && app.globalData.token
    if (!token) {
      this.setData({
        notLoggedIn: true,
        requestStatus: 'error',
        statusText: '登录后才能画路线',
        errorMessage: '登录后才能保存和贴路。',
        canSaveRoute: false,
      })
      return false
    }
    if (this.data.notLoggedIn) {
      this.setData({
        notLoggedIn: false,
        errorMessage: '',
        requestStatus: 'idle',
        statusText: '拖动地图对准起点，点添加点',
      })
    }
    return true
  },

  restorePendingSave: function () {
    var payload = readPendingSave()
    if (!payload) return false
    var action = {
      kind: 'segment',
      mode: 'freehand',
      points: cloneLonLatPoints(payload.points),
      rawPoints: cloneLonLatPoints(payload.points),
      warnings: [],
    }
    this.applyDraftState([action], null, {
      routeName: payload.name,
      saving: false,
      pendingSaveLocked: true,
      requestStatus: 'unknown',
      saveError: '上次保存结果待确认',
      statusText: '发现一条上次未确认的保存',
      errorMessage: '点“确认上次保存”会用同一个请求号查询，不会重复创建路线。',
      canSaveRoute: false,
    })
    return true
  },

  preventPendingSaveEdit: function () {
    if (!this.data.pendingSaveLocked) return false
    wx.showToast({ title: '先确认或放弃上次保存', icon: 'none' })
    return true
  },

  applyDraftState: function (actions, pending, extraPatch) {
    var patch = extraPatch || {}
    var view = deriveDraftView(actions, pending)
    var nextRequestStatus = patch.requestStatus !== undefined ? patch.requestStatus : this.data.requestStatus
    var nextBuilderMode = patch.builderMode !== undefined ? patch.builderMode : this.data.builderMode
    var nextSaving = patch.saving !== undefined ? patch.saving : this.data.saving
    var nextSavedRouteBookId = patch.savedRouteBookId !== undefined
      ? patch.savedRouteBookId
      : this.data.savedRouteBookId
    var canSaveRoute = (
      view.confirmedPoints.length >= 2 &&
      nextRequestStatus !== 'previewing' &&
      nextRequestStatus !== 'saving' &&
      nextRequestStatus !== 'unknown' &&
      nextBuilderMode !== 'sketch' &&
      !nextSaving &&
      !nextSavedRouteBookId
    )

    this.setData(Object.assign({
      routeDraft: buildRouteDraft(view.actions, view.pending, view.segments),
      confirmedSegments: view.segments,
      confirmedSegmentModes: view.modes,
      confirmedRawSegments: view.rawSegments,
      confirmedSegmentWarnings: view.segmentWarnings,
      confirmedPoints: view.confirmedPoints,
      markers: view.markers,
      currentRawPoints: view.currentRawPoints,
      previewPoints: view.previewPoints,
      currentWarnings: view.pendingWarnings,
      warnings: flattenWarnings(view.segmentWarnings, view.pendingWarnings),
      drawPolylines: buildDrawPolylines(view.confirmedPoints, view.currentRawPoints, view.previewPoints),
      routeStats: buildRouteStats(view.confirmedPoints),
      canSaveRoute: canSaveRoute,
    }, patch))
  },

  updateMode: function (mode, patch) {
    this.applyDraftState(
      this.data.routeDraft.actions,
      this.data.routeDraft.pending,
      Object.assign({
        builderMode: mode,
        modeTitle: modeTitle(mode),
        modeHelp: modeHelp(mode),
      }, patch || {})
    )
  },

  markGestureUnsupported: function () {
    this.applyDraftState(this.data.routeDraft.actions, null, {
      gestureSupported: false,
      builderMode: this._builderModeBeforeSketch || 'smart',
      modeTitle: modeTitle(this._builderModeBeforeSketch || 'smart'),
      modeHelp: modeHelp(this._builderModeBeforeSketch || 'smart'),
      requestStatus: 'error',
      statusText: '当前微信版本暂不支持铅笔手绘',
      errorMessage: '可以继续点地图创建路线，或更新微信后再试铅笔手绘。',
      showSketchLayer: false,
      isSketching: false,
      mapScrollEnabled: true,
    })
  },

  lastConfirmedPoint: function () {
    var points = normalizeLonLatPoints(this.data.confirmedPoints)
    return points.length ? points[points.length - 1] : null
  },

  commitAnchorAction: function (point) {
    this._snapSeq = (this._snapSeq || 0) + 1
    var actions = cloneActions(this.data.routeDraft.actions)
    actions.push({ kind: 'anchor', point: point })
    this.applyDraftState(actions, null, {
      requestStatus: 'idle',
      statusText: '起点已设置，继续点下一个路口',
      errorMessage: '',
      latitude: point[1],
      longitude: point[0],
    })
  },

  commitSegmentAction: function (segment) {
    this._snapSeq = (this._snapSeq || 0) + 1
    var points = cloneLonLatPoints(segment && segment.points)
    if (points.length < 2) return
    var actions = cloneActions(this.data.routeDraft.actions)
    actions.push({
      kind: 'segment',
      mode: segment.mode === 'freehand' ? 'freehand' : 'snap',
      rawPoints: cloneLonLatPoints(segment.rawPoints || points),
      points: points,
      warnings: Array.isArray(segment.warnings) ? segment.warnings.slice(0, 20) : [],
      routingReceipt: typeof segment.routingReceipt === 'string' ? segment.routingReceipt.slice(0, 512) : '',
    })
    this.applyDraftState(actions, null, {
      requestStatus: 'idle',
      statusText: '这一段已接上，继续点地图加路线点',
      errorMessage: '',
    })
  },

  onMapRegionChange: function (event) {
    if (this.data.builderMode === 'sketch') return
    if (this.data.requestStatus !== 'idle') return
    if (!event || event.type !== 'end') return
    this.setData({
      statusText: this.lastConfirmedPoint() ? '对准下一个路口，点添加点' : '对准起点，点添加点',
    })
  },

  readMapCenterPoint: function () {
    var that = this
    var fallback = normalizeLonLatPoint({
      longitude: this.data.longitude,
      latitude: this.data.latitude,
    }) || [DEFAULT_CENTER.longitude, DEFAULT_CENTER.latitude]
    var context = this.mapContext || (typeof wx.createMapContext === 'function' ? wx.createMapContext('route-draw-map', this) : null)

    return new Promise(function (resolve) {
      if (!context || typeof context.getCenterLocation !== 'function') {
        resolve(fallback)
        return
      }
      context.getCenterLocation({
        success: function (res) {
          var point = normalizeLonLatPoint({
            longitude: res && res.longitude,
            latitude: res && res.latitude,
          }) || fallback
          that.setData({
            latitude: point[1],
            longitude: point[0],
          })
          resolve(point)
        },
        fail: function () {
          wx.showToast({ title: '没有读到地图中心，先按当前中心加点', icon: 'none' })
          resolve(fallback)
        },
      })
    })
  },

  onTapAddCenterPoint: function () {
    if (this.preventPendingSaveEdit()) return Promise.resolve()
    if (!this.ensureLoggedIn()) return Promise.resolve()
    if (this.data.builderMode === 'sketch') {
      wx.showToast({ title: '先退出铅笔手绘', icon: 'none' })
      return Promise.resolve()
    }
    if (this.data.requestStatus === 'previewing') {
      wx.showToast({ title: '等这一段贴好再继续', icon: 'none' })
      return Promise.resolve()
    }
    if (this.data.requestStatus === 'saving' || this.data.saving || this.data.centerAddBusy) return Promise.resolve()

    var that = this
    this.setData({ centerAddBusy: true })
    return this.readMapCenterPoint().then(function (point) {
      that.setData({ centerAddBusy: false })
      that.addRoutePoint(point)
    }).catch(function () {
      that.setData({ centerAddBusy: false })
      wx.showToast({ title: '没有读到地图中心，再试一次', icon: 'none' })
    })
  },

  onMapTap: function (event) {
    if (this.preventPendingSaveEdit()) return
    if (!this.ensureLoggedIn()) return
    if (this.data.builderMode === 'sketch') return
    if (this.data.requestStatus === 'previewing') {
      wx.showToast({ title: '等这一段贴好再继续', icon: 'none' })
      return
    }
    if (this.data.requestStatus === 'saving' || this.data.saving) return

    var point = mapPointFromTapEvent(event)
    if (!point) {
      wx.showToast({ title: '这次没有取到地图点，再点一次', icon: 'none' })
      return
    }

    this.addRoutePoint(point)
  },

  addRoutePoint: function (point) {
    var normalized = normalizeLonLatPoint(point)
    if (!normalized) {
      wx.showToast({ title: '没有取到地图点，再试一次', icon: 'none' })
      return
    }

    var lastPoint = this.lastConfirmedPoint()
    if (!lastPoint) {
      this.commitAnchorAction(normalized)
      return
    }
    if (samePoint(lastPoint, normalized)) return

    var raw = [lastPoint, normalized]
    if (this.data.builderMode === 'manual') {
      this.commitSegmentAction({
        mode: 'freehand',
        rawPoints: raw,
        points: raw,
        warnings: [],
      })
      return
    }

    this.startSnapPreview(raw)
  },

  startSnapPreview: function (rawPoints) {
    if (!this.ensureLoggedIn()) return
    var raw = cloneLonLatPoints(rawPoints)
    if (raw.length < 2) return

    var that = this
    this._snapSeq = (this._snapSeq || 0) + 1
    var snapSeq = this._snapSeq
    var pending = {
      mode: 'snap',
      rawPoints: raw,
      previewPoints: raw,
      warnings: [],
    }
    this.applyDraftState(this.data.routeDraft.actions, pending, {
      requestStatus: 'previewing',
      statusText: '正在帮你贴到可骑行道路',
      errorMessage: '',
      showSketchLayer: false,
      isSketching: false,
      mapScrollEnabled: true,
    })

    api.snapManualDrawnRoute({
      coordinate_system: 'gcj02',
      mode: 'snap',
      points: simplifyForSnap(raw),
    }).then(function (result) {
      if (snapSeq !== that._snapSeq) return
      var preview = normalizeLonLatPoints(result && result.snapped_points)
      if (preview.length < 2) throw { code: 422 }
      var warnings = (result && Array.isArray(result.warnings)) ? result.warnings : []
      that.commitSegmentAction({
        mode: 'snap',
        rawPoints: raw,
        points: preview,
        warnings: warnings,
        routingReceipt: result && result.routing_receipt,
      })
      that.applyDraftState(that.data.routeDraft.actions, null, {
        requestStatus: 'idle',
        statusText: '贴路成功，橙色路线已并入草稿',
      })
    }).catch(function (err) {
      if (snapSeq !== that._snapSeq) return
      var message = snapErrorMessage(err)
      that.applyDraftState(that.data.routeDraft.actions, {
        mode: 'snap',
        rawPoints: raw,
        previewPoints: [],
        warnings: [],
      }, {
        requestStatus: 'error',
        statusText: message,
        errorMessage: message,
        showSketchLayer: false,
        isSketching: false,
        mapScrollEnabled: true,
      })
    })
  },

  onTapToggleManualMode: function () {
    if (this.preventPendingSaveEdit()) return
    if (this.data.requestStatus === 'previewing' || this.data.requestStatus === 'saving' || this.data.saving) return

    var next = this.data.builderMode === 'manual' ? 'smart' : 'manual'
    var pending = clonePending(this.data.routeDraft.pending)
    if (next === 'manual' && this.data.requestStatus === 'error' && pending && pending.rawPoints.length >= 2) {
      this.updateMode('manual', {
        requestStatus: 'idle',
        statusText: '已切 Manual Mode，这段按直线接上',
        errorMessage: '',
      })
      this.commitSegmentAction({
        mode: 'freehand',
        rawPoints: pending.rawPoints,
        points: pending.rawPoints,
        warnings: [],
      })
      return
    }

    this._snapSeq = (this._snapSeq || 0) + 1
    this.applyDraftState(this.data.routeDraft.actions, null, {
      builderMode: next,
      modeTitle: modeTitle(next),
      modeHelp: modeHelp(next),
      requestStatus: 'idle',
      statusText: next === 'manual' ? 'Manual Mode 已开启，点地图会直连' : '智能贴路已开启，继续点地图加路线点',
      errorMessage: '',
      showSketchLayer: false,
      isSketching: false,
      mapScrollEnabled: true,
    })
  },

  onTapStartSketch: function () {
    if (this.preventPendingSaveEdit()) return
    if (!this.ensureLoggedIn()) return
    if (!this.data.gestureSupported || this.data.requestStatus === 'previewing' || this.data.requestStatus === 'saving' || this.data.saving) return
    if (this.data.builderMode === 'sketch') {
      this.finishSketchMode('已退出铅笔手绘')
      return
    }

    this._snapSeq = (this._snapSeq || 0) + 1
    this._builderModeBeforeSketch = this.data.builderMode === 'manual' ? 'manual' : 'smart'
    this.applyDraftState(this.data.routeDraft.actions, null, {
      builderMode: 'sketch',
      modeTitle: modeTitle('sketch'),
      modeHelp: modeHelp('sketch'),
      requestStatus: 'idle',
      statusText: '按住地图画一小段，松手后处理',
      errorMessage: '',
      showSketchLayer: true,
      isSketching: false,
      mapScrollEnabled: false,
    })
  },

  onDrawTouchStart: function (event) {
    if (this.data.pendingSaveLocked) return
    if (!this.ensureLoggedIn()) return
    if (this.data.builderMode !== 'sketch') return
    if (!this.data.gestureSupported || this.data.requestStatus === 'previewing' || this.data.saving) return

    this.clearSketchAutoFinish()
    this._drawSeq = (this._drawSeq || 0) + 1
    this._rawSegmentPoints = []
    this._lastScreenPoint = null
    this._lastCaptureAt = 0
    this._captureChain = Promise.resolve()
    this.applyDraftState(this.data.routeDraft.actions, null, {
      requestStatus: 'idle',
      statusText: '继续沿路画，松手后处理',
      errorMessage: '',
      showSketchLayer: true,
      isSketching: true,
      mapScrollEnabled: false,
    })
    this.captureTouchLocation(event, true)
    this.armSketchAutoFinish()
  },

  onDrawTouchMove: function (event) {
    if (this.data.pendingSaveLocked) return
    if (this.data.builderMode !== 'sketch' || !this.data.isSketching) return
    this.captureTouchLocation(event, false)
    this.armSketchAutoFinish()
  },

  onDrawTouchEnd: function (event) {
    if (this.data.pendingSaveLocked) return
    if (this.data.builderMode !== 'sketch' || !this.data.isSketching) return
    this.clearSketchAutoFinish()
    this.captureTouchLocation(event, true)
    this.finishSketchAfterCapture()
  },

  armSketchAutoFinish: function () {
    var that = this
    this.clearSketchAutoFinish()
    this._sketchAutoFinishTimer = setTimeout(function () {
      that._sketchAutoFinishTimer = null
      that.finishSketchAfterCapture()
    }, SKETCH_AUTO_FINISH_MS)
  },

  clearSketchAutoFinish: function () {
    if (this._sketchAutoFinishTimer === undefined || this._sketchAutoFinishTimer === null) return
    clearTimeout(this._sketchAutoFinishTimer)
    this._sketchAutoFinishTimer = null
  },

  finishSketchAfterCapture: function () {
    var that = this
    var finished = false
    var timeout = setTimeout(function () {
      if (finished) return
      finished = true
      if (that.data.builderMode === 'sketch' && that.data.isSketching) {
        that.finishSketchSegment()
      }
    }, SKETCH_LOCATION_TIMEOUT_MS + 120)

    ;(this._captureChain || Promise.resolve()).then(function () {
      if (finished) return
      finished = true
      clearTimeout(timeout)
      if (that.data.builderMode === 'sketch' && that.data.isSketching) {
        that.finishSketchSegment()
      }
    }).catch(function () {
      if (finished) return
      finished = true
      clearTimeout(timeout)
      if (that.data.builderMode === 'sketch' && that.data.isSketching) {
        that.finishSketchSegment()
      }
    })
  },

  captureTouchLocation: function (event, force) {
    var screenPoint = screenPointFromEvent(event)
    if (!screenPoint) return
    var now = Date.now()
    if (!force && now - this._lastCaptureAt < TOUCH_SAMPLE_INTERVAL_MS && screenDistance(screenPoint, this._lastScreenPoint) < TOUCH_SAMPLE_DISTANCE_PX) {
      return
    }
    this._lastCaptureAt = now
    this._lastScreenPoint = screenPoint

    var that = this
    var seq = this._drawSeq
    var context = this.mapContext || (typeof wx.createMapContext === 'function' ? wx.createMapContext('route-draw-map', this) : null)
    this._captureChain = (this._captureChain || Promise.resolve()).then(function () {
      return mapContextFromScreenLocation(context, screenPoint)
    }).then(function (point) {
      if (seq !== that._drawSeq) return
      var raw = that._rawSegmentPoints || []
      if (!raw.length || !samePoint(raw[raw.length - 1], point)) raw.push(point)
      that._rawSegmentPoints = raw
      if (force || raw.length % 3 === 0) {
        that.applyDraftState(that.data.routeDraft.actions, {
          mode: 'freehand',
          rawPoints: raw.slice(),
          previewPoints: [],
          warnings: [],
        }, {
          requestStatus: 'idle',
          showSketchLayer: true,
          isSketching: true,
          mapScrollEnabled: false,
        })
      }
    }).catch(function () {
      if (seq === that._drawSeq) that.markGestureUnsupported()
    })
  },

  finishSketchSegment: function () {
    if (!this.ensureLoggedIn()) return
    if (this.data.builderMode !== 'sketch') return
    this.clearSketchAutoFinish()

    var previousMode = this._builderModeBeforeSketch || 'smart'
    var raw = normalizeLonLatPoints(this._rawSegmentPoints || this.data.currentRawPoints)
    var lastPoint = this.lastConfirmedPoint()
    if (lastPoint && raw.length && !samePoint(lastPoint, raw[0])) {
      raw = [lastPoint].concat(raw)
    }

    if (raw.length < 2 || distanceOf(raw) < 5) {
      this.applyDraftState(this.data.routeDraft.actions, null, {
        builderMode: previousMode,
        modeTitle: modeTitle(previousMode),
        modeHelp: modeHelp(previousMode),
        requestStatus: 'idle',
        statusText: '这段太短了，再多画一点',
        showSketchLayer: false,
        isSketching: false,
        mapScrollEnabled: true,
      })
      return
    }

    this.applyDraftState(this.data.routeDraft.actions, null, {
      builderMode: previousMode,
      modeTitle: modeTitle(previousMode),
      modeHelp: modeHelp(previousMode),
      requestStatus: 'idle',
      showSketchLayer: false,
      isSketching: false,
      mapScrollEnabled: true,
    })

    if (previousMode === 'manual') {
      this.commitSegmentAction({
        mode: 'freehand',
        rawPoints: raw,
        points: raw,
        warnings: [],
      })
      return
    }

    this.startSnapPreview(raw)
  },

  finishSketchMode: function (text) {
    this.clearSketchAutoFinish()
    var previousMode = this._builderModeBeforeSketch || 'smart'
    this.applyDraftState(this.data.routeDraft.actions, null, {
      builderMode: previousMode,
      modeTitle: modeTitle(previousMode),
      modeHelp: modeHelp(previousMode),
      requestStatus: 'idle',
      statusText: text || '已退出铅笔手绘',
      showSketchLayer: false,
      isSketching: false,
      mapScrollEnabled: true,
    })
  },

  onTapUndoAction: function () {
    if (this.preventPendingSaveEdit()) return
    this._snapSeq = (this._snapSeq || 0) + 1
    if (this.data.builderMode === 'sketch') {
      this.finishSketchMode('已退出铅笔手绘')
      return
    }
    var pending = this.data.routeDraft.pending
    if (pending) {
      this.applyDraftState(this.data.routeDraft.actions, null, {
        requestStatus: 'idle',
        statusText: '已丢弃当前预览',
        errorMessage: '',
        showSketchLayer: false,
        isSketching: false,
        mapScrollEnabled: true,
      })
      return
    }

    var actions = cloneActions(this.data.routeDraft.actions)
    if (!actions.length) {
      wx.showToast({ title: '还没有可撤回的动作', icon: 'none' })
      return
    }
    actions.pop()
    this.applyDraftState(actions, null, {
      requestStatus: 'idle',
      statusText: actions.length ? '已撤回上一步' : '路线已清空，点地图设置起点',
      errorMessage: '',
    })
  },

  onTapLocate: function () {
    var that = this
    if (typeof wx.getLocation !== 'function') return
    wx.getLocation({
      type: 'gcj02',
      success: function (res) {
        var point = normalizeLonLatPoint({ longitude: res.longitude, latitude: res.latitude })
        if (!point) return
        that.setData({
          latitude: point[1],
          longitude: point[0],
          statusText: '已回到你附近，点地图设置路线点',
        })
      },
      fail: function () {
        wx.showToast({ title: '没有拿到当前位置，可以手动拖地图', icon: 'none' })
      },
    })
  },

  onTapClose: function () {
    if (typeof wx.navigateBack === 'function') {
      wx.navigateBack({
        delta: 1,
        fail: function () {
          wx.switchTab({ url: '/pages/explore/explore' })
        },
      })
      return
    }
    wx.switchTab({ url: '/pages/explore/explore' })
  },

  onRouteNameInput: function (event) {
    if (this.data.pendingSaveLocked) return
    this.setData({ routeName: event.detail.value })
  },

  onTapSave: function () {
    if (!this.ensureLoggedIn()) return
    if (this.data.savedRouteBookId) {
      this.onTapOpenSavedRoute()
      return
    }
    if (this.data.requestStatus === 'unknown') {
      wx.showToast({ title: '保存结果不确定，请先到我的路书确认', icon: 'none' })
      return
    }
    if (this.data.saving || this.data.requestStatus === 'saving') return
    if (this.data.requestStatus === 'previewing') {
      wx.showToast({ title: '等这一段贴好再保存', icon: 'none' })
      return
    }
    if (this.data.builderMode === 'sketch') {
      wx.showToast({ title: '先退出铅笔手绘', icon: 'none' })
      return
    }
    if (this.data.routeDraft.pending) {
      wx.showToast({ title: '先处理当前预览', icon: 'none' })
      return
    }
    var confirmedPoints = normalizeLonLatPoints(this.data.confirmedPoints)
    if (confirmedPoints.length < 2) {
      wx.showToast({ title: '至少点 2 个点再保存', icon: 'none' })
      return
    }
    var name = String(this.data.routeName || '').trim() || defaultRouteName(new Date())
    var points = simplifyForSave(confirmedPoints)
    if (points.length > MAX_SAVE_POINTS) {
      wx.showToast({ title: '路线太长，分几段保存更稳', icon: 'none' })
      return
    }

    var drawMetadata = buildDrawMetadata(
      this.data.confirmedSegmentModes,
      this.data.confirmedRawSegments,
      this.data.confirmedSegmentWarnings
    )
    var actions = cloneActions(this.data.routeDraft.actions)
    var routeParts = buildRouteParts(actions)
    var hasLegacySnapSegment = actions.some(function (action) {
      return action.kind === 'segment' && action.mode === 'snap' && !action.routingReceipt
    })
    if (!routeParts && !hasLegacySnapSegment) {
      wx.showToast({ title: '路线片段已失效，请重新贴路', icon: 'none' })
      return
    }
    var payload = {
      name: name,
      client_request_id: newClientRequestId(),
      coordinate_system: 'gcj02',
      points: points,
      draw_metadata: drawMetadata,
    }
    // 新后端返回 receipt 时走服务端重建；旧线上协议则继续用已确认的 points 保存。
    if (routeParts) payload.route_parts = routeParts
    if (!persistPendingSave(payload)) {
      wx.showToast({ title: '无法安全保存草稿，请重新登录或清理存储空间', icon: 'none' })
      return
    }
    this.submitPendingSave(payload)
  },

  onTapConfirmPendingSave: function () {
    if (!this.ensureLoggedIn()) return
    if (this.data.saving || this.data.requestStatus === 'saving') return
    var payload = readPendingSave()
    if (!payload) {
      clearPendingSave()
      this.applyDraftState(this.data.routeDraft.actions, null, {
        pendingSaveLocked: false,
        requestStatus: 'idle',
        saveError: '',
        statusText: '没有找到待确认的保存，请重新保存',
        errorMessage: '',
      })
      return
    }
    this.submitPendingSave(payload)
  },

  onTapAbandonPendingSave: function () {
    if (this.data.saving || this.data.requestStatus === 'saving') return
    var that = this
    var abandon = function () {
      clearPendingSave()
      that.applyDraftState(that.data.routeDraft.actions, null, {
        pendingSaveLocked: false,
        requestStatus: 'idle',
        saveError: '',
        statusText: '已放弃确认；再次保存会创建一个新请求',
        errorMessage: '',
      })
    }
    if (typeof wx.showModal !== 'function') {
      abandon()
      return
    }
    wx.showModal({
      title: '放弃确认上次保存？',
      content: '上次路线可能已经保存。继续编辑后再次保存，可能在路书里看到两条路线。',
      confirmText: '仍要放弃',
      success: function (result) {
        if (result && result.confirm) abandon()
      },
    })
  },

  refreshExpiredRouteParts: function (payload) {
    var that = this
    clearPendingSave()
    this.applyDraftState(this.data.routeDraft.actions, null, {
      saving: false,
      pendingSaveLocked: true,
      requestStatus: 'previewing',
      saveError: '',
      statusText: '智能贴路信息已过期，正在重新贴路',
      errorMessage: '',
      canSaveRoute: false,
    })
    refreshActionsFromRouteParts(payload.route_parts, api.snapManualDrawnRoute).then(function (actions) {
      that.applyDraftState(actions, null, {
        routeName: payload.name,
        saving: false,
        pendingSaveLocked: false,
        requestStatus: 'idle',
        saveError: '',
        statusText: '智能贴路已刷新，请检查路线后重新保存',
        errorMessage: '',
      })
      wx.showToast({ title: '贴路已刷新，请重新保存', icon: 'none' })
    }).catch(function () {
      that.applyDraftState(that.data.routeDraft.actions, null, {
        saving: false,
        pendingSaveLocked: false,
        requestStatus: 'error',
        saveError: '旧贴路信息已失效',
        statusText: '旧贴路信息已失效，请重新画这段路线',
        errorMessage: '路线没有保存；请撤回失效的贴路段后重新贴路。',
      })
      wx.showToast({ title: '请重新贴路后保存', icon: 'none' })
    })
  },

  submitPendingSave: function (payload) {
    var normalizedPayload = normalizePendingSavePayload(payload)
    if (!normalizedPayload) {
      clearPendingSave()
      this.applyDraftState(this.data.routeDraft.actions, null, {
        saving: false,
        pendingSaveLocked: false,
        requestStatus: 'idle',
        saveError: '',
        statusText: '待确认的保存数据已损坏，请重新保存',
        errorMessage: '',
      })
      wx.showToast({ title: '待确认的保存数据已损坏，请重新保存', icon: 'none' })
      return
    }
    var that = this
    var confirmingUnknown = this.data.requestStatus === 'unknown'
    this.applyDraftState(this.data.routeDraft.actions, null, {
      saving: true,
      pendingSaveLocked: true,
      requestStatus: 'saving',
      savedRouteBookId: null,
      saveError: '',
      statusText: '正在保存路线',
      canSaveRoute: false,
    })
    var requestPayload = normalizedPayload
    if (normalizedPayload.route_parts) {
      requestPayload = Object.assign({}, normalizedPayload, {
        route_parts: routePartsForRequest(normalizedPayload.route_parts),
      })
    }
    api.createRouteBookFromManualDrawn(requestPayload).then(function (route) {
      var routeBookId = route && (route.route_book_id || route.id)
      if (!routeBookId) {
        that.applyDraftState(that.data.routeDraft.actions, null, {
          saving: false,
          requestStatus: 'unknown',
          saveError: '保存结果不确定，请不要重复保存',
          statusText: '保存结果不确定，请到我的路书确认',
          errorMessage: '服务没有返回路线编号，请不要重复保存。',
          canSaveRoute: false,
        })
        wx.showToast({ title: '保存结果不确定，请先确认', icon: 'none' })
        return
      }
      clearPendingSave()
      that.applyDraftState(that.data.routeDraft.actions, null, {
        saving: false,
        requestStatus: 'saved',
        savedRouteBookId: routeBookId,
        saveError: '',
        statusText: '路线已保存，正在打开详情',
        errorMessage: '',
        canSaveRoute: false,
      })
      that.openSavedRouteDetail(routeBookId)
    }, function (err) {
      var code = Number(err && err.code)
      if (isRoutingReceiptError(err)) {
        that.refreshExpiredRouteParts(normalizedPayload)
        return
      }
      if (code === -1 || code >= 500 || (confirmingUnknown && code !== 409 && code !== 410)) {
        that.applyDraftState(that.data.routeDraft.actions, null, {
          saving: false,
          requestStatus: 'unknown',
          saveError: '保存结果不确定，请不要重复保存',
          statusText: '保存结果不确定，请到我的路书确认',
          errorMessage: '这次仍没确认到结果，路线可能已经保存。请继续用同一个请求确认。',
          canSaveRoute: false,
        })
        wx.showToast({ title: '保存结果不确定，请先确认', icon: 'none' })
        return
      }
      clearPendingSave()
      var message = saveErrorMessage(err)
      that.applyDraftState(that.data.routeDraft.actions, null, {
        saving: false,
        pendingSaveLocked: false,
        requestStatus: 'error',
        saveError: message,
        statusText: message,
        errorMessage: message,
      })
      wx.showToast({ title: message, icon: 'none' })
    })
  },

  markSavedNavigationFailure: function (routeBookId) {
    this.applyDraftState(this.data.routeDraft.actions, null, {
      saving: false,
      requestStatus: 'saved',
      savedRouteBookId: routeBookId,
      saveError: '',
      statusText: '路线已保存，但详情页没有打开',
      errorMessage: '路线已经保存，请点“打开已保存路线”继续。',
      canSaveRoute: false,
    })
    wx.showToast({ title: '路线已保存，请重试打开', icon: 'none' })
  },

  openSavedRouteDetail: function (routeBookId) {
    var that = this
    var url = '/pages/route-book-detail/route-book-detail?id=' + encodeURIComponent(routeBookId)
    var markFailure = function () { that.markSavedNavigationFailure(routeBookId) }
    wx.redirectTo({
      url: url,
      fail: function () {
        if (typeof wx.navigateTo !== 'function') {
          markFailure()
          return
        }
        wx.navigateTo({ url: url, fail: markFailure })
      },
    })
  },

  onTapOpenSavedRoute: function () {
    if (!this.data.savedRouteBookId) return
    this.openSavedRouteDetail(this.data.savedRouteBookId)
  },

  onTapGoLogin: function () {
    wx.switchTab({ url: '/pages/profile/profile' })
  },
})

if (typeof module !== 'undefined') {
  module.exports = {
    buildDrawPolylines: buildDrawPolylines,
    buildRouteStats: buildRouteStats,
    simplifyForSave: simplifyForSave,
    simplifyForSnap: simplifyForSnap,
    buildDrawMetadata: buildDrawMetadata,
    buildRouteParts: buildRouteParts,
    routePartsForRequest: routePartsForRequest,
    refreshActionsFromRouteParts: refreshActionsFromRouteParts,
    isRoutingReceiptError: isRoutingReceiptError,
    mergeSegments: mergeSegments,
    newClientRequestId: newClientRequestId,
    normalizePendingSavePayload: normalizePendingSavePayload,
    persistPendingSave: persistPendingSave,
    saveErrorMessage: saveErrorMessage,
    snapErrorMessage: snapErrorMessage,
  }
}
