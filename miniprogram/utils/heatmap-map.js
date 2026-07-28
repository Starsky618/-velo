/**
 * 个人热图地图数据适配。
 *
 * 后端保留 WGS-84 原始坐标；这里统一转换成腾讯地图使用的 GCJ-02，
 * 再生成原生 <map> 的 polyline 图层。重叠的半透明轨迹自然变亮，形成热度。
 */

const { wgs84ToGcj02 } = require('./coords')

const HEATMAP_COLORS = [
  { key: 'orange', label: '橙色', color: '#FF6B00' },
  { key: 'red', label: '红色', color: '#FF174F' },
  { key: 'blue', label: '蓝色', color: '#1677FF' },
  { key: 'purple', label: '紫色', color: '#8E44FF' },
]
const MAX_HEATMAP_POLYLINES = 1000

function colorValue(colorKey, opacityHex) {
  var selected = HEATMAP_COLORS.find(function (item) { return item.key === colorKey })
  return (selected || HEATMAP_COLORS[0]).color + (opacityHex || '52')
}

function normalizeTrack(points) {
  if (!Array.isArray(points)) return []
  var normalized = []
  points.forEach(function (point) {
    if (!Array.isArray(point) || point.length < 2) return
    var longitude = Number(point[0])
    var latitude = Number(point[1])
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return
    if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) return
    normalized.push({ longitude: longitude, latitude: latitude })
  })
  return normalized
}

function distanceKm(a, b) {
  var toRad = Math.PI / 180
  var lat1 = a.latitude * toRad
  var lat2 = b.latitude * toRad
  var dLat = (b.latitude - a.latitude) * toRad
  var dLon = (b.longitude - a.longitude) * toRad
  var sinLat = Math.sin(dLat / 2)
  var sinLon = Math.sin(dLon / 2)
  var h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon
  return 6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)))
}

function trackCenter(points) {
  var bounds = boundsForPoints(points)
  return bounds ? bounds.center : null
}

/**
 * 清掉有“跳出去又跳回来”证据的 GPS 漂点，同时保留合法稀疏长骑。
 * 这沿用旧热图已经覆盖过的判断，避免在真实道路底图上画跨城直线。
 */
function splitTrack(points) {
  if (points.length < 2) return []
  var rawSegments = []
  var current = []
  points.forEach(function (point) {
    if (current.length && distanceKm(current[current.length - 1], point) > 40) {
      rawSegments.push(current)
      current = []
    }
    current.push(point)
  })
  if (current.length) rawSegments.push(current)
  if (rawSegments.length === 1) return [points]

  var drawable = rawSegments.filter(function (segment) { return segment.length >= 2 })
  if (drawable.length <= 1) return [points]

  var groups = []
  drawable.forEach(function (segment) {
    var center = trackCenter(segment)
    var group = groups.find(function (candidate) {
      return distanceKm(center, candidate.center) <= 40
    })
    if (!group) {
      group = { segments: [], center: center }
      groups.push(group)
    }
    var count = group.segments.length
    group.center.longitude = (group.center.longitude * count + center.longitude) / (count + 1)
    group.center.latitude = (group.center.latitude * count + center.latitude) / (count + 1)
    group.segments.push(segment)
  })

  var first = drawable[0]
  var last = drawable[drawable.length - 1]
  var firstGroup = groups.find(function (group) { return group.segments.indexOf(first) >= 0 })
  var lastGroup = groups.find(function (group) { return group.segments.indexOf(last) >= 0 })
  return firstGroup && firstGroup === lastGroup ? firstGroup.segments : drawable
}

function toGcj02(points) {
  return points.map(function (point) {
    var converted = wgs84ToGcj02(point.latitude, point.longitude)
    // setData 会序列化完整键名；5 位小数仍约 1 米，却能砍掉坐标转换产生的冗余尾数。
    return {
      latitude: Math.round(converted[0] * 100000) / 100000,
      longitude: Math.round(converted[1] * 100000) / 100000,
    }
  })
}

function prepareTracks(rawTracks) {
  var prepared = []
  if (!Array.isArray(rawTracks)) return prepared
  rawTracks.forEach(function (track) {
    splitTrack(normalizeTrack(track)).forEach(function (segment) {
      if (segment.length >= 2) prepared.push(toGcj02(segment))
    })
  })
  return prepared
}

/**
 * 在固定点数内保留轨迹形状变化最大的点。
 *
 * 旧客户端兜底按数组下标等间隔抽点；长弯道的顶点若刚好落在采样间隔之间，
 * 地图就会把弯道两端直接连成直线。这里分桶保证整条路线都有覆盖，并在每桶
 * 选偏离相邻连线最远的点。复杂度 O(n)，旧后端意外返回大对象时也不会重新卡住。
 */
function selectShapePoints(points, limit) {
  if (points.length <= limit) return points
  if (limit < 3) return [points[0], points[points.length - 1]].slice(0, limit)

  function localDeviation(index) {
    var left = points[index - 1]
    var point = points[index]
    var right = points[index + 1]
    var cosLatitude = Math.cos(point.latitude * Math.PI / 180)
    var leftX = left.longitude * cosLatitude
    var leftY = left.latitude
    var pointX = point.longitude * cosLatitude
    var pointY = point.latitude
    var rightX = right.longitude * cosLatitude
    var rightY = right.latitude
    var chordX = rightX - leftX
    var chordY = rightY - leftY
    var chordLength = Math.sqrt(chordX * chordX + chordY * chordY)
    if (chordLength <= 1e-12) {
      var loopX = pointX - leftX
      var loopY = pointY - leftY
      return Math.sqrt(loopX * loopX + loopY * loopY)
    }
    return Math.abs(chordX * (pointY - leftY) - chordY * (pointX - leftX)) / chordLength
  }

  var sampled = [points[0]]
  var bucketSize = (points.length - 2) / (limit - 2)

  for (var bucket = 0; bucket < limit - 2; bucket++) {
    var rangeStart = Math.floor(bucket * bucketSize) + 1
    var rangeEnd = Math.min(Math.floor((bucket + 1) * bucketSize) + 1, points.length - 1)
    var bestDeviation = -1
    var bestIndex = rangeStart
    for (var index = rangeStart; index < Math.max(rangeStart + 1, rangeEnd); index++) {
      var deviation = localDeviation(index)
      if (deviation > bestDeviation) {
        bestDeviation = deviation
        bestIndex = index
      }
    }
    sampled.push(points[bestIndex])
  }

  sampled.push(points[points.length - 1])
  return sampled
}

function selectRepresentativeTracks(tracks, limit) {
  if (tracks.length <= limit) return tracks
  var bucketMembers = {}
  tracks.forEach(function (track, trackIndex) {
    var covered = {}
    track.forEach(function (point) {
      var key = Math.floor(point.latitude * 2) + ':' + Math.floor(point.longitude * 2)
      covered[key] = true
    })
    Object.keys(covered).forEach(function (key) {
      if (!bucketMembers[key]) bucketMembers[key] = []
      bucketMembers[key].push(trackIndex)
    })
  })

  var selectedIndexes = []
  var selected = {}
  Object.keys(bucketMembers)
    .sort(function (a, b) { return bucketMembers[a].length - bucketMembers[b].length })
    .some(function (key) {
      var candidate = bucketMembers[key].find(function (trackIndex) {
        return !selected[trackIndex]
      })
      if (candidate === undefined) return false
      selected[candidate] = true
      selectedIndexes.push(candidate)
      return selectedIndexes.length === limit
    })

  for (var index = 0; index < tracks.length && selectedIndexes.length < limit; index++) {
    if (selected[index]) continue
    selected[index] = true
    selectedIndexes.push(index)
  }
  selectedIndexes.sort(function (a, b) { return a - b })
  return selectedIndexes.map(function (index) { return tracks[index] })
}

/**
 * 原生 map 的 polyline 会把全部点复制进渲染层；旧接口返回大对象时，直接 setData
 * 会再次卡住小程序。这里做最后一道客户端 LOD 保险：每条活动至少保留首尾点，
 * 其余预算按原轨迹点数分配，并把折线数锁在 1000 条以内，避免旧缓存仍把
 * 上万条两点折线一次性送入 setData。
 */
function limitTrackPoints(tracks, maxPoints) {
  if (!Number.isFinite(maxPoints) || maxPoints < 2 || tracks.length === 0) return tracks
  var drawable = tracks.filter(function (track) { return track.length >= 2 })
  if (drawable.length > MAX_HEATMAP_POLYLINES) {
    drawable = selectRepresentativeTracks(drawable, MAX_HEATMAP_POLYLINES)
  }
  var total = drawable.reduce(function (sum, track) { return sum + track.length }, 0)
  if (total <= maxPoints) return drawable

  if (drawable.length * 2 > maxPoints) {
    drawable = drawable.slice(0, Math.floor(maxPoints / 2))
  }
  var basePoints = drawable.length * 2
  var extraBudget = Math.max(0, maxPoints - basePoints)
  var totalExtraWeight = drawable.reduce(function (sum, track) {
    return sum + Math.max(0, track.length - 2)
  }, 0)
  var allocations = drawable.map(function (track) {
    var weight = Math.max(0, track.length - 2)
    var exact = totalExtraWeight > 0 ? extraBudget * weight / totalExtraWeight : 0
    return {
      limit: Math.min(track.length, 2 + Math.floor(exact)),
      remainder: exact - Math.floor(exact),
    }
  })
  var used = allocations.reduce(function (sum, item) { return sum + item.limit }, 0)
  var order = allocations.map(function (item, index) {
    return { index: index, remainder: item.remainder }
  }).sort(function (a, b) { return b.remainder - a.remainder })
  var cursor = 0
  while (used < maxPoints && order.length) {
    var target = order[cursor % order.length].index
    if (allocations[target].limit < drawable[target].length) {
      allocations[target].limit += 1
      used += 1
    }
    cursor += 1
    if (cursor > order.length * 2 && allocations.every(function (item, index) {
      return item.limit >= drawable[index].length
    })) break
  }

  return drawable.map(function (track, index) {
    var limit = allocations[index].limit
    if (limit >= track.length) return track
    return selectShapePoints(track, limit)
  })
}

function boundsForPoints(points) {
  if (!Array.isArray(points) || points.length === 0) return null
  var minLat = Infinity
  var maxLat = -Infinity
  var minLon = Infinity
  var maxLon = -Infinity
  points.forEach(function (point) {
    minLat = Math.min(minLat, point.latitude)
    maxLat = Math.max(maxLat, point.latitude)
    minLon = Math.min(minLon, point.longitude)
    maxLon = Math.max(maxLon, point.longitude)
  })
  if (!Number.isFinite(minLat) || !Number.isFinite(minLon)) return null
  if (maxLat - minLat < 0.01) {
    minLat -= 0.005
    maxLat += 0.005
  }
  if (maxLon - minLon < 0.01) {
    minLon -= 0.005
    maxLon += 0.005
  }
  return {
    includePoints: [
      { latitude: minLat, longitude: minLon },
      { latitude: maxLat, longitude: maxLon },
    ],
    center: {
      latitude: (minLat + maxLat) / 2,
      longitude: (minLon + maxLon) / 2,
    },
  }
}

function flattenTracks(tracks) {
  var points = []
  tracks.forEach(function (track) {
    track.forEach(function (point) { points.push(point) })
  })
  return points
}

/** 找出点最密集的 0.5° 网格，并把相邻一圈作为默认“常骑区域”。 */
function focusPointsForTracks(tracks) {
  var allPoints = flattenTracks(tracks)
  if (allPoints.length < 2) return allPoints
  var buckets = {}
  var bestKey = ''
  allPoints.forEach(function (point) {
    var latBucket = Math.floor(point.latitude * 2)
    var lonBucket = Math.floor(point.longitude * 2)
    var key = latBucket + ':' + lonBucket
    if (!buckets[key]) buckets[key] = { count: 0, latBucket: latBucket, lonBucket: lonBucket }
    buckets[key].count += 1
    if (!bestKey || buckets[key].count > buckets[bestKey].count) bestKey = key
  })
  var best = buckets[bestKey]
  var focus = allPoints.filter(function (point) {
    return Math.abs(Math.floor(point.latitude * 2) - best.latBucket) <= 1
      && Math.abs(Math.floor(point.longitude * 2) - best.lonBucket) <= 1
  })
  return focus.length >= 2 ? focus : allPoints
}

function buildPolylines(preparedTracks, colorKey, width, opacityHex) {
  var color = colorValue(colorKey, opacityHex)
  return preparedTracks.map(function (points) {
    return {
      points: points,
      color: color,
      width: width || 2,
      arrowLine: false,
      // 路线在建筑之上、道路文字之下：城市总览仍能读清地名和主干道。
      level: 'abovebuildings',
    }
  })
}

function buildHeatmapMapModel(rawTracks, colorKey, width, maxPoints, opacityHex) {
  var preparedTracks = limitTrackPoints(prepareTracks(rawTracks), maxPoints)
  var allPoints = flattenTracks(preparedTracks)
  var allBounds = boundsForPoints(allPoints)
  var focusBounds = boundsForPoints(focusPointsForTracks(preparedTracks)) || allBounds
  if (!allBounds || !focusBounds) return null
  return {
    preparedTracks: preparedTracks,
    polylines: buildPolylines(preparedTracks, colorKey, width, opacityHex),
    center: focusBounds.center,
    focusPoints: focusBounds.includePoints,
    allPoints: allBounds.includePoints,
  }
}

module.exports = {
  HEATMAP_COLORS: HEATMAP_COLORS,
  buildHeatmapMapModel: buildHeatmapMapModel,
  buildPolylines: buildPolylines,
  limitTrackPoints: limitTrackPoints,
  prepareTracks: prepareTracks,
}
