/**
 * 路线轨迹缩略图 —— 在小 canvas 上画"浅色纸面 + 路线形状"。
 *
 * 这个文件像一支描图笔：给它一串经纬度点和一块画布，它把路线的形状
 * 等比缩进画布里，先铺一层浅色纸面，再画成一条橙色线 + 起终点两个小圆点。
 * 它不是腾讯底图（没有真实街道），只回答一个问题："这条路线长什么样？"
 *
 * 为什么用它替代小尺寸原生地图：map 是原生组件，缩成卡片缩略图时
 * 层级盖普通元素、手势抢滚动、多实例卡顿（约骑编辑页"地图与按键位置冲突"
 * bug 的根源）。canvas 是普通绘制层，彻底没有这些问题。
 *
 * 输入：points —— 两种格式都收：
 *   a) [[lon, lat], ...]            （后端 route_book.preview_points 原始格式）
 *   b) [{latitude, longitude}, ...] （buildRoutePreview 转好的 GCJ 点）
 *   画形状不需要坐标系转换（WGS84/GCJ02 偏移对"形状"无感知），原样可用。
 * 输出：在指定 canvas-id 上完成绘制（旧 canvas API，与路线详情页海拔
 *   缩略图同款，已真机过审）。⚠ wxss 里 canvas 的 rpx 尺寸必须是这里
 *   px 尺寸的 2 倍（rpx:px = 2:1），改一处必须同步另一处。
 */

// 把两种输入格式统一成 [{x: lon, y: lat}]，丢掉非法点
function normalizePoints(points) {
  if (!Array.isArray(points)) return []
  var out = []
  points.forEach(function (p) {
    var lon, lat
    if (Array.isArray(p)) {
      lon = Number(p[0])
      lat = Number(p[1])
    } else if (p && typeof p === 'object') {
      lon = Number(p.longitude)
      lat = Number(p.latitude)
    }
    if (Number.isFinite(lon) && Number.isFinite(lat)
      && lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90) {
      out.push({ x: lon, y: lat })
    }
  })
  return out
}

function drawPaperBackground(ctx, width, height) {
  ctx.clearRect(0, 0, width, height)
  ctx.setFillStyle('#F7F2E8')
  ctx.fillRect(0, 0, width, height)

  // 纸面底纹：很淡的横纵线让卡片像地图纸，但不冒充真实道路。
  ctx.setStrokeStyle('rgba(214, 204, 184, 0.42)')
  ctx.setLineWidth(1)
  for (var x = 18; x < width; x += 42) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x - 10, height)
    ctx.stroke()
  }
  for (var y = 24; y < height; y += 44) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y + 8)
    ctx.stroke()
  }

  // 远景道路感：只做浅灰线，不画真实街道，避免误导用户当导航图看。
  var roads = [
    [{ x: -20, y: height * 0.28 }, { x: width * 0.28, y: height * 0.22 }, { x: width + 20, y: height * 0.34 }],
    [{ x: -15, y: height * 0.72 }, { x: width * 0.44, y: height * 0.62 }, { x: width + 18, y: height * 0.78 }],
    [{ x: width * 0.18, y: -12 }, { x: width * 0.28, y: height * 0.45 }, { x: width * 0.24, y: height + 14 }],
    [{ x: width * 0.72, y: -10 }, { x: width * 0.64, y: height * 0.42 }, { x: width * 0.82, y: height + 12 }],
  ]
  roads.forEach(function (road) {
    ctx.setLineCap('round')
    ctx.setLineJoin('round')
    ctx.setStrokeStyle('rgba(255, 255, 255, 0.82)')
    ctx.setLineWidth(5)
    ctx.beginPath()
    ctx.moveTo(road[0].x, road[0].y)
    ctx.quadraticCurveTo(road[1].x, road[1].y, road[2].x, road[2].y)
    ctx.stroke()
    ctx.setStrokeStyle('rgba(203, 197, 184, 0.55)')
    ctx.setLineWidth(2)
    ctx.beginPath()
    ctx.moveTo(road[0].x, road[0].y)
    ctx.quadraticCurveTo(road[1].x, road[1].y, road[2].x, road[2].y)
    ctx.stroke()
  })
}

function projectNormalizedTracks(tracks, frame, pad) {
  if (!tracks.length) return null
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  tracks.forEach(function (pts) {
    pts.forEach(function (p) {
      if (p.x < minX) minX = p.x
      if (p.x > maxX) maxX = p.x
      if (p.y < minY) minY = p.y
      if (p.y > maxY) maxY = p.y
    })
  })

  var width = frame.width
  var height = frame.height
  var frameX = frame.x || 0
  var frameY = frame.y || 0

  // 纬度方向 1° 的实际距离恒定，经度方向要乘 cos(纬度)——
  // 不修正的话，路线形状会被横向拉胖（纬度越高越明显）。
  var latMid = (minY + maxY) / 2
  var cosLat = Math.cos(latMid * Math.PI / 180)
  var spanX = (maxX - minX) * cosLat
  var spanY = maxY - minY
  if (spanX <= 0 && spanY <= 0) return null

  // 等比缩放装进指定区域（留 pad 边距），并把形状居中
  var innerW = Math.max(1, width - pad * 2)
  var innerH = Math.max(1, height - pad * 2)
  var scale = Math.min(
    spanX > 0 ? innerW / spanX : Infinity,
    spanY > 0 ? innerH / spanY : Infinity
  )
  var drawW = spanX * scale
  var drawH = spanY * scale
  var offsetX = frameX + pad + (innerW - drawW) / 2
  var offsetY = frameY + pad + (innerH - drawH) / 2

  var toCanvas = function (p) {
    return {
      // 纬度向北增大、canvas 的 y 向下增大，所以 y 轴要翻转
      x: offsetX + (p.x - minX) * cosLat * scale,
      y: offsetY + (maxY - p.y) * scale,
    }
  }

  return tracks.map(function (track) {
    return track.map(toCanvas)
  })
}

function projectTracks(trackList, width, height, pad) {
  var tracks = []
  trackList.forEach(function (track) {
    var pts = normalizePoints(track)
    if (pts.length < 2) return
    tracks.push(pts)
  })
  if (!tracks.length) return null
  var projected = projectNormalizedTracks(tracks, { x: 0, y: 0, width: width, height: height }, pad)
  if (!projected) return null
  return {
    tracks: projected,
  }
}

// 相邻点相距过远代表 GPS 漂点或暂停后跨城恢复；不允许一条橙线瞬移，
// 更不能让一个孤立漂点把整张热力图的比例尺拉到全国范围。
function distanceKm(a, b) {
  var toRad = Math.PI / 180
  var lat1 = a.y * toRad
  var lat2 = b.y * toRad
  var dLat = (b.y - a.y) * toRad
  var dLon = (b.x - a.x) * toRad
  var sinLat = Math.sin(dLat / 2)
  var sinLon = Math.sin(dLon / 2)
  var h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon
  return 6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)))
}

function splitHeatmapTrack(points) {
  if (points.length < 2) return []
  var rawSegments = []
  var current = []
  points.forEach(function (point) {
    // 40km 已远大于常规显示预览中正常相邻点的距离。这里只先切候选段；
    // 是否丢弃必须再看“跳出后回到原区域”的证据，不能只凭距离删合法长骑。
    if (current.length && distanceKm(current[current.length - 1], point) > 40) {
      rawSegments.push(current)
      current = []
    }
    current.push(point)
  })
  if (current.length) rawSegments.push(current)
  if (rawSegments.length === 1) return [points]

  var drawable = rawSegments.filter(function (segment) { return segment.length >= 2 })
  // 稀疏长骑可能每个相邻点都超过 40km；没有任何可判断的连续段时必须回退
  // 原轨迹，不能让 4 点/更稀疏的真实活动整条消失。
  if (!drawable.length) return [points]
  // 只有一个连续段、其余为稀疏远端点时，没有“跳出后返回”的证据，可能是
  // 合法长骑的低采样尾段；必须回退原轨迹，不能武断当漂点删除。
  if (drawable.length === 1) return [points]

  // 多个连续段按区域聚类。仅当活动离开某区域后又回到同一区域时，才把中间
  // 的远端 excursion 当漂点丢弃；若首尾属于不同真实区域，则各段都保留。
  var groups = []
  drawable.forEach(function (segment) {
    var center = trackCenter(segment)
    var group = groups.find(function (candidate) {
      return distanceKm(center, candidate.center) <= 40
    })
    if (!group) {
      group = { segments: [], center: center, pointCount: 0 }
      groups.push(group)
    }
    var count = group.segments.length
    group.center.x = (group.center.x * count + center.x) / (count + 1)
    group.center.y = (group.center.y * count + center.y) / (count + 1)
    group.segments.push(segment)
    group.pointCount += segment.length
  })
  var firstSegment = drawable[0]
  var lastSegment = drawable[drawable.length - 1]
  var firstGroup = groups.find(function (group) { return group.segments.indexOf(firstSegment) >= 0 })
  var lastGroup = groups.find(function (group) { return group.segments.indexOf(lastSegment) >= 0 })
  if (firstGroup && firstGroup === lastGroup) return firstGroup.segments
  return drawable
}

function trackCenter(points) {
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  points.forEach(function (point) {
    minX = Math.min(minX, point.x)
    maxX = Math.max(maxX, point.x)
    minY = Math.min(minY, point.y)
    maxY = Math.max(maxY, point.y)
  })
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2 }
}

function buildHeatmapRegions(trackList) {
  var segments = []
  trackList.forEach(function (track, sourceIndex) {
    splitHeatmapTrack(normalizePoints(track)).forEach(function (points) {
      segments.push({ points: points, center: trackCenter(points), sourceIndex: sourceIndex })
    })
  })

  var regions = []
  segments.forEach(function (segment) {
    var best = null
    var bestDistance = Infinity
    regions.forEach(function (region) {
      var km = distanceKm(segment.center, region.center)
      if (km <= 240 && km < bestDistance) {
        best = region
        bestDistance = km
      }
    })
    if (!best) {
      best = { tracks: [], sourceIds: {}, center: { x: segment.center.x, y: segment.center.y }, pointCount: 0 }
      regions.push(best)
    }
    var count = best.tracks.length
    best.center.x = (best.center.x * count + segment.center.x) / (count + 1)
    best.center.y = (best.center.y * count + segment.center.y) / (count + 1)
    best.tracks.push(segment.points)
    best.sourceIds[segment.sourceIndex] = true
    best.pointCount += segment.points.length
  })

  regions.forEach(function (region) {
    region.activityCount = Object.keys(region.sourceIds).length
  })
  regions.sort(function (a, b) {
    return b.activityCount - a.activityCount || b.pointCount - a.pointCount
  })

  return regions
}

function buildRegionFrames(count, width, height) {
  var frames = []
  var gap = 6
  if (count <= 1) return [{ x: 0, y: 0, width: width, height: height }]
  if (count <= 4) {
    var primaryWidth = Math.round(width * 0.67)
    frames.push({ x: 0, y: 0, width: primaryWidth, height: height })
    var sideX = primaryWidth + gap
    var sideWidth = width - sideX
    var sideHeight = (height - gap * (count - 2)) / (count - 1)
    for (var i = 1; i < count; i++) {
      frames.push({
        x: sideX,
        y: (i - 1) * (sideHeight + gap),
        width: sideWidth,
        height: sideHeight,
      })
    }
    return frames
  }

  // 5 个以上区域改用等格网，每个城市仍有自己的比例尺。旧实现把第 4+ 城市
  // 合并到一个小框，深圳/乌鲁木齐会再次被全国跨度压成不到 1px。
  var best = null
  for (var columns = 2; columns <= count; columns++) {
    var rows = Math.ceil(count / columns)
    // 区域很多时缝隙也随单元格缩小，避免固定 6px 把可用宽高扣成负数。
    var gridGap = Math.min(gap, width / columns * 0.12, height / rows * 0.12)
    var cellWidth = (width - gridGap * (columns - 1)) / columns
    var cellHeight = (height - gridGap * (rows - 1)) / rows
    var emptyCells = columns * rows - count
    var score = Math.abs(Math.log(cellWidth / cellHeight)) + emptyCells * 0.15
    if (!best || score < best.score) {
      best = {
        columns: columns, rows: rows, cellWidth: cellWidth, cellHeight: cellHeight,
        gap: gridGap, score: score,
      }
    }
  }
  for (var index = 0; index < count; index++) {
    var column = index % best.columns
    var row = Math.floor(index / best.columns)
    frames.push({
      x: column * (best.cellWidth + best.gap),
      y: row * (best.cellHeight + best.gap),
      width: best.cellWidth,
      height: best.cellHeight,
    })
  }
  return frames
}

function projectHeatmapTracks(trackList, width, height, pad) {
  var regions = buildHeatmapRegions(trackList)
  if (!regions.length) return null
  var frames = buildRegionFrames(regions.length, width, height)
  var projectedTracks = []
  var projectedRegions = []
  regions.forEach(function (region, index) {
    var frame = frames[index]
    var regionPad = Math.min(pad, Math.max(5, Math.min(frame.width, frame.height) * 0.1))
    var tracks = projectNormalizedTracks(region.tracks, frame, regionPad)
    if (!tracks) return
    projectedTracks = projectedTracks.concat(tracks)
    projectedRegions.push({ frame: frame, activityCount: region.activityCount })
  })
  if (!projectedTracks.length) return null
  return { tracks: projectedTracks, regions: projectedRegions }
}

/**
 * 在 canvas 上画轨迹缩略线。
 * @param {string} canvasId  旧 API 的 canvas-id
 * @param {Array} points     轨迹点（两种格式见文件头）
 * @param {Object} opts      { width, height: 画布 px 尺寸（= wxss rpx ÷ 2）,
 *                             lineWidth, color, dotR: 起终点圆点半径(0=不画),
 *                             paper: true 才铺纸面底纹（只给大展示卡用；小缩略图
 *                               铺底纹会糊成一团，且已过审的列表缩略图就是无底纹的样子）,
 *                             component: 自定义组件内调用时传 this }
 * @returns {boolean} 是否真的画了（点不够时 false，调用方据此隐藏画布）
 */
function drawRouteThumb(canvasId, points, opts) {
  opts = opts || {}
  // ⚠ 把"原始点"直接交给 projectTracks，它内部自己做归一化。
  // 不许在这里先 normalizePoints 再传——projectTracks 只认 [lon,lat] / {latitude,longitude}，
  // 预转成 {x,y} 会被它当非法点全部丢弃 → 所有缩略图静默画空白
  // （2026-06-13 全地图白屏事故根因，有 node 桩回归测试锁着）。
  var width = opts.width || 320
  var height = opts.height || 180
  var pad = opts.lineWidth ? opts.lineWidth * 2 : 4
  var projected = projectTracks([points], width, height, pad)
  if (!projected) return false

  var ctx = wx.createCanvasContext(canvasId, opts.component)
  var color = opts.color || '#FF9500'
  var lineWidth = opts.lineWidth || 2
  var drawPoints = projected.tracks[0]

  if (opts.paper === true) {
    drawPaperBackground(ctx, width, height)
  } else {
    ctx.clearRect(0, 0, width, height)
  }

  ctx.setLineWidth(lineWidth)
  ctx.setStrokeStyle(color)
  ctx.setLineCap('round')
  ctx.setLineJoin('round')
  ctx.beginPath()
  var first = drawPoints[0]
  ctx.moveTo(first.x, first.y)
  for (var i = 1; i < drawPoints.length; i++) {
    var c = drawPoints[i]
    ctx.lineTo(c.x, c.y)
  }
  ctx.stroke()

  // 起终点圆点：起点橙实心、终点深色实心（一眼分清方向）
  var dotR = opts.dotR === undefined ? lineWidth * 1.6 : opts.dotR
  if (dotR > 0) {
    var last = drawPoints[drawPoints.length - 1]
    ctx.setFillStyle(color)
    ctx.beginPath()
    ctx.arc(first.x, first.y, dotR, 0, Math.PI * 2)
    ctx.fill()
    ctx.setFillStyle('#1C1C1E')
    ctx.beginPath()
    ctx.arc(last.x, last.y, dotR, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.draw()
  return true
}

function drawHeatmapThumb(canvasId, tracks, opts) {
  opts = opts || {}
  var width = opts.width || 320
  var height = opts.height || 180
  var lineWidth = opts.lineWidth || 2
  var projected = projectHeatmapTracks(tracks, width, height, opts.pad || 12)
  if (!projected) return false

  var ctx = wx.createCanvasContext(canvasId, opts.component)
  drawPaperBackground(ctx, width, height)
  ctx.setLineCap('round')
  ctx.setLineJoin('round')
  ctx.setStrokeStyle(opts.color || 'rgba(255, 149, 0, 0.42)')
  ctx.setLineWidth(lineWidth)

  projected.tracks.forEach(function (track) {
    ctx.beginPath()
    track.forEach(function (point, index) {
      if (index === 0) ctx.moveTo(point.x, point.y)
      else ctx.lineTo(point.x, point.y)
    })
    ctx.stroke()
  })

  ctx.draw()
  return true
}

/**
 * 热力图绘制（新版 Canvas 2D / type="2d"）—— 给"多活动显示精度轨迹"用。
 *
 * 为什么单独写一个：旧版 wx.createCanvasContext + ctx.draw() 在点数过多时
 * （旧个人页热力图曾一次传几十万点）会渲染超时直接白屏。现在服务端按卡片
 * 像素生成轻量预览；新版 Canvas 2D 完整绘制响应中的点，不在客户端二次抽稀。
 *
 * 与旧 drawHeatmapThumb 的区别：
 *   - 旧版：传 canvas-id，内部 createCanvasContext，调用方负责 setData 让 canvas 先存在
 *   - 新版：传 selector（'#xxx'）+ component 实例，内部用 createSelectorQuery 拿真实 node，
 *     自己做 dpr 缩放（高清屏不糊），用标准 ctx.beginPath/moveTo/lineTo/stroke
 *
 * @param {Object} comp     组件实例（this）——createSelectorQuery 要在组件作用域查
 * @param {string} selector canvas 的 id 选择器（如 '#heatmap-canvas'）
 * @param {Array} tracks    多条显示精度轨迹 [[[lon,lat],...], ...]，响应点全部绘制
 * @param {Object} opts     { lineWidth, color }
 */
function drawHeatmap2d(comp, selector, tracks, opts) {
  opts = opts || {}
  if (!Array.isArray(tracks) || tracks.length === 0) return
  var query = comp.createSelectorQuery()
  query.select(selector)
    .fields({ node: true, size: true })
    .exec(function (res) {
      if (!res || !res[0] || !res[0].node) return
      var canvas = res[0].node
      var width = res[0].width
      var height = res[0].height
      if (!width || !height) return

      // 跨城市活动按骑行区域各自投影。旧算法用一个全国比例尺，
      // 北京 + 深圳这类真实数据会把几百条城市路线压成几个像素点。
      var projected = projectHeatmapTracks(tracks, width, height, opts.pad || 12)
      if (!projected) return

      var ctx = canvas.getContext('2d')
      // 高清屏适配：canvas 实际像素按 dpr 放大，再 scale 缩回，否则线条发糊。
      // typeof 守卫让纯 node 单测（无 wx.getSystemInfoSync）也能跑这条路径不炸
      var dpr = (typeof wx !== 'undefined' && wx.getSystemInfoSync
        ? wx.getSystemInfoSync().pixelRatio : 2) || 2
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, width, height)

      // 浅色纸面底（与小缩略图同一支笔，视觉统一）
      drawPaperBackground2d(ctx, width, height)

      if (projected.regions.length > 1) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.36)'
        ctx.strokeStyle = 'rgba(203, 197, 184, 0.58)'
        ctx.lineWidth = 1
        projected.regions.forEach(function (region) {
          var frame = region.frame
          ctx.fillRect(frame.x, frame.y, frame.width, frame.height)
          ctx.strokeRect(frame.x + 0.5, frame.y + 0.5, frame.width - 1, frame.height - 1)
        })
      }

      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.strokeStyle = opts.color || 'rgba(255, 149, 0, 0.42)'
      ctx.lineWidth = opts.lineWidth || 2

      // 逐条轨迹完整画（每个点都画，半透明橙叠加 → 骑得越多越亮的自然热力）
      projected.tracks.forEach(function (track) {
        ctx.beginPath()
        track.forEach(function (point, index) {
          if (index === 0) ctx.moveTo(point.x, point.y)
          else ctx.lineTo(point.x, point.y)
        })
        ctx.stroke()
      })
    })
}

// 新版 Canvas 2D 的纸面底纹（标准 ctx API，对应旧版 drawPaperBackground 的 set* 写法）
function drawPaperBackground2d(ctx, width, height) {
  ctx.fillStyle = '#F7F2E8'
  ctx.fillRect(0, 0, width, height)
  ctx.strokeStyle = 'rgba(214, 204, 184, 0.42)'
  ctx.lineWidth = 1
  for (var x = 18; x < width; x += 42) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x - 10, height)
    ctx.stroke()
  }
  for (var y = 24; y < height; y += 44) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y + 8)
    ctx.stroke()
  }
}

module.exports = {
  drawRouteThumb: drawRouteThumb,
  drawHeatmapThumb: drawHeatmapThumb,
  drawHeatmap2d: drawHeatmap2d,
  normalizePoints: normalizePoints,
  projectHeatmapTracks: projectHeatmapTracks,
}
