const api = require('../../utils/api')

const DEFAULT_CENTER = { latitude: 37.8706, longitude: 112.5489 }
const MAX_SNAP_POINTS = 120
const TARGET_SAVE_POINTS = 500
const MAX_SAVE_POINTS = 5000
const MAX_DISPLAY_POINTS = 500
const TOUCH_SAMPLE_INTERVAL_MS = 32
const TOUCH_SAMPLE_DISTANCE_PX = 6
const SKETCH_RENDER_EVERY_POINTS = 4
const SKETCH_AUTO_FINISH_MS = 900
const SKETCH_PREPARE_TIMEOUT_MS = 800
const ELEVATION_PREVIEW_DEBOUNCE_MS = 800
const MAP_TAP_SUPPRESSION_MS = 450
const SNAP_COLOR = '#FC4C02'
const RAW_COLOR = '#FC4C02'
const PREVIEW_COLOR = '#8E8E93'
const PENDING_SAVE_STORAGE_PREFIX = 'route_draw_pending_save_v1:'
const MAX_PENDING_SAVE_BYTES = 256 * 1024

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
      width: 7,
      borderColor: '#FFFFFF',
      borderWidth: 2,
      dottedLine: false,
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

function normalizeElevationPreview(value) {
  if (!value || typeof value !== 'object') return null
  var climbM = Number(value.climb_m)
  var descentM = Number(value.descent_m)
  var profile = []
  ;(Array.isArray(value.elevation_profile) ? value.elevation_profile : []).forEach(function (point) {
    if (!Array.isArray(point) || point.length < 2) return
    var distanceKm = Number(point[0])
    var elevationM = Number(point[1])
    if (Number.isFinite(distanceKm) && Number.isFinite(elevationM)) profile.push([distanceKm, elevationM])
  })
  if (!Number.isFinite(climbM) || !Number.isFinite(descentM) || profile.length < 2) return null
  return {
    climb_m: climbM,
    descent_m: descentM,
    elevation_profile: profile,
  }
}

function geometryKey(points) {
  return normalizeLonLatPoints(points).map(function (point) {
    return point[0].toFixed(6) + ',' + point[1].toFixed(6)
  }).join(';')
}

function buildRouteStats(points, elevationPreview, elevationStatus) {
  var normalized = normalizeLonLatPoints(points)
  var distanceM = distanceOf(normalized)
  var km = distanceM / 1000
  var estimatedMinutes = distanceM > 0 ? Math.max(1, Math.round(distanceM / 1000 / 20 * 60)) : 0
  var preview = normalizeElevationPreview(elevationPreview)
  var climbText = '—'
  if (normalized.length >= 2 && elevationStatus === 'loading') climbText = '计算中'
  if (normalized.length >= 2 && elevationStatus === 'error') climbText = '待重试'
  if (preview && elevationStatus === 'ready') climbText = Math.round(preview.climb_m) + ' m'
  var etaText = '0 分钟'
  if (estimatedMinutes >= 60) {
    etaText = Math.floor(estimatedMinutes / 60) + ' 小时 ' + (estimatedMinutes % 60) + ' 分钟'
  } else if (estimatedMinutes > 0) {
    etaText = estimatedMinutes + ' 分钟'
  }
  return {
    distanceM: distanceM,
    distanceText: distanceM > 0 ? (km >= 10 ? km.toFixed(1) : km.toFixed(2)) + ' km' : '0 km',
    pointCount: normalized.length,
    climbText: climbText,
    etaText: etaText,
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

function rdpSimplifyWithBudget(points, limit, toleranceM) {
  var normalized = normalizeLonLatPoints(points)
  if (normalized.length <= 2) {
    return { points: normalized, remainingErrorM: 0 }
  }
  var kept = { 0: true }
  kept[normalized.length - 1] = true
  var candidates = []

  function pushCandidate(start, end) {
    if (end - start <= 1) return
    var maxDistance = -1
    var maxIndex = start
    for (var index = start + 1; index < end; index += 1) {
      var distance = pointDistanceToLine(normalized[index], normalized[start], normalized[end])
      if (distance > maxDistance) {
        maxDistance = distance
        maxIndex = index
      }
    }
    candidates.push({ distance: maxDistance, start: start, end: end, index: maxIndex })
  }

  pushCandidate(0, normalized.length - 1)
  var keptCount = 2
  while (candidates.length && keptCount < limit) {
    var bestPosition = 0
    for (var i = 1; i < candidates.length; i += 1) {
      if (candidates[i].distance > candidates[bestPosition].distance) bestPosition = i
    }
    var best = candidates.splice(bestPosition, 1)[0]
    if (best.distance <= toleranceM) break
    kept[best.index] = true
    keptCount += 1
    pushCandidate(best.start, best.index)
    pushCandidate(best.index, best.end)
  }
  var remainingErrorM = 0
  candidates.forEach(function (candidate) {
    remainingErrorM = Math.max(remainingErrorM, candidate.distance)
  })
  return {
    points: normalized.filter(function (_, index) { return kept[index] }),
    remainingErrorM: remainingErrorM,
  }
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
  if (normalized.length <= TARGET_SAVE_POINTS) return normalized
  var budgeted = rdpSimplifyWithBudget(normalized, TARGET_SAVE_POINTS, 1)
  if (budgeted.remainingErrorM <= 1) return budgeted.points
  return normalized
}

function simplifyForDisplay(points) {
  var simplified = simplifyForSave(points)
  if (simplified.length <= MAX_DISPLAY_POINTS) return simplified
  return samplePoints(simplified, MAX_DISPLAY_POINTS)
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
  var x = finiteNumber(touch.clientX !== undefined ? touch.clientX : touch.x, NaN)
  var y = finiteNumber(touch.clientY !== undefined ? touch.clientY : touch.y, NaN)
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

function mercatorY(latitude) {
  var bounded = Math.max(-85.05112878, Math.min(85.05112878, Number(latitude)))
  var radians = toRadians(bounded)
  return Math.log(Math.tan(Math.PI / 4 + radians / 2))
}

function inverseMercatorY(value) {
  return Math.atan(Math.sinh(value)) * 180 / Math.PI
}

function sketchViewportFromParts(rect, region) {
  var southwest = region && region.southwest
  var northeast = region && region.northeast
  var left = Number(rect && rect.left)
  var top = Number(rect && rect.top)
  var width = Number(rect && rect.width)
  var height = Number(rect && rect.height)
  var west = Number(southwest && southwest.longitude)
  var south = Number(southwest && southwest.latitude)
  var east = Number(northeast && northeast.longitude)
  var north = Number(northeast && northeast.latitude)
  if (![left, top, width, height, west, south, east, north].every(Number.isFinite)) return null
  if (width <= 0 || height <= 0 || east <= west || north <= south) return null
  return {
    left: left,
    top: top,
    width: width,
    height: height,
    west: west,
    east: east,
    southMercator: mercatorY(south),
    northMercator: mercatorY(north),
  }
}

function mapPointFromSketchViewport(screenPoint, viewport) {
  if (!screenPoint || !viewport) return null
  var xRatio = (screenPoint.x - viewport.left) / viewport.width
  var yRatio = (screenPoint.y - viewport.top) / viewport.height
  if (!Number.isFinite(xRatio) || !Number.isFinite(yRatio)) return null
  xRatio = Math.max(0, Math.min(1, xRatio))
  yRatio = Math.max(0, Math.min(1, yRatio))
  var longitude = viewport.west + (viewport.east - viewport.west) * xRatio
  var mercator = viewport.northMercator + (viewport.southMercator - viewport.northMercator) * yRatio
  var latitude = inverseMercatorY(mercator)
  return normalizeLonLatPoint([longitude, latitude])
}

function snapErrorMessage(err) {
  if (err && err.code === -1) return '网络断了，这段没有贴上路，请联网后重试。'
  if (err && err.code === 404) return '贴路服务还没上线，请更新服务后再试。'
  if (err && err.code === 429) return '贴路操作太快，稍等一下再继续。'
  if (err && err.code === 503) return '贴路服务暂时不可用，请稍后重试。'
  if (err && err.code === 422) return '这段附近没有找到合适的路，画短一点再试。'
  if (err && err.code >= 500) return '贴路服务暂时不可用，请稍后重试。'
  return '这一段没有贴好，画短一点再试。'
}

function elevationErrorMessage(err) {
  if (err && (err.code === -1 || err.code === -2)) return '网络恢复后会重新计算海拔。'
  if (err && err.code === 429) return '海拔计算太频繁，稍后会自动重试。'
  if (err && err.code === 503) return '海拔底图正在准备，路线仍可继续编辑。'
  return '暂时没有算出海拔，路线仍可继续编辑。'
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
  return {
    name: name,
    client_request_id: clientRequestId,
    coordinate_system: value.coordinate_system,
    points: points,
    draw_metadata: value.draw_metadata && typeof value.draw_metadata === 'object'
      ? value.draw_metadata
      : null,
  }
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
  if (mode === 'sketch') return '用手指画出你的路线'
  return '规划骑行路线'
}

function modeHelp(mode) {
  if (mode === 'sketch') return '沿确认可骑的道路画线；手绘会保留原线，不再自动绕路。'
  return '直接点地图添加路线点，或使用手绘快速指定走向。'
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
      displayPoints: cloneLonLatPoints(action.displayPoints || action.points),
      warnings: Array.isArray(action.warnings) ? action.warnings.slice(0, 20) : [],
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
    displayPoints: cloneLonLatPoints(pending.displayPoints || pending.previewPoints),
    warnings: Array.isArray(pending.warnings) ? pending.warnings.slice(0, 20) : [],
  }
}

function buildMarkers(actions) {
  var markerPoints = []
  var hasConfirmedSegment = false
  ;(actions || []).forEach(function (action) {
    if (action.kind === 'anchor') {
      markerPoints.push(action.point)
      return
    }
    if (action.kind === 'segment') {
      var points = normalizeLonLatPoints(action.points)
      if (!points.length) return
      if (!hasConfirmedSegment) {
        if (markerPoints.length) markerPoints[0] = points[0]
        else markerPoints.push(points[0])
        hasConfirmedSegment = true
      }
      markerPoints.push(points[points.length - 1])
    }
  })
  return markerPoints.map(function (point, index) {
    var isStart = index === 0
    var isEnd = index === markerPoints.length - 1 && markerPoints.length > 1
    return {
      id: index + 1,
      longitude: point[0],
      latitude: point[1],
      width: 18,
      height: 18,
      label: {
        content: isStart ? '起' : (isEnd ? '终' : String(index + 1)),
        color: isEnd ? '#FFFFFF' : '#FC4C02',
        fontSize: 11,
        fontWeight: 'bold',
        borderRadius: 12,
        bgColor: isEnd ? '#FC4C02' : '#FFFFFF',
        borderColor: '#FC4C02',
        borderWidth: 2,
        padding: 4,
        textAlign: 'center',
        anchorX: -10,
        anchorY: -10,
      },
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
  var displaySegments = []
  var segmentWarnings = []

  safeActions.forEach(function (action) {
    if (action.kind !== 'segment') return
    var segmentPoints = action.points
    if (segmentPoints.length < 2) return
    segments.push(segmentPoints)
    displaySegments.push(action.displayPoints.length >= 2 ? action.displayPoints : segmentPoints)
    modes.push(action.mode)
    rawSegments.push(action.rawPoints)
    segmentWarnings.push(Array.isArray(action.warnings) ? action.warnings.slice(0, 20) : [])
  })

  var confirmedPoints = segments.length ? mergeSegments(segments) : []
  var confirmedDisplayPoints = displaySegments.length ? mergeSegments(displaySegments) : []
  if (!confirmedPoints.length) {
    safeActions.some(function (action) {
      if (action.kind !== 'anchor') return false
      confirmedPoints = [action.point]
      confirmedDisplayPoints = [action.point]
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
    confirmedDisplayPoints: confirmedDisplayPoints,
    pending: safePending,
    currentRawPoints: safePending ? safePending.rawPoints : [],
    previewPoints: safePending ? safePending.displayPoints : [],
    pendingWarnings: safePending ? safePending.warnings : [],
    markers: buildMarkers(safeActions),
  }
}

Page({
  data: {
    notLoggedIn: false,
    gestureSupported: true,
    builderMode: 'smart',
    requestStatus: 'idle',
    statusText: '点地图设置起点',
    modeTitle: modeTitle('smart'),
    modeHelp: modeHelp('smart'),
    errorMessage: '',
    latitude: DEFAULT_CENTER.latitude,
    longitude: DEFAULT_CENTER.longitude,
    mapScrollEnabled: true,
    showSketchLayer: false,
    isSketching: false,
    sketchViewportReady: false,
    actionCount: 0,
    confirmedPointCount: 0,
    markers: [],
    drawPolylines: [],
    routeStats: buildRouteStats([], null, 'idle'),
    elevationStatus: 'idle',
    elevationPreview: null,
    elevationGeometryKey: '',
    elevationMessage: '',
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

  onUnload: function () {
    this.clearSketchAutoFinish()
    this.clearElevationPreviewTimer()
    this._snapSeq = (this._snapSeq || 0) + 1
    this._elevationSeq = (this._elevationSeq || 0) + 1
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
        statusText: '点地图设置起点',
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
    var displayConfirmedPoints = simplifyForDisplay(view.confirmedDisplayPoints)
    this._routeActions = view.actions
    this._routePending = view.pending
    this._confirmedPoints = view.confirmedPoints
    this._displayConfirmedPoints = displayConfirmedPoints
    this._segmentModes = view.modes
    this._rawSegments = view.rawSegments
    this._segmentWarnings = view.segmentWarnings
    var nextRequestStatus = patch.requestStatus !== undefined ? patch.requestStatus : this.data.requestStatus
    var nextBuilderMode = patch.builderMode !== undefined ? patch.builderMode : this.data.builderMode
    var nextSaving = patch.saving !== undefined ? patch.saving : this.data.saving
    var nextSavedRouteBookId = patch.savedRouteBookId !== undefined
      ? patch.savedRouteBookId
      : this.data.savedRouteBookId
    var confirmedGeometryKey = geometryKey(simplifyForSave(view.confirmedPoints))
    var nextElevationStatus = patch.elevationStatus !== undefined
      ? patch.elevationStatus
      : this.data.elevationStatus
    var nextElevationPreview = patch.elevationPreview !== undefined
      ? patch.elevationPreview
      : this.data.elevationPreview
    var nextElevationGeometryKey = patch.elevationGeometryKey !== undefined
      ? patch.elevationGeometryKey
      : this.data.elevationGeometryKey
    var nextElevationMessage = patch.elevationMessage !== undefined
      ? patch.elevationMessage
      : this.data.elevationMessage
    if (!confirmedGeometryKey || nextElevationGeometryKey !== confirmedGeometryKey) {
      nextElevationStatus = 'idle'
      nextElevationPreview = null
      nextElevationGeometryKey = ''
      nextElevationMessage = ''
    }
    var canSaveRoute = (
      view.confirmedPoints.length >= 2 &&
      nextRequestStatus !== 'previewing' &&
      nextRequestStatus !== 'confirming' &&
      nextRequestStatus !== 'saving' &&
      nextRequestStatus !== 'unknown' &&
      nextBuilderMode !== 'sketch' &&
      !nextSaving &&
      !nextSavedRouteBookId
    )

    this.setData(Object.assign({
      actionCount: view.actions.length,
      confirmedPointCount: view.confirmedPoints.length,
      markers: view.markers,
      warnings: flattenWarnings(view.segmentWarnings, view.pendingWarnings),
      drawPolylines: buildDrawPolylines(displayConfirmedPoints, view.currentRawPoints, view.previewPoints),
      routeStats: buildRouteStats(view.confirmedPoints, nextElevationPreview, nextElevationStatus),
      elevationStatus: nextElevationStatus,
      elevationPreview: nextElevationPreview,
      elevationGeometryKey: nextElevationGeometryKey,
      elevationMessage: nextElevationMessage,
      canSaveRoute: canSaveRoute,
    }, patch))
  },

  markGestureUnsupported: function () {
    this.applyDraftState(this._routeActions || [], null, {
      builderMode: 'smart',
      modeTitle: modeTitle('smart'),
      modeHelp: modeHelp('smart'),
      requestStatus: 'error',
      statusText: '地图还没有准备好手绘',
      errorMessage: '可以继续点地图创建路线，或重新点一次手绘。',
      showSketchLayer: false,
      isSketching: false,
      sketchViewportReady: false,
      mapScrollEnabled: true,
    })
  },

  lastConfirmedPoint: function () {
    var points = normalizeLonLatPoints(this._confirmedPoints || [])
    return points.length ? points[points.length - 1] : null
  },

  commitAnchorAction: function (point) {
    this._snapSeq = (this._snapSeq || 0) + 1
    this.cancelElevationPreview()
    var actions = cloneActions(this._routeActions || [])
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
    var actions = cloneActions(this._routeActions || [])
    actions.push({
      kind: 'segment',
      mode: segment.mode === 'freehand' ? 'freehand' : 'snap',
      rawPoints: cloneLonLatPoints(segment.rawPoints || points),
      points: points,
      displayPoints: cloneLonLatPoints(segment.displayPoints || points),
      warnings: Array.isArray(segment.warnings) ? segment.warnings.slice(0, 20) : [],
    })
    this.applyDraftState(actions, null, {
      requestStatus: 'idle',
      statusText: '这一段已接上，继续点地图加路线点',
      errorMessage: '',
    })
    this.scheduleElevationPreview()
  },

  onMapRegionChange: function (event) {
    if (this.data.builderMode === 'sketch') return
    if (!event) return
    var cause = event.causedBy || (event.detail && event.detail.causedBy) || ''
    if (event.type === 'begin') {
      if (!cause || cause === 'gesture' || cause === 'scale') this._mapGestureActive = true
      return
    }
    if (event.type !== 'end') return
    if (this._mapGestureActive || cause === 'gesture' || cause === 'scale') {
      this._suppressMapTapUntil = Date.now() + MAP_TAP_SUPPRESSION_MS
    }
    this._mapGestureActive = false
    if (this.data.requestStatus !== 'idle') return
    this.setData({
      statusText: this.lastConfirmedPoint() ? '点地图添加下一个路线点' : '点地图设置起点',
    })
  },

  onMapTap: function (event) {
    if (this.preventPendingSaveEdit()) return
    if (!this.ensureLoggedIn()) return
    if (this.data.builderMode === 'sketch') return
    if (Date.now() < (this._suppressMapTapUntil || 0)) {
      wx.showToast({ title: '刚才是在移动地图，请再轻点一次加点', icon: 'none' })
      return
    }
    if (this.data.requestStatus === 'previewing') {
      wx.showToast({ title: '等这一段贴好再继续', icon: 'none' })
      return
    }
    if (this.data.requestStatus === 'confirming') {
      wx.showToast({ title: '先处理当前绕行预览', icon: 'none' })
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

    this.startSnapPreview([lastPoint, normalized])
  },

  startSnapPreview: function (rawPoints) {
    if (!this.ensureLoggedIn()) return
    var raw = cloneLonLatPoints(rawPoints)
    if (raw.length < 2) return
    var requestMode = 'snap'

    var that = this
    this.cancelElevationPreview()
    if (this.data.elevationStatus === 'loading') {
      this.applyElevationState({
        elevationStatus: 'idle',
        elevationPreview: null,
        elevationGeometryKey: '',
        elevationMessage: '',
      })
    }
    this._snapSeq = (this._snapSeq || 0) + 1
    var snapSeq = this._snapSeq
    var pending = {
      mode: requestMode,
      rawPoints: raw,
      previewPoints: [],
      displayPoints: [],
      warnings: [],
    }
    this.applyDraftState(this._routeActions || [], pending, {
      requestStatus: 'previewing',
      statusText: requestMode === 'freehand' ? '正在生成手绘路线' : '正在贴到可骑行道路',
      errorMessage: '',
      showSketchLayer: false,
      isSketching: false,
      mapScrollEnabled: true,
    })

    api.snapManualDrawnRoute({
      coordinate_system: 'gcj02',
      mode: requestMode,
      points: simplifyForSnap(raw),
    }).then(function (result) {
      if (snapSeq !== that._snapSeq) return
      var preview = normalizeLonLatPoints(result && result.snapped_points)
      if (preview.length < 2) throw { code: 422 }
      var displayPreview = normalizeLonLatPoints(result && result.display_points)
      if (displayPreview.length < 2) displayPreview = simplifyForDisplay(preview)
      var warnings = (result && Array.isArray(result.warnings)) ? result.warnings : []
      if (requestMode === 'snap' && result && result.requires_confirmation) {
        that.applyDraftState(that._routeActions || [], {
          mode: 'snap',
          rawPoints: raw,
          previewPoints: preview,
          displayPoints: displayPreview,
          warnings: warnings,
        }, {
          requestStatus: 'confirming',
          statusText: '这两个点很近，但路线绕得很远',
          errorMessage: '可接受腾讯规划的绕行，或手绘这一小段。',
          showSketchLayer: false,
          isSketching: false,
          mapScrollEnabled: true,
        })
        return
      }
      that.commitSegmentAction({
        mode: requestMode,
        rawPoints: raw,
        points: preview,
        displayPoints: displayPreview,
        warnings: warnings,
      })
    }).catch(function (err) {
      if (snapSeq !== that._snapSeq) return
      var message = snapErrorMessage(err)
      that.applyDraftState(that._routeActions || [], {
        mode: requestMode,
        rawPoints: raw,
        previewPoints: [],
        displayPoints: [],
        warnings: [],
      }, {
        requestStatus: 'error',
        statusText: message,
        errorMessage: message,
        showSketchLayer: false,
        isSketching: false,
        mapScrollEnabled: true,
      })
      if ((that._confirmedPoints || []).length >= 2) that.scheduleElevationPreview()
    })
  },

  onTapAcceptDetour: function () {
    if (this.data.requestStatus !== 'confirming' || !this._routePending) return
    var pending = clonePending(this._routePending)
    if (!pending || pending.previewPoints.length < 2) return
    this.commitSegmentAction({
      mode: 'snap',
      rawPoints: pending.rawPoints,
      points: pending.previewPoints,
      displayPoints: pending.displayPoints,
      warnings: pending.warnings,
    })
  },

  onTapSketchDetour: function () {
    if (this.data.requestStatus !== 'confirming') return
    this.applyDraftState(this._routeActions || [], null, {
      requestStatus: 'idle',
      statusText: '沿确认可骑的道路重新手绘',
      errorMessage: '',
    })
    this.onTapStartSketch()
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
    this._drawSeq = (this._drawSeq || 0) + 1
    this._rawSegmentPoints = []
    this._sketchViewport = null
    this.applyDraftState(this._routeActions || [], null, {
      builderMode: 'sketch',
      modeTitle: modeTitle('sketch'),
      modeHelp: modeHelp('sketch'),
      requestStatus: 'idle',
      statusText: '正在准备手绘区域',
      errorMessage: '',
      showSketchLayer: true,
      isSketching: false,
      sketchViewportReady: false,
      mapScrollEnabled: false,
    })
    return this.prepareSketchViewport()
  },

  prepareSketchViewport: function () {
    var that = this
    var context = this.mapContext || (typeof wx.createMapContext === 'function' ? wx.createMapContext('route-draw-map', this) : null)
    var prepareSeq = (this._sketchPrepareSeq || 0) + 1
    this._sketchPrepareSeq = prepareSeq
    if (!context || typeof context.getRegion !== 'function' || typeof wx.createSelectorQuery !== 'function') {
      this.markGestureUnsupported()
      return Promise.resolve(false)
    }

    var regionPromise = new Promise(function (resolve, reject) {
      context.getRegion({ success: resolve, fail: reject })
    })
    var rectPromise = new Promise(function (resolve, reject) {
      var query = wx.createSelectorQuery()
      if (query && typeof query.in === 'function') query = query.in(that)
      if (!query || typeof query.select !== 'function') {
        reject(new Error('selector query unavailable'))
        return
      }
      var selected = query.select('#route-draw-map')
      if (!selected || typeof selected.boundingClientRect !== 'function') {
        reject(new Error('map rect unavailable'))
        return
      }
      selected.boundingClientRect(function (rect) {
        if (rect) resolve(rect)
        else reject(new Error('map rect missing'))
      })
      query.exec()
    })

    var preparePromise = Promise.all([rectPromise, regionPromise])
    var timeoutPromise = new Promise(function (_resolve, reject) {
      setTimeout(function () { reject(new Error('sketch viewport timeout')) }, SKETCH_PREPARE_TIMEOUT_MS)
    })
    return Promise.race([preparePromise, timeoutPromise]).then(function (parts) {
      if (prepareSeq !== that._sketchPrepareSeq || that.data.builderMode !== 'sketch') return false
      var viewport = sketchViewportFromParts(parts[0], parts[1])
      if (!viewport) throw new Error('invalid sketch viewport')
      that._sketchViewport = viewport
      that.setData({
        sketchViewportReady: true,
        statusText: '用手指画出你的路线',
      })
      return true
    }).catch(function () {
      if (prepareSeq === that._sketchPrepareSeq && that.data.builderMode === 'sketch') {
        that.markGestureUnsupported()
      }
      return false
    })
  },

  onDrawTouchStart: function (event) {
    if (this.data.pendingSaveLocked) return
    if (!this.ensureLoggedIn()) return
    if (this.data.builderMode !== 'sketch') return
    if (!this.data.gestureSupported || this.data.requestStatus === 'previewing' || this.data.saving) return
    if (!this.data.sketchViewportReady || !this._sketchViewport) {
      wx.showToast({ title: '地图正在准备，稍等一下再画', icon: 'none' })
      this.prepareSketchViewport()
      return
    }

    this.clearSketchAutoFinish()
    this._drawSeq = (this._drawSeq || 0) + 1
    this._rawSegmentPoints = []
    this._lastScreenPoint = null
    this._lastCaptureAt = 0
    this.applyDraftState(this._routeActions || [], null, {
      requestStatus: 'idle',
      statusText: '继续画，松手后自动贴路',
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
    this.finishSketchSegment()
  },

  armSketchAutoFinish: function () {
    var that = this
    this.clearSketchAutoFinish()
    this._sketchAutoFinishTimer = setTimeout(function () {
      that._sketchAutoFinishTimer = null
      if (that.data.builderMode === 'sketch' && that.data.isSketching) that.finishSketchSegment()
    }, SKETCH_AUTO_FINISH_MS)
  },

  clearSketchAutoFinish: function () {
    if (this._sketchAutoFinishTimer === undefined || this._sketchAutoFinishTimer === null) return
    clearTimeout(this._sketchAutoFinishTimer)
    this._sketchAutoFinishTimer = null
  },

  renderSketchInk: function (rawPoints) {
    var raw = cloneLonLatPoints(rawPoints)
    this._routePending = {
      mode: 'freehand',
      rawPoints: raw,
      previewPoints: [],
      warnings: [],
    }
    this.setData({
      drawPolylines: buildDrawPolylines(this._displayConfirmedPoints || [], raw, []),
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
    var point = mapPointFromSketchViewport(screenPoint, this._sketchViewport)
    if (!point) return
    var raw = this._rawSegmentPoints || []
    if (raw.length >= MAX_SNAP_POINTS * 2) return
    if (!raw.length || !samePoint(raw[raw.length - 1], point)) raw.push(point)
    this._rawSegmentPoints = raw
    if (force || raw.length % SKETCH_RENDER_EVERY_POINTS === 0) this.renderSketchInk(raw)
  },

  finishSketchSegment: function () {
    if (!this.ensureLoggedIn()) return
    if (this.data.builderMode !== 'sketch') return
    this.clearSketchAutoFinish()

    var raw = normalizeLonLatPoints(this._rawSegmentPoints || (this._routePending && this._routePending.rawPoints))
    var lastPoint = this.lastConfirmedPoint()
    if (lastPoint && raw.length && !samePoint(lastPoint, raw[0])) {
      raw = [lastPoint].concat(raw)
    }

    if (raw.length < 2 || distanceOf(raw) < 5) {
      this.applyDraftState(this._routeActions || [], null, {
        builderMode: 'sketch',
        modeTitle: modeTitle('sketch'),
        modeHelp: modeHelp('sketch'),
        requestStatus: 'idle',
        statusText: '这段太短了，再画长一点',
        showSketchLayer: true,
        isSketching: false,
        mapScrollEnabled: false,
      })
      return
    }

    this.applyDraftState(this._routeActions || [], null, {
      builderMode: 'smart',
      modeTitle: modeTitle('smart'),
      modeHelp: modeHelp('smart'),
      requestStatus: 'idle',
      showSketchLayer: false,
      isSketching: false,
      sketchViewportReady: false,
      mapScrollEnabled: true,
    })
    this._sketchViewport = null
    this.commitSegmentAction({
      mode: 'freehand',
      rawPoints: raw,
      points: raw,
      displayPoints: simplifyForDisplay(raw),
      warnings: [],
    })
  },

  finishSketchMode: function (text) {
    this.clearSketchAutoFinish()
    this._drawSeq = (this._drawSeq || 0) + 1
    this._sketchPrepareSeq = (this._sketchPrepareSeq || 0) + 1
    this._rawSegmentPoints = []
    this._sketchViewport = null
    this.applyDraftState(this._routeActions || [], null, {
      builderMode: 'smart',
      modeTitle: modeTitle('smart'),
      modeHelp: modeHelp('smart'),
      requestStatus: 'idle',
      statusText: text || '已取消手绘',
      showSketchLayer: false,
      isSketching: false,
      sketchViewportReady: false,
      mapScrollEnabled: true,
    })
  },

  onTapCancelSketch: function () {
    if (this.data.builderMode !== 'sketch') return
    this.finishSketchMode('已取消手绘，可以继续点地图加点')
  },

  onTapUndoAction: function () {
    if (this.preventPendingSaveEdit()) return
    this._snapSeq = (this._snapSeq || 0) + 1
    if (this.data.builderMode === 'sketch') {
      this.finishSketchMode('已退出铅笔手绘')
      return
    }
    var pending = this._routePending
    if (pending) {
      this.applyDraftState(this._routeActions || [], null, {
        requestStatus: 'idle',
        statusText: '已丢弃当前预览',
        errorMessage: '',
        showSketchLayer: false,
        isSketching: false,
        mapScrollEnabled: true,
      })
      if ((this._confirmedPoints || []).length >= 2) this.scheduleElevationPreview()
      return
    }

    var actions = cloneActions(this._routeActions || [])
    if (!actions.length) {
      wx.showToast({ title: '还没有可撤回的动作', icon: 'none' })
      return
    }
    this.cancelElevationPreview()
    actions.pop()
    this.applyDraftState(actions, null, {
      requestStatus: 'idle',
      statusText: actions.length ? '已撤回上一步' : '路线已清空，点地图设置起点',
      errorMessage: '',
    })
    if ((this._confirmedPoints || []).length >= 2) this.scheduleElevationPreview()
  },

  clearElevationPreviewTimer: function () {
    if (this._elevationPreviewTimer === undefined || this._elevationPreviewTimer === null) return
    clearTimeout(this._elevationPreviewTimer)
    this._elevationPreviewTimer = null
  },

  cancelElevationPreview: function () {
    this.clearElevationPreviewTimer()
    this._elevationSeq = (this._elevationSeq || 0) + 1
  },

  rememberElevationPreview: function (key, preview) {
    if (!this._elevationCache) this._elevationCache = {}
    if (!this._elevationCacheOrder) this._elevationCacheOrder = []
    if (!this._elevationCache[key]) this._elevationCacheOrder.push(key)
    this._elevationCache[key] = preview
    while (this._elevationCacheOrder.length > 8) {
      delete this._elevationCache[this._elevationCacheOrder.shift()]
    }
  },

  applyElevationState: function (patch) {
    var next = patch || {}
    var status = next.elevationStatus !== undefined ? next.elevationStatus : this.data.elevationStatus
    var preview = next.elevationPreview !== undefined ? next.elevationPreview : this.data.elevationPreview
    this.setData({
      elevationStatus: status,
      elevationPreview: preview,
      elevationGeometryKey: next.elevationGeometryKey !== undefined
        ? next.elevationGeometryKey
        : this.data.elevationGeometryKey,
      elevationMessage: next.elevationMessage !== undefined
        ? next.elevationMessage
        : this.data.elevationMessage,
      routeStats: buildRouteStats(this._confirmedPoints || [], preview, status),
    })
  },

  scheduleElevationPreview: function () {
    this.clearElevationPreviewTimer()
    this._elevationSeq = (this._elevationSeq || 0) + 1
    var elevationSeq = this._elevationSeq
    var points = simplifyForSave(this._confirmedPoints || [])
    if (points.length < 2) {
      this.applyElevationState({
        elevationStatus: 'idle',
        elevationPreview: null,
        elevationGeometryKey: '',
        elevationMessage: '',
      })
      return
    }
    var key = geometryKey(points)
    var cached = this._elevationCache && this._elevationCache[key]
    if (cached) {
      this.applyElevationState({
        elevationStatus: 'ready',
        elevationPreview: cached,
        elevationGeometryKey: key,
        elevationMessage: '',
      })
      this.drawElevationChartSoon()
      return
    }

    this.applyElevationState({
      elevationStatus: 'loading',
      elevationPreview: null,
      elevationGeometryKey: key,
      elevationMessage: '正在计算爬升与海拔曲线',
    })
    var that = this
    this._elevationPreviewTimer = setTimeout(function () {
      that._elevationPreviewTimer = null
      api.previewManualDrawnElevation({
        coordinate_system: 'gcj02',
        points: points,
      }).then(function (result) {
        if (elevationSeq !== that._elevationSeq || key !== geometryKey(simplifyForSave(that._confirmedPoints || []))) return
        var preview = normalizeElevationPreview(result)
        if (!preview) throw { code: 422 }
        that.rememberElevationPreview(key, preview)
        that.applyElevationState({
          elevationStatus: 'ready',
          elevationPreview: preview,
          elevationGeometryKey: key,
          elevationMessage: '',
        })
        that.drawElevationChartSoon()
      }).catch(function (err) {
        if (elevationSeq !== that._elevationSeq || key !== geometryKey(simplifyForSave(that._confirmedPoints || []))) return
        that.applyElevationState({
          elevationStatus: 'error',
          elevationPreview: null,
          elevationGeometryKey: key,
          elevationMessage: elevationErrorMessage(err),
        })
      })
    }, ELEVATION_PREVIEW_DEBOUNCE_MS)
  },

  onTapRetryElevation: function () {
    if (this.data.elevationStatus !== 'error') return
    this.scheduleElevationPreview()
  },

  drawElevationChartSoon: function () {
    var that = this
    if (typeof wx.nextTick === 'function') {
      wx.nextTick(function () { that.drawElevationChart() })
      return
    }
    setTimeout(function () { that.drawElevationChart() }, 0)
  },

  drawElevationChart: function () {
    var preview = normalizeElevationPreview(this.data.elevationPreview)
    if (!preview || !Array.isArray(preview.elevation_profile) || preview.elevation_profile.length < 2) return
    if (typeof wx.createSelectorQuery !== 'function') return
    var query = wx.createSelectorQuery()
    if (query && typeof query.in === 'function') query = query.in(this)
    if (!query || typeof query.select !== 'function') return
    var selected = query.select('#routeElevationCanvas')
    if (!selected || typeof selected.fields !== 'function') return
    selected.fields({ node: true, size: true }).exec(function (results) {
      var result = results && results[0]
      var canvas = result && result.node
      var width = Number(result && result.width)
      var height = Number(result && result.height)
      if (!canvas || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return
      var context = canvas.getContext('2d')
      var windowInfo = typeof wx.getWindowInfo === 'function'
        ? wx.getWindowInfo()
        : (typeof wx.getSystemInfoSync === 'function' ? wx.getSystemInfoSync() : {})
      var dpr = Math.max(1, Number(windowInfo && windowInfo.pixelRatio) || 1)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      context.scale(dpr, dpr)
      context.clearRect(0, 0, width, height)

      var profile = preview.elevation_profile
      var maxDistance = Math.max(Number(profile[profile.length - 1][0]) || 0, 0.001)
      var values = profile.map(function (point) { return Number(point[1]) })
      var minElevation = Math.min.apply(Math, values)
      var maxElevation = Math.max.apply(Math, values)
      var range = Math.max(maxElevation - minElevation, 1)
      var top = 10
      var bottom = height - 12
      function toX(point) { return Number(point[0]) / maxDistance * width }
      function toY(point) { return bottom - (Number(point[1]) - minElevation) / range * (bottom - top) }

      context.beginPath()
      context.moveTo(toX(profile[0]), bottom)
      profile.forEach(function (point) { context.lineTo(toX(point), toY(point)) })
      context.lineTo(toX(profile[profile.length - 1]), bottom)
      context.closePath()
      context.fillStyle = '#E5E5EA'
      context.fill()

      context.beginPath()
      context.moveTo(toX(profile[0]), toY(profile[0]))
      for (var index = 1; index < profile.length; index += 1) {
        context.lineTo(toX(profile[index]), toY(profile[index]))
      }
      context.strokeStyle = SNAP_COLOR
      context.lineWidth = 3
      context.lineJoin = 'round'
      context.lineCap = 'round'
      context.stroke()
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

  onTapSearchLocation: function () {
    var that = this
    if (typeof wx.chooseLocation !== 'function') {
      wx.showToast({ title: '当前微信版本不支持地点搜索', icon: 'none' })
      return
    }
    wx.chooseLocation({
      success: function (res) {
        var point = normalizeLonLatPoint({ longitude: res.longitude, latitude: res.latitude })
        if (!point) return
        var label = String(res.name || res.address || '该地点').trim()
        that.setData({
          latitude: point[1],
          longitude: point[0],
          statusText: '已找到' + label + '，直接点地图设置路线点',
        })
      },
      fail: function (err) {
        if (err && String(err.errMsg || '').indexOf('cancel') >= 0) return
        wx.showToast({ title: '没有选中地点，再试一次', icon: 'none' })
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
    if (this._routePending) {
      wx.showToast({ title: '先处理当前预览', icon: 'none' })
      return
    }
    var confirmedPoints = normalizeLonLatPoints(this._confirmedPoints || [])
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
      this._segmentModes || [],
      this._rawSegments || [],
      this._segmentWarnings || []
    )
    var payload = {
      name: name,
      client_request_id: newClientRequestId(),
      coordinate_system: 'gcj02',
      points: points,
      draw_metadata: drawMetadata,
    }
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
      this.applyDraftState(this._routeActions || [], null, {
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
      that.applyDraftState(that._routeActions || [], null, {
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

  submitPendingSave: function (payload) {
    var normalizedPayload = normalizePendingSavePayload(payload)
    if (!normalizedPayload) {
      clearPendingSave()
      this.applyDraftState(this._routeActions || [], null, {
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
    this.applyDraftState(this._routeActions || [], null, {
      saving: true,
      pendingSaveLocked: true,
      requestStatus: 'saving',
      savedRouteBookId: null,
      saveError: '',
      statusText: '正在保存路线',
      canSaveRoute: false,
    })
    api.createRouteBookFromManualDrawn(normalizedPayload).then(function (route) {
      var routeBookId = route && (route.route_book_id || route.id)
      if (!routeBookId) {
        that.applyDraftState(that._routeActions || [], null, {
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
      that.applyDraftState(that._routeActions || [], null, {
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
      if (code === -1 || code >= 500 || (confirmingUnknown && code !== 409 && code !== 410)) {
        that.applyDraftState(that._routeActions || [], null, {
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
      that.applyDraftState(that._routeActions || [], null, {
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
    this.applyDraftState(this._routeActions || [], null, {
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
    buildMarkers: buildMarkers,
    buildRouteStats: buildRouteStats,
    geometryKey: geometryKey,
    mapPointFromSketchViewport: mapPointFromSketchViewport,
    normalizeElevationPreview: normalizeElevationPreview,
    sketchViewportFromParts: sketchViewportFromParts,
    simplifyForSave: simplifyForSave,
    simplifyForDisplay: simplifyForDisplay,
    simplifyForSnap: simplifyForSnap,
    buildDrawMetadata: buildDrawMetadata,
    mergeSegments: mergeSegments,
    newClientRequestId: newClientRequestId,
    normalizePendingSavePayload: normalizePendingSavePayload,
    persistPendingSave: persistPendingSave,
    saveErrorMessage: saveErrorMessage,
    snapErrorMessage: snapErrorMessage,
  }
}
