/**
 * 通用折线图绘制工具 — 在微信小程序 Canvas 2D 上画数据曲线。
 *
 * 类比：这是一支"万能画笔"，你告诉它"X 轴是距离、Y 轴是速度、颜色用蓝色"，
 * 它就能在 canvas 上画出一条漂亮的折线图，带网格、标签、可选填充。
 *
 * 使用方式：
 *   var bindchart = require('../../utils/bindchart')
 *   bindchart.bindLineChart(page, '#speedCanvas', {
 *     xData: distances,
 *     yData: speeds,
 *     color: '#5AC8FA',
 *     yUnit: 'km/h',
 *     xUnit: 'km',
 *     fill: true,
 *   })
 *
 * 注意：调用时 canvas 必须已在 DOM 中（放在 setData 回调或 wx.nextTick 里）。
 */

/**
 * 计算"好看的"坐标轴刻度值（和 detail.js 里的 niceScale 相同逻辑）
 */
function niceScale(min, max, targetTicks) {
  var range = max - min
  if (range <= 0) return [min]
  var roughStep = range / targetTicks
  var mag = Math.pow(10, Math.floor(Math.log10(roughStep)))
  var norm = roughStep / mag
  var step
  if (norm <= 1.5) step = 1
  else if (norm <= 3.5) step = 2
  else if (norm <= 7.5) step = 5
  else step = 10
  step *= mag
  var ticks = []
  var start = Math.ceil(min / step) * step
  for (var v = start; v <= max + step * 0.01; v += step) {
    if (ticks.length > 20) break
    ticks.push(Math.round(v * 100) / 100) // 保留两位精度避免浮点误差
  }
  return ticks
}

/**
 * 格式化数字：千位加逗号
 */
function formatNum(n) {
  var s = String(Math.round(n))
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/**
 * 在指定 canvas 上绘制折线图
 *
 * @param {Object} page - 页面实例（用于 createSelectorQuery）
 * @param {string} selector - canvas 的 CSS 选择器（如 '#speedCanvas'）
 * @param {Object} opts - 绘制选项
 * @param {Array<number>} opts.xData - X 轴数据（通常是累计公里数）
 * @param {Array<number|null>} opts.yData - Y 轴数据（速度/功率/心率等）
 * @param {string} opts.color - 线条颜色（如 '#5AC8FA'）
 * @param {string} opts.yUnit - Y 轴单位标签（如 'km/h'）
 * @param {string} [opts.xUnit='km'] - X 轴单位标签
 * @param {boolean} [opts.fill=false] - 是否在线条下方填充半透明色
 */

/**
 * 把 6 位 hex 颜色转为 rgba 字符串（兼容所有微信版本）
 * '#5AC8FA' + 0.1 → 'rgba(90, 200, 250, 0.1)'
 */
function hexToRgba(hex, alpha) {
  var r = parseInt(hex.slice(1, 3), 16)
  var g = parseInt(hex.slice(3, 5), 16)
  var b = parseInt(hex.slice(5, 7), 16)
  return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')'
}

function bindLineChart(page, selector, opts) {
  var xData = opts.xData
  var yData = opts.yData
  var color = opts.color
  var yUnit = opts.yUnit || ''
  var xUnit = opts.xUnit || 'km'
  var fill = opts.fill !== undefined ? opts.fill : false

  // 过滤掉 null 值，找到有效数据的范围
  // 但保留 null 在数组中的位置（画图时跳过 null 点，形成断线效果）
  var validY = []
  for (var i = 0; i < yData.length; i++) {
    if (yData[i] != null) validY.push(yData[i])
  }
  if (validY.length < 2) return // 有效数据不足，不画

  var query = page.createSelectorQuery()
  query.select(selector)
    .fields({ node: true, size: true })
    .exec(function (res) {
      if (!res || !res[0] || !res[0].node) return

      var canvas = res[0].node
      var width = res[0].width
      var height = res[0].height
      var ctx = canvas.getContext('2d')

      // Retina 适配
      var sysInfo = wx.getSystemInfoSync()
      var dpr = sysInfo.pixelRatio
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.scale(dpr, dpr)

      // 清空画布（onShow 重绘时防止半透明填充叠加变深）
      ctx.clearRect(0, 0, width, height)

      // 布局参数
      var pad = { top: 12, right: 16, bottom: 28, left: 44 }
      var chartW = width - pad.left - pad.right
      var chartH = height - pad.top - pad.bottom

      // 数据范围
      var minY = Infinity, maxY = -Infinity
      for (var i = 0; i < validY.length; i++) {
        if (validY[i] < minY) minY = validY[i]
        if (validY[i] > maxY) maxY = validY[i]
      }
      var maxX = xData[xData.length - 1]
      if (maxX <= 0) return

      // Y 轴留余量
      var yRange = maxY - minY
      if (yRange < 1) yRange = 1
      minY = Math.floor((minY - yRange * 0.1) * 10) / 10
      maxY = Math.ceil((maxY + yRange * 0.1) * 10) / 10
      yRange = maxY - minY

      // 坐标转换
      function toX(val) { return pad.left + (val / maxX) * chartW }
      function toY(val) { return pad.top + (1 - (val - minY) / yRange) * chartH }

      // ── 1. 网格线 ──
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.08)'
      ctx.lineWidth = 0.5

      var yTicks = niceScale(minY, maxY, 4)
      for (var t = 0; t < yTicks.length; t++) {
        var y = toY(yTicks[t])
        ctx.beginPath()
        ctx.moveTo(pad.left, y)
        ctx.lineTo(width - pad.right, y)
        ctx.stroke()
      }

      var xTicks = niceScale(0, maxX, 4)
      for (var t = 0; t < xTicks.length; t++) {
        if (xTicks[t] <= 0) continue
        var x = toX(xTicks[t])
        ctx.beginPath()
        ctx.moveTo(x, pad.top)
        ctx.lineTo(x, pad.top + chartH)
        ctx.stroke()
      }

      // ── 2. 边框 ──
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.12)'
      ctx.lineWidth = 0.5
      ctx.strokeRect(pad.left, pad.top, chartW, chartH)

      // ── 3. 收集非 null 的连续线段 ──
      // 遇到 null 就断开，开始新的一段线，这样图表不会连接不存在的数据点
      var segments = []
      var current = []
      for (var i = 0; i < yData.length; i++) {
        if (yData[i] != null && xData[i] != null) {
          current.push({ x: xData[i], y: yData[i] })
        } else {
          if (current.length >= 2) segments.push(current)
          current = []
        }
      }
      if (current.length >= 2) segments.push(current)

      // ── 4. 可选填充 ──
      if (fill) {
        for (var s = 0; s < segments.length; s++) {
          var seg = segments[s]
          ctx.beginPath()
          ctx.moveTo(toX(seg[0].x), toY(seg[0].y))
          for (var j = 1; j < seg.length; j++) {
            ctx.lineTo(toX(seg[j].x), toY(seg[j].y))
          }
          ctx.lineTo(toX(seg[seg.length - 1].x), pad.top + chartH)
          ctx.lineTo(toX(seg[0].x), pad.top + chartH)
          ctx.closePath()
          // 半透明填充，颜色和线条一致但更淡（用 rgba 确保全平台兼容）
          ctx.fillStyle = hexToRgba(color, 0.09)
          ctx.fill()
        }
      }

      // ── 5. 画线条 ──
      for (var s = 0; s < segments.length; s++) {
        var seg = segments[s]
        ctx.beginPath()
        ctx.moveTo(toX(seg[0].x), toY(seg[0].y))
        for (var j = 1; j < seg.length; j++) {
          ctx.lineTo(toX(seg[j].x), toY(seg[j].y))
        }
        ctx.strokeStyle = color
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      // ── 6. 坐标轴标签 ──
      ctx.fillStyle = 'rgba(0, 0, 0, 0.4)'
      ctx.font = '10px -apple-system, sans-serif'

      // Y 轴标签
      ctx.textAlign = 'right'
      ctx.textBaseline = 'middle'
      for (var t = 0; t < yTicks.length; t++) {
        var label = yTicks[t] >= 1000 ? formatNum(yTicks[t]) : String(yTicks[t])
        ctx.fillText(label, pad.left - 6, toY(yTicks[t]))
      }

      // Y 轴单位
      ctx.textAlign = 'left'
      ctx.textBaseline = 'top'
      ctx.fillText(yUnit, 2, pad.top + chartH + 4)

      // X 轴标签
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      for (var t = 0; t < xTicks.length; t++) {
        if (xTicks[t] <= 0) continue
        ctx.fillText(xTicks[t] + ' ' + xUnit, toX(xTicks[t]), pad.top + chartH + 8)
      }
    })
}

module.exports = {
  bindLineChart: bindLineChart,
}
