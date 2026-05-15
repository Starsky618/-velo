/**
 * 骑行详情页 — 一次骑行的"完整报告"
 *
 * 从上传完成页或首页的骑行列表点进来，
 * 通过 URL 参数 ?id=xxx 拿到 activity_id，
 * 再调接口获取完整数据展示。
 *
 * 类比：如果首页是"成绩公告栏"，这里就是"详细成绩单"。
 *
 * 海拔剖面图使用 Canvas 2D 手绘，类比"给这次骑行拍一张地形侧面照"：
 * X 轴是你骑了多少公里，Y 轴是当前海拔，灰色填充区域让你一眼看出
 * 哪段在爬坡、哪段在下坡、哪段是平路。
 */

var api = require('../../utils/api')
var bindchart = require('../../utils/bindchart')

// ────── 纯工具函数（不依赖页面实例，可独立测试） ──────

/**
 * Haversine 公式 — 算地球上两个 GPS 点之间的距离
 *
 * 类比：地球是个球，两点之间贴着球面走的最短路径叫"大圆距离"。
 * Haversine 就是算这个距离的经典公式，在几十公里内精度完全够用。
 *
 * @param {number} lat1 起点纬度（度）
 * @param {number} lon1 起点经度（度）
 * @param {number} lat2 终点纬度（度）
 * @param {number} lon2 终点经度（度）
 * @returns {number} 两点间距离（米）
 */
function haversineDistance(lat1, lon1, lat2, lon2) {
  var R = 6371000 // 地球平均半径，单位米
  var toRad = Math.PI / 180
  var dLat = (lat2 - lat1) * toRad
  var dLon = (lon2 - lon1) * toRad
  var a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2)
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/**
 * 把 simplified_track 转换成海拔剖面数据
 *
 * simplified_track 是后端经 Douglas-Peucker 压缩后的轨迹（约 500-1000 点），
 * 每个点只有 lat/lon/ele。这个函数做两件事：
 * 1. 用 Haversine 逐点累加，算出每个点的"已骑行公里数"
 * 2. 提取海拔值，拼成 [{distance, elevation}] 供 Canvas 绑定
 *
 * 注意：Douglas-Peucker 压缩后点间距不均匀（平路点稀、山路点密），
 * 所以 X 轴必须用真实累计距离，不能用点的序号均匀铺开，否则图形会严重失真。
 *
 * @param {Array} track simplified_track 数组
 * @returns {Array} [{distance: 公里, elevation: 米}]，无有效海拔数据时返回空数组
 */
function processElevationData(track) {
  if (!track || track.length < 2) return []
  var result = []
  var cumDist = 0
  var hasValidEle = false
  for (var i = 0; i < track.length; i++) {
    if (i > 0) {
      cumDist += haversineDistance(
        track[i - 1].lat, track[i - 1].lon,
        track[i].lat, track[i].lon
      )
    }
    var ele = track[i].ele
    // 只要有任何一个点的海拔不为 null/undefined，就认为有有效数据
    // 注意：海拔 0 是合法值（海平面骑行，如上海、荷兰），不能排除
    if (ele != null) hasValidEle = true
    result.push({
      distance: cumDist / 1000,
      elevation: ele != null ? ele : 0
    })
  }
  return hasValidEle ? result : []
}

// niceScale / formatNum 已统一到 bindchart.js，通过 require 复用
var niceScale = bindchart.niceScale
var formatNum = bindchart.formatNum

// ────── 页面逻辑 ──────

Page({
  data: {
    loading: true,
    activity: null,
    durationText: '',
    movingTimeText: '',
    dateText: '',
    // 海拔剖面相关（控制模板渲染）
    hasElevation: false,
    maxElevation: '0',        // 格式化后的字符串（如 "1,491"）
    elevationGainText: '0',   // 格式化后的爬升（如 "1,302"）
    // 途经赛段（从 /api/activities/{id}/segments 获取）
    segments: [],             // 格式化后的赛段列表
    hasSegments: false,
    // 时序数据（从 /api/activities/{id}/timeseries 获取，供绘制曲线图）
    hasTimeseries: false,
    hasPowerChart: false,
    hasHrChart: false,
    hasCadenceChart: false,
  },

  // 海拔剖面原始数据 — 不放 data 里，因为不需要渲染到模板，
  // 放 data 里会触发不必要的 setData 序列化开销
  elevationData: null,

  onLoad: function (options) {
    if (options.id) {
      this.activityId = options.id
      // 三个请求并行发起，互不依赖，谁先回来谁先渲染
      this.fetchDetail(options.id)
      this.fetchSegments(options.id)
      this.fetchTimeseries(options.id)
    }
  },

  // 页面重新显示时重绘所有 Canvas（某些低端机型切走再切回会回收 Canvas 导致白屏）
  onShow: function () {
    var that = this
    wx.nextTick(function () {
      if (that.elevationData && that.elevationData.length > 0) {
        that.drawElevationProfile()
      }
      if (that.timeseriesData) {
        that.bindTimeseriesCharts()
      }
    })
  },

  fetchDetail: function (id) {
    var that = this
    api.get('/api/activities/' + id)
      .then(function (data) {
        // 处理海拔剖面数据
        var eleData = processElevationData(data.simplified_track)
        var maxEle = -Infinity
        for (var i = 0; i < eleData.length; i++) {
          if (eleData[i].elevation > maxEle) maxEle = eleData[i].elevation
        }
        // 如果全部海拔都无效（不应该走到这里，因为 eleData 会是空数组），兜底为 0
        if (maxEle === -Infinity) maxEle = 0
        that.elevationData = eleData

        that.setData({
          loading: false,
          activity: data,
          durationText: that.formatDuration(data.duration),
          // 老活动 moving_time 为 NULL 显示 "-"；用 != null 防 truthiness 陷阱（0 视为合法）
          movingTimeText: data.moving_time != null ? that.formatDuration(data.moving_time) : '-',
          dateText: that.formatDate(data.started_at || data.created_at),
          hasElevation: eleData.length > 0,
          maxElevation: formatNum(maxEle),
          elevationGainText: formatNum(data.elevation_gain || 0),
        }, function () {
          // setData 的回调：此时 DOM 已更新完毕，canvas 元素已在页面上。
          // 额外套一层 wx.nextTick，确保 wx:if 条件渲染的 canvas 节点
          // 真正挂载完毕（某些低端机型 setData 回调略早于 canvas 挂载）
          if (eleData.length > 0) {
            wx.nextTick(function () {
              that.drawElevationProfile()
            })
          }
        })
      })
      .catch(function (err) {
        that.setData({ loading: false })
        wx.showToast({
          title: err.message || '加载失败',
          icon: 'none',
        })
      })
  },

  /**
   * 获取该活动匹配到的赛段成绩
   *
   * 和 fetchDetail 并行发起（在 onLoad 中同时调用），
   * 两个请求互不依赖，谁先回来谁先渲染。
   * 赛段数据来自后端自动匹配，用户无需手动操作。
   */
  fetchSegments: function (id) {
    var that = this
    api.get('/api/activities/' + id + '/segments')
      .then(function (res) {
        var items = (res && Array.isArray(res.items)) ? res.items : []
        if (!items.length) return

        // 预格式化：把秒数转为可读时长，避免在 wxml 模板里做计算
        var formatted = items.map(function (seg) {
          return {
            segment_id: seg.segment_id,
            name: seg.segment_name,
            timeText: that.formatDuration(seg.elapsed_time),
            avgSpeed: seg.avg_speed ? (Math.round(seg.avg_speed * 10) / 10) : null,
            avgPower: seg.avg_power ? Math.round(seg.avg_power) : null,
            rank: seg.rank,
            isPr: seg.is_pr,
          }
        })

        that.setData({
          segments: formatted,
          hasSegments: true,
        })
      })
      .catch(function () {
        // 赛段加载失败不影响主页面，静默忽略
      })
  },

  /**
   * 获取时序数据（速度/功率/心率/踏频的逐点采样）
   *
   * 和 fetchDetail、fetchSegments 并行发起。
   * 数据到达后触发曲线图绘制。
   */
  fetchTimeseries: function (id) {
    var that = this
    api.get('/api/activities/' + id + '/timeseries?points=500')
      .then(function (data) {
        if (!data || !data.distances || data.distances.length < 2) return
        that.timeseriesData = data
        that.setData({
          hasTimeseries: true,
          hasPowerChart: !!data.powers,
          hasHrChart: !!data.heart_rates,
          hasCadenceChart: !!data.cadences,
        }, function () {
          // wx.nextTick 在某些机型上仍早于 canvas 2d node 真正 ready，
          // setTimeout 100ms 兜底等 canvas 节点彻底挂载（用户感知不到）
          setTimeout(function () {
            that.bindTimeseriesCharts()
          }, 100)
        })
      })
      .catch(function () {
        // 时序数据加载失败不影响主页面，静默忽略
      })
  },

  /**
   * 绑制所有时序曲线图
   *
   * 使用通用绘图工具 bindchart.js，传入不同数据和颜色。
   * 每个图表独立一个 canvas，互不干扰。
   */
  bindTimeseriesCharts: function () {
    var data = this.timeseriesData
    if (!data) return

    // 所有曲线图共享海拔背景（灰色剪影，让你一眼看出"慢是因为爬坡"）
    var bgEle = data.elevations

    // 速度曲线（深蓝，平滑窗口 7 消除停车骤降和 GPS 锯齿）
    if (data.speeds) {
      bindchart.bindLineChart(this, '#speedCanvas', {
        xData: data.distances,
        yData: data.speeds,
        color: '#1565C0',
        yUnit: 'km/h',
        fill: true,
        smooth: 7,
        bgElevation: bgEle,
      })
    }

    // 功率曲线（紫色）
    if (data.powers) {
      bindchart.bindLineChart(this, '#powerCanvas', {
        xData: data.distances,
        yData: data.powers,
        color: '#AF52DE',
        yUnit: 'W',
        fill: true,
        smooth: 5,
        bgElevation: bgEle,
      })
    }

    // 心率曲线（红色）
    if (data.heart_rates) {
      bindchart.bindLineChart(this, '#hrCanvas', {
        xData: data.distances,
        yData: data.heart_rates,
        color: '#FF2D55',
        yUnit: 'bpm',
        fill: true,
        smooth: 5,
        bgElevation: bgEle,
      })
    }

    // 踏频曲线（粉红）
    if (data.cadences) {
      bindchart.bindLineChart(this, '#cadenceCanvas', {
        xData: data.distances,
        yData: data.cadences,
        color: '#FF6B9D',
        yUnit: 'rpm',
        fill: true,
        smooth: 5,
        bgElevation: bgEle,
      })
    }
  },

  /**
   * 在 Canvas 上绘制海拔剖面图 — Strava 风格灰色填充面积图
   *
   * 绘制步骤（按画家算法，先画底层再画上层）：
   * 1. 获取 canvas 节点 + 适配 Retina 屏幕分辨率
   * 2. 计算数据范围和坐标映射函数
   * 3. 画网格线（最底层，浅灰色）
   * 4. 画图表边框（矩形框）
   * 5. 画灰色填充面积（地形轮廓的"身体"）
   * 6. 画顶部描边线（地形轮廓的"轮廓线"，让山脊更清晰）
   * 7. 画坐标轴标签（最上层，文字不被遮挡）
   */
  drawElevationProfile: function () {
    var that = this
    var data = this.elevationData
    if (!data || data.length < 2) return

    var query = wx.createSelectorQuery()
    query.select('#elevationCanvas')
      .fields({ node: true, size: true })
      .exec(function (res) {
        if (!res || !res[0] || !res[0].node) return

        var canvas = res[0].node
        var width = res[0].width
        var height = res[0].height
        var ctx = canvas.getContext('2d')

        // ── Retina 适配 ──
        // 微信小程序的 canvas 默认按逻辑像素绘制，Retina 屏幕（dpr=2/3）
        // 需要把 canvas 实际像素放大，再用 scale 缩回来，否则图形会模糊
        var sysInfo = wx.getSystemInfoSync()
        var dpr = sysInfo.pixelRatio
        canvas.width = width * dpr
        canvas.height = height * dpr
        ctx.scale(dpr, dpr)

        // 清空画布（onShow 重绘时防止半透明填充叠加变深）
        ctx.clearRect(0, 0, width, height)

        // ── 布局参数 ──
        // 为坐标轴标签留出空间：左侧放 Y 轴数字，底部放 X 轴数字
        var pad = { top: 12, right: 16, bottom: 28, left: 44 }
        var chartW = width - pad.left - pad.right
        var chartH = height - pad.top - pad.bottom

        // ── 计算数据范围 ──
        var minEle = Infinity
        var maxEle = -Infinity
        var maxDist = data[data.length - 1].distance
        // 所有点坐标完全重合时 maxDist 为 0，无法绘图
        if (maxDist <= 0) return
        for (var i = 0; i < data.length; i++) {
          if (data[i].elevation < minEle) minEle = data[i].elevation
          if (data[i].elevation > maxEle) maxEle = data[i].elevation
        }

        // Y 轴上下各留 10% 余量，让曲线不贴边
        var eleRange = maxEle - minEle
        if (eleRange < 20) eleRange = 20 // 最小范围 20m，避免太平的路线图形退化
        minEle = Math.floor(minEle - eleRange * 0.1)
        maxEle = Math.ceil(maxEle + eleRange * 0.1)
        eleRange = maxEle - minEle

        // 坐标转换函数：数据空间 → 画布像素
        function toX(dist) { return pad.left + (dist / maxDist) * chartW }
        function toY(ele) { return pad.top + (1 - (ele - minEle) / eleRange) * chartH }

        // ── 1. 画网格线（最浅的灰色，不抢主角） ──
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.08)'
        ctx.lineWidth = 0.5

        // Y 轴网格线（水平线，标海拔刻度）
        var yTicks = niceScale(minEle, maxEle, 4)
        for (var t = 0; t < yTicks.length; t++) {
          var y = toY(yTicks[t])
          ctx.beginPath()
          ctx.moveTo(pad.left, y)
          ctx.lineTo(width - pad.right, y)
          ctx.stroke()
        }

        // X 轴网格线（竖线，标距离刻度）
        var xTicks = niceScale(0, maxDist, 4)
        for (var t = 0; t < xTicks.length; t++) {
          if (xTicks[t] <= 0) continue
          var x = toX(xTicks[t])
          ctx.beginPath()
          ctx.moveTo(x, pad.top)
          ctx.lineTo(x, pad.top + chartH)
          ctx.stroke()
        }

        // ── 2. 画图表边框 ──
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.12)'
        ctx.lineWidth = 0.5
        ctx.strokeRect(pad.left, pad.top, chartW, chartH)

        // ── 3. 画灰色填充面积（地形的"身体"） ──
        ctx.beginPath()
        ctx.moveTo(toX(data[0].distance), toY(data[0].elevation))
        for (var i = 1; i < data.length; i++) {
          ctx.lineTo(toX(data[i].distance), toY(data[i].elevation))
        }
        // 封闭路径：从最后一个点垂直下到底部，再水平回到起点底部
        ctx.lineTo(toX(data[data.length - 1].distance), pad.top + chartH)
        ctx.lineTo(toX(data[0].distance), pad.top + chartH)
        ctx.closePath()
        // Strava 的海拔填充是半透明灰色
        ctx.fillStyle = 'rgba(190, 190, 190, 0.5)'
        ctx.fill()

        // ── 4. 画顶部描边线（地形的"轮廓线"） ──
        ctx.beginPath()
        ctx.moveTo(toX(data[0].distance), toY(data[0].elevation))
        for (var i = 1; i < data.length; i++) {
          ctx.lineTo(toX(data[i].distance), toY(data[i].elevation))
        }
        ctx.strokeStyle = 'rgba(150, 150, 150, 0.9)'
        ctx.lineWidth = 1.5
        ctx.stroke()

        // ── 5. 画坐标轴标签（放最后，确保文字不被图形遮挡） ──
        ctx.fillStyle = 'rgba(0, 0, 0, 0.4)'
        ctx.font = '10px -apple-system, sans-serif'

        // Y 轴标签（海拔数值，右对齐贴在图表左侧）
        ctx.textAlign = 'right'
        ctx.textBaseline = 'middle'
        for (var t = 0; t < yTicks.length; t++) {
          var yPos = toY(yTicks[t])
          var label = yTicks[t] >= 1000
            ? formatNum(yTicks[t])
            : String(yTicks[t])
          ctx.fillText(label, pad.left - 6, yPos)
        }

        // "m" 单位标记（左下角，和 Strava 一样）
        ctx.textAlign = 'left'
        ctx.textBaseline = 'top'
        ctx.fillText('m', 4, pad.top + chartH + 4)

        // X 轴标签（距离，居中对齐在竖线下方）
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        for (var t = 0; t < xTicks.length; t++) {
          if (xTicks[t] <= 0) continue
          ctx.fillText(xTicks[t] + ' km', toX(xTicks[t]), pad.top + chartH + 8)
        }
      })
  },

  /**
   * 秒数转为"1:32:14"格式
   */
  formatDuration: function (seconds) {
    if (!seconds) return '0:00'
    var h = Math.floor(seconds / 3600)
    var m = Math.floor((seconds % 3600) / 60)
    var s = seconds % 60
    if (h > 0) {
      return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
    }
    return m + ':' + String(s).padStart(2, '0')
  },

  /**
   * ISO 日期转为"2026-04-14 16:30"格式
   */
  formatDate: function (isoStr) {
    if (!isoStr) return ''
    var d = new Date(isoStr)
    var month = String(d.getMonth() + 1).padStart(2, '0')
    var day = String(d.getDate()).padStart(2, '0')
    var hour = String(d.getHours()).padStart(2, '0')
    var min = String(d.getMinutes()).padStart(2, '0')
    return d.getFullYear() + '-' + month + '-' + day + ' ' + hour + ':' + min
  },

  /**
   * 返回上一页
   */
  goBack: function () {
    wx.navigateBack()
  },

  /**
   * 点击"途经赛段"行：跳赛段详情页（task-4.4 砍 leaderboard 后改向）。
   *
   * 改向历史：原 leaderboard tab 没了；赛段详情和全网排行榜都搬到
   * /pages/segment/segment 页（task-4.5 实施）。
   */
  goSegment: function (e) {
    var id = e.currentTarget.dataset.id
    if (!id) return
    // task-4.4：从骑行详情进 segment 详情时带 from_activity_id，
    // 让赛段页"我的记录"卡显示"本次"行（来自这条 activity 的 effort）
    var url = '/pages/segment/segment?id=' + id
    if (this.activityId) {
      url += '&from_activity_id=' + this.activityId
    }
    wx.navigateTo({ url: url })
  },
})
