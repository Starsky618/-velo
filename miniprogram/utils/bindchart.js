/**
 * 通用折线图绘制工具 — 在微信小程序 Canvas 2D 上画数据曲线。
 *
 * 类比：这是一支"万能画笔"，你告诉它"X 轴是距离、Y 轴是速度、颜色用蓝色"，
 * 它就能在 canvas 上画出一条漂亮的折线图，带网格、标签、可选填充。
 * 还能在背景叠加灰色海拔剖面，让你一眼看出"这段慢是因为在爬坡"。
 *
 * 使用方式：
 *   var bindchart = require('../../utils/bindchart')
 *   bindchart.bindLineChart(page, '#speedCanvas', {
 *     xData: distances,
 *     yData: speeds,
 *     color: '#5AC8FA',
 *     yUnit: 'km/h',
 *     fill: true,
 *     smooth: 5,                    // 移动平均窗口，消除锯齿
 *     bgElevation: elevationArray,  // 灰色海拔背景叠加
 *     activeIndex: 120,             // 可选：手指当前吸附到第几个点
 *   })
 *
 * 注意：调用时 canvas 必须已在 DOM 中（放在 setData 回调或 wx.nextTick 里）。
 */

// ────── 纯工具函数 ──────

/**
 * 计算"好看的"坐标轴刻度值
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
    ticks.push(Math.round(v * 100) / 100)
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
 * 把 6 位 hex 颜色转为 rgba 字符串（兼容所有微信版本）
 */
function hexToRgba(hex, alpha) {
  var r = parseInt(hex.slice(1, 3), 16)
  var g = parseInt(hex.slice(3, 5), 16)
  var b = parseInt(hex.slice(5, 7), 16)
  return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')'
}

/**
 * 移动窗口平均 — 平滑数据，消除 GPS 噪声和停车骤降造成的锯齿。
 *
 * 类比：你拍了一张有噪点的照片，用"模糊"滤镜让它变平滑。
 * 窗口越大越模糊（趋势清晰但细节丢失），窗口越小越清晰（保留细节但噪声也保留）。
 * 窗口 5-7 对 500 个采样点是好的平衡点。
 *
 * null 值处理：遇到 null 直接保留为 null，不参与平均计算。
 *
 * @param {Array<number|null>} data 原始数据
 * @param {number} windowSize 窗口大小（奇数更好，会自动确保至少为 1）
 * @returns {Array<number|null>} 平滑后的数据（等长）
 */
function smoothData(data, windowSize) {
  if (!windowSize || windowSize <= 1) return data
  var half = Math.floor(windowSize / 2)
  var result = new Array(data.length)
  for (var i = 0; i < data.length; i++) {
    if (data[i] == null) {
      result[i] = null
      continue
    }
    var sum = 0
    var count = 0
    for (var j = i - half; j <= i + half; j++) {
      if (j >= 0 && j < data.length && data[j] != null) {
        sum += data[j]
        count++
      }
    }
    result[i] = count > 0 ? Math.round((sum / count) * 10) / 10 : null
  }
  return result
}

// 缓存设备像素比，避免多个图表重复查询
var _cachedDpr = null
function getDpr() {
  if (!_cachedDpr) _cachedDpr = wx.getSystemInfoSync().pixelRatio
  return _cachedDpr
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function findNearestIndex(xData, targetX) {
  if (!xData || !xData.length) return null
  var left = 0
  var right = xData.length - 1
  while (left < right) {
    var mid = Math.floor((left + right) / 2)
    if (xData[mid] < targetX) left = mid + 1
    else right = mid
  }
  if (left <= 0) return 0
  var prev = left - 1
  return Math.abs(xData[left] - targetX) < Math.abs(xData[prev] - targetX)
    ? left
    : prev
}

function findNearestDrawableIndex(yData, activeIndex) {
  if (!yData || !yData.length) return null
  var idx = clamp(activeIndex, 0, yData.length - 1)
  if (yData[idx] != null) return idx
  for (var offset = 1; offset < yData.length; offset++) {
    var left = idx - offset
    var right = idx + offset
    if (left >= 0 && yData[left] != null) return left
    if (right < yData.length && yData[right] != null) return right
  }
  return null
}

function formatTooltipValue(value, yUnit) {
  if (value == null) return '-'
  if (yUnit === 'W' || yUnit === 'bpm' || yUnit === 'rpm' || yUnit === 'm') {
    return Math.round(value) + ' ' + yUnit
  }
  return (Math.round(value * 10) / 10).toFixed(1) + (yUnit ? ' ' + yUnit : '')
}

function drawRoundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

function drawCursorOverlay(ctx, state, activeIndex) {
  var xData = state.xData
  var yData = state.yData
  var rawYData = state.rawYData || yData
  var idx = findNearestDrawableIndex(yData, activeIndex)
  if (idx == null || xData[idx] == null) return

  var x = state.toX(xData[idx])
  var y = state.toY(yData[idx])
  var pad = state.pad
  var chartH = state.chartH
  var width = state.width
  var color = state.color

  // 竖线像一根透明尺子，告诉用户当前读的是路上的哪一个点。
  ctx.save()
  ctx.strokeStyle = 'rgba(20, 20, 20, 0.55)'
  ctx.lineWidth = 1
  if (ctx.setLineDash) ctx.setLineDash([3, 3])
  ctx.beginPath()
  ctx.moveTo(x, pad.top)
  ctx.lineTo(x, pad.top + chartH)
  ctx.stroke()
  if (ctx.setLineDash) ctx.setLineDash([])

  ctx.fillStyle = '#FFFFFF'
  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.arc(x, y, 4, 0, Math.PI * 2)
  ctx.fill()
  ctx.stroke()

  var valueText = formatTooltipValue(rawYData[idx], state.yUnit)
  var distanceText = (Math.round(xData[idx] * 100) / 100).toFixed(2) + ' km'
  var bubbleW = clamp(Math.max(valueText.length * 7 + 20, 86), 86, 132)
  var bubbleH = 38
  var bubbleX = clamp(x - bubbleW / 2, pad.left, width - pad.right - bubbleW)
  var bubbleY = pad.top + 6

  drawRoundRect(ctx, bubbleX, bubbleY, bubbleW, bubbleH, 6)
  ctx.fillStyle = color
  ctx.fill()
  ctx.fillStyle = '#FFFFFF'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.font = '12px -apple-system, sans-serif'
  ctx.fillText(valueText, bubbleX + bubbleW / 2, bubbleY + 6)
  ctx.font = '10px -apple-system, sans-serif'
  ctx.fillText(distanceText, bubbleX + bubbleW / 2, bubbleY + 22)
  ctx.restore()
}

function getNearestIndexFromTouch(page, selector, touch) {
  if (!page || !selector || !touch || !page.__bindchartStates) return null
  var state = page.__bindchartStates[selector]
  if (!state || !state.xData || !state.xData.length) return null

  if (!state.chartW) return null
  var localX
  if (touch.x != null) {
    // canvas 事件里的 x 已经是“离 canvas 左上角多远”，不能再减 canvas.left。
    // 否则用户点右边，读数会整体被推到左边。
    localX = touch.x
  } else {
    var touchX = touch.clientX != null ? touch.clientX : touch.pageX
    if (touchX == null) return null
    localX = state.left != null ? touchX - state.left : touchX
  }
  localX = clamp(localX, state.pad.left, state.width - state.pad.right)
  var ratio = (localX - state.pad.left) / state.chartW
  var targetX = ratio * state.maxX
  return findNearestIndex(state.xData, targetX)
}

// ────── 主绘图函数 ──────

/**
 * 在指定 canvas 上绘制折线图（可叠加海拔背景）
 *
 * @param {Object} page - 页面实例
 * @param {string} selector - canvas 选择器
 * @param {Object} opts - 绘制选项
 * @param {Array<number>} opts.xData - X 轴数据（累计公里数）
 * @param {Array<number|null>} opts.yData - Y 轴数据
 * @param {string} opts.color - 线条颜色（6 位 hex）
 * @param {string} opts.yUnit - Y 轴单位标签
 * @param {string} [opts.xUnit='km'] - X 轴单位标签
 * @param {boolean} [opts.fill=true] - 是否填充线条下方
 * @param {number} [opts.smooth=0] - 移动平均窗口大小（0=不平滑）
 * @param {Array<number|null>} [opts.bgElevation] - 海拔数据（画灰色背景轮廓）
 * @param {number|null} [opts.activeIndex] - 可选：当前手指吸附的点
 */
function bindLineChart(page, selector, opts) {
  var xData = opts.xData
  var rawYData = opts.yData
  var color = opts.color
  var yUnit = opts.yUnit || ''
  var xUnit = opts.xUnit || 'km'
  var fill = opts.fill !== undefined ? opts.fill : true
  var smoothWindow = opts.smooth || 0
  var bgElevation = opts.bgElevation || null

  // 平滑处理（消除锯齿）
  var yData = smoothWindow > 1 ? smoothData(rawYData, smoothWindow) : rawYData

  // 过滤 null，检查有效数据量
  var validY = []
  for (var i = 0; i < yData.length; i++) {
    if (yData[i] != null) validY.push(yData[i])
  }
  if (validY.length < 2) return

  var query = page.createSelectorQuery()
  query.select(selector)
    .fields({ node: true, size: true, rect: true })
    .exec(function (res) {
      if (!res || !res[0] || !res[0].node) return

      var canvas = res[0].node
      var width = res[0].width
      var height = res[0].height
      var left = res[0].left || 0
      var ctx = canvas.getContext('2d')

      // Retina 适配
      var dpr = getDpr()
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, width, height)

      // 布局参数
      var pad = { top: 12, right: 16, bottom: 28, left: 44 }
      var chartW = width - pad.left - pad.right
      var chartH = height - pad.top - pad.bottom

      // 主数据 Y 轴范围
      var minY = Infinity, maxY = -Infinity
      for (var i = 0; i < validY.length; i++) {
        if (validY[i] < minY) minY = validY[i]
        if (validY[i] > maxY) maxY = validY[i]
      }
      var maxX = xData[xData.length - 1]
      if (maxX <= 0) return

      var yRange = maxY - minY
      if (yRange < 1) yRange = 1
      minY = Math.floor((minY - yRange * 0.1) * 10) / 10
      maxY = Math.ceil((maxY + yRange * 0.1) * 10) / 10
      yRange = maxY - minY

      // 坐标转换
      function toX(val) { return pad.left + (val / maxX) * chartW }
      function toY(val) { return pad.top + (1 - (val - minY) / yRange) * chartH }

      page.__bindchartStates = page.__bindchartStates || {}
      page.__bindchartStates[selector] = {
        left: left,
        width: width,
        height: height,
        pad: pad,
        chartW: chartW,
        chartH: chartH,
        maxX: maxX,
        xData: xData,
        yData: yData,
        rawYData: rawYData,
        yUnit: yUnit,
        color: color,
        toX: toX,
        toY: toY,
      }

      // ── 1. 网格线 ──
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.08)'
      ctx.lineWidth = 0.5

      var yTicks = niceScale(minY, maxY, 4)
      for (var t = 0; t < yTicks.length; t++) {
        ctx.beginPath()
        ctx.moveTo(pad.left, toY(yTicks[t]))
        ctx.lineTo(width - pad.right, toY(yTicks[t]))
        ctx.stroke()
      }

      var xTicks = niceScale(0, maxX, 4)
      for (var t = 0; t < xTicks.length; t++) {
        if (xTicks[t] <= 0) continue
        ctx.beginPath()
        ctx.moveTo(toX(xTicks[t]), pad.top)
        ctx.lineTo(toX(xTicks[t]), pad.top + chartH)
        ctx.stroke()
      }

      // ── 2. 边框 ──
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.12)'
      ctx.lineWidth = 0.5
      ctx.strokeRect(pad.left, pad.top, chartW, chartH)

      // ── 3. 海拔背景叠加（灰色半透明填充，和 Strava 一样） ──
      // 画在网格之上、主数据之下，形成"地形剪影"效果
      if (bgElevation && bgElevation.length === xData.length) {
        // 海拔用自己的 Y 轴范围（不影响主数据的 Y 轴）
        var eleMin = Infinity, eleMax = -Infinity
        for (var i = 0; i < bgElevation.length; i++) {
          var e = bgElevation[i]
          if (e != null) {
            if (e < eleMin) eleMin = e
            if (e > eleMax) eleMax = e
          }
        }
        if (eleMax > eleMin) {
          var eleRange = eleMax - eleMin
          if (eleRange < 20) eleRange = 20
          // 海拔峰值尽量顶到图表上方（仅留 2% 余量），
          // 底部也压缩，让山峰占据更多图表高度，
          // 这样和前景数据（心率/功率等）产生更多交错区域
          eleMin = eleMin - eleRange * 0.02
          eleMax = eleMax + eleRange * 0.02
          eleRange = eleMax - eleMin

          // 海拔的 Y 坐标转换（独立于主数据的 Y 轴）
          function toEleY(ele) {
            return pad.top + (1 - (ele - eleMin) / eleRange) * chartH
          }

          // 画灰色填充面积
          ctx.beginPath()
          var started = false
          var lastValidX = 0
          for (var i = 0; i < bgElevation.length; i++) {
            if (bgElevation[i] == null) continue
            var ex = toX(xData[i])
            var ey = toEleY(bgElevation[i])
            if (!started) {
              ctx.moveTo(ex, ey)
              started = true
            } else {
              ctx.lineTo(ex, ey)
            }
            lastValidX = ex
          }
          // 封闭到底部
          ctx.lineTo(lastValidX, pad.top + chartH)
          ctx.lineTo(toX(xData[0]), pad.top + chartH)
          ctx.closePath()
          ctx.fillStyle = 'rgba(180, 180, 180, 0.45)'
          ctx.fill()
        }
      }

      // ── 4. 收集主数据的连续线段（null 处断开） ──
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

      // ── 5. 主数据填充 ──
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
          ctx.fillStyle = hexToRgba(color, 0.5)
          ctx.fill()
        }
      }

      // ── 6. 主数据线条（不填充时才画描边，填充模式下填充边缘就是视觉边界） ──
      if (!fill) {
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
      }

      // ── 7. 坐标轴标签（最上层） ──
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

      if (opts.activeIndex != null) {
        drawCursorOverlay(ctx, page.__bindchartStates[selector], opts.activeIndex)
      }
    })
}

module.exports = {
  bindLineChart: bindLineChart,
  smoothData: smoothData,
  niceScale: niceScale,
  formatNum: formatNum,
  hexToRgba: hexToRgba,
  getDpr: getDpr,
  getNearestIndexFromTouch: getNearestIndexFromTouch,
}
