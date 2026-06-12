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
    if (Number.isFinite(lon) && Number.isFinite(lat)) {
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

function projectTracks(trackList, width, height, pad) {
  var tracks = []
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  trackList.forEach(function (track) {
    var pts = normalizePoints(track)
    if (pts.length < 2) return
    tracks.push(pts)
    pts.forEach(function (p) {
      if (p.x < minX) minX = p.x
      if (p.x > maxX) maxX = p.x
      if (p.y < minY) minY = p.y
      if (p.y > maxY) maxY = p.y
    })
  })
  if (!tracks.length) return null

  // 纬度方向 1° 的实际距离恒定，经度方向要乘 cos(纬度)——
  // 不修正的话，路线形状会被横向拉胖（纬度越高越明显）。
  var latMid = (minY + maxY) / 2
  var cosLat = Math.cos(latMid * Math.PI / 180)
  var spanX = (maxX - minX) * cosLat
  var spanY = maxY - minY
  if (spanX <= 0 && spanY <= 0) return null

  // 等比缩放装进画布（留 pad 边距），并把形状居中
  var innerW = width - pad * 2
  var innerH = height - pad * 2
  var scale = Math.min(
    spanX > 0 ? innerW / spanX : Infinity,
    spanY > 0 ? innerH / spanY : Infinity
  )
  var drawW = spanX * scale
  var drawH = spanY * scale
  var offsetX = pad + (innerW - drawW) / 2
  var offsetY = pad + (innerH - drawH) / 2

  var toCanvas = function (p) {
    return {
      // 纬度向北增大、canvas 的 y 向下增大，所以 y 轴要翻转
      x: offsetX + (p.x - minX) * cosLat * scale,
      y: offsetY + (maxY - p.y) * scale,
    }
  }

  return {
    tracks: tracks.map(function (track) {
      return track.map(toCanvas)
    }),
  }
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
  var pts = normalizePoints(points)
  if (pts.length < 2) return false

  var width = opts.width || 320
  var height = opts.height || 180
  var pad = opts.lineWidth ? opts.lineWidth * 2 : 4
  var projected = projectTracks([pts], width, height, pad)
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
  var projected = projectTracks(tracks, width, height, opts.pad || 12)
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

module.exports = {
  drawRouteThumb: drawRouteThumb,
  drawHeatmapThumb: drawHeatmapThumb,
  normalizePoints: normalizePoints,
}
