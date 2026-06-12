/**
 * 路线轨迹缩略图 —— 在小 canvas 上画"路线的形状"，不画地图底图。
 *
 * 这个文件像一支描图笔：给它一串经纬度点和一块画布，它把路线的形状
 * 等比缩进画布里，画成一条橙色线 + 起终点两个小圆点。
 * 它不是地图（没有街道、没有底图），只回答一个问题："这条路线长什么样？"
 *
 * 为什么用它替代小尺寸 <map>：map 是原生组件，缩成卡片缩略图时
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

/**
 * 在 canvas 上画轨迹缩略线。
 * @param {string} canvasId  旧 API 的 canvas-id
 * @param {Array} points     轨迹点（两种格式见文件头）
 * @param {Object} opts      { width, height: 画布 px 尺寸（= wxss rpx ÷ 2）,
 *                             lineWidth, color, dotR: 起终点圆点半径(0=不画),
 *                             component: 自定义组件内调用时传 this }
 * @returns {boolean} 是否真的画了（点不够时 false，调用方据此隐藏画布）
 */
function drawRouteThumb(canvasId, points, opts) {
  var pts = normalizePoints(points)
  if (pts.length < 2) return false

  var width = opts.width
  var height = opts.height
  var pad = opts.lineWidth ? opts.lineWidth * 2 : 4

  // 求经纬度包围盒
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  pts.forEach(function (p) {
    if (p.x < minX) minX = p.x
    if (p.x > maxX) maxX = p.x
    if (p.y < minY) minY = p.y
    if (p.y > maxY) maxY = p.y
  })

  // 纬度方向 1° 的实际距离恒定，经度方向要乘 cos(纬度)——
  // 不修正的话，路线形状会被横向拉胖（纬度越高越明显）。
  var latMid = (minY + maxY) / 2
  var cosLat = Math.cos(latMid * Math.PI / 180)
  var spanX = (maxX - minX) * cosLat
  var spanY = maxY - minY
  if (spanX <= 0 && spanY <= 0) return false

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

  var ctx = wx.createCanvasContext(canvasId, opts.component)
  var color = opts.color || '#FF9500'
  var lineWidth = opts.lineWidth || 2

  ctx.setLineWidth(lineWidth)
  ctx.setStrokeStyle(color)
  ctx.setLineCap('round')
  ctx.setLineJoin('round')
  ctx.beginPath()
  var first = toCanvas(pts[0])
  ctx.moveTo(first.x, first.y)
  for (var i = 1; i < pts.length; i++) {
    var c = toCanvas(pts[i])
    ctx.lineTo(c.x, c.y)
  }
  ctx.stroke()

  // 起终点圆点：起点橙实心、终点深色实心（一眼分清方向）
  var dotR = opts.dotR === undefined ? lineWidth * 1.6 : opts.dotR
  if (dotR > 0) {
    var last = toCanvas(pts[pts.length - 1])
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

module.exports = {
  drawRouteThumb: drawRouteThumb,
  normalizePoints: normalizePoints,
}
