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
var powerZones = require('../../utils/power-zones')

var CHART_COLORS = {
  speed: '#4D83D8',
  power: '#B268E6',
  hr: '#D9504F',
  cadence: '#D14FBA',
  elevation: '#BFC1BB',
  elevationLine: '#A7A9A2',
}

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
    // task-4.6：隐私设置（仅 owner 可见 / 用于初始化抽屉 UI）
    isOwner: false,

    privacyDrawerOpen: false,
    privacyForm: {
      visibility: 'public',
      hide_power: false,
      hide_heartrate: false,
    },
  },

  // 海拔剖面原始数据 — 不放 data 里，因为不需要渲染到模板，
  // 放 data 里会触发不必要的 setData 序列化开销
  elevationData: null,
  chartCursors: null,
  activeChart: null,
  _chartRedrawTimers: null,

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
        // 平均功率 / 心率 / 踏频统一取整：DB 存 Float 但展示层不要小数
        if (data.avg_power != null) data.avg_power = Math.round(data.avg_power)
        if (data.avg_hr != null) data.avg_hr = Math.round(data.avg_hr)
        if (data.avg_cadence != null) data.avg_cadence = Math.round(data.avg_cadence)
        if (data.max_cadence != null) data.max_cadence = Math.round(data.max_cadence)
        // task-7 (sprint9): NP / IF / TSS 取整 / W/kg 后端已 round 2 位 / 不再处理
        if (data.normalized_power != null) data.normalized_power = Math.round(data.normalized_power)
        if (data.intensity_factor != null) data.intensity_factor = data.intensity_factor.toFixed(2)  // 0.85 这种
        if (data.tss != null) data.tss = Math.round(data.tss)
        data.power_zones = powerZones.buildPedalingPowerZones(data.power_zones)
        if (Array.isArray(data.splits)) {
          for (var si = 0; si < data.splits.length; si++) {
            var sp = data.splits[si]
            if (sp.avg_power != null) sp.avg_power = Math.round(sp.avg_power)
            if (sp.avg_hr != null) sp.avg_hr = Math.round(sp.avg_hr)
          }
        }

        // 处理海拔剖面数据
        var eleData = processElevationData(data.simplified_track)
        var maxEle = -Infinity
        for (var i = 0; i < eleData.length; i++) {
          if (eleData[i].elevation > maxEle) maxEle = eleData[i].elevation
        }
        // 如果全部海拔都无效（不应该走到这里，因为 eleData 会是空数组），兜底为 0
        if (maxEle === -Infinity) maxEle = 0
        that.elevationData = eleData

        // task-4.6：判断当前查看者是不是 owner（用于显示隐私设置入口）
        // 优先用 globalData.userId（登录后立刻可用 / 不等 profile tab 激活）
        // 兜底用 globalData.userInfo.id（向后兼容 / 之前已激活 profile 的会话）
        var app = getApp()
        var gd = app.globalData || {}
        var myUserId = gd.userId || (gd.userInfo && gd.userInfo.id) || 0
        var isOwner = !!(myUserId && data.user_id === myUserId)
        var privacy = data.privacy || {}

        that.setData({
          loading: false,
          activity: data,
          // durationText（全程耗时）保留给明细对照行用；头部"时长"label 改用 headerTimeText（移动时间优先 / 老活动 fallback duration）
          // 2026-05-20 Tim 拍：所有"时长"显示统一移动时间语义；明细诊断区保留两值对照不动
          durationText: that.formatDuration(data.duration),
          headerTimeText: that.formatDuration(data.moving_time != null ? data.moving_time : data.duration),
          // 老活动 moving_time 为 NULL 显示 "-"；用 != null 防 truthiness 陷阱（0 视为合法）
          movingTimeText: data.moving_time != null ? that.formatDuration(data.moving_time) : '-',
          dateText: that.formatDate(data.started_at || data.created_at),
          hasElevation: eleData.length > 0,
          maxElevation: formatNum(maxEle),
          elevationGainText: formatNum(data.elevation_gain || 0),
          isOwner: isOwner,
          privacyForm: {
            visibility: privacy.visibility || 'public',
            hide_power: privacy.hide_power === true,
            hide_heartrate: privacy.hide_heartrate === true,
          },
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
    api.get('/api/activities/' + id + '/timeseries?points=1200')
      .then(function (data) {
        if (!data || !data.distances || data.distances.length < 2) return
        that.timeseriesData = data
        that.chartCursors = {}
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

    var chartKeys = ['speed', 'power', 'hr', 'cadence']
    for (var i = 0; i < chartKeys.length; i++) {
      this._drawTimeseriesChart(chartKeys[i])
    }
  },

  _selectorForChart: function (chartKey) {
    var selectors = {
      elevation: '#elevationCanvas',
      speed: '#speedCanvas',
      power: '#powerCanvas',
      hr: '#hrCanvas',
      cadence: '#cadenceCanvas',
    }
    return selectors[chartKey] || ''
  },

  _getTimeseriesChartConfig: function (chartKey) {
    var data = this.timeseriesData
    if (!data) return null

    // 所有曲线图共享海拔背景（灰色剪影，让你一眼看出"慢是因为爬坡"）
    var bgEle = data.elevations
    var configs = {
      speed: {
        selector: '#speedCanvas',
        yData: data.speeds,
        color: CHART_COLORS.speed,
        yUnit: 'km/h',
        smooth: 7,
      },
      power: {
        selector: '#powerCanvas',
        yData: data.powers,
        color: CHART_COLORS.power,
        yUnit: 'W',
        smooth: 5,
      },
      hr: {
        selector: '#hrCanvas',
        yData: data.heart_rates,
        color: CHART_COLORS.hr,
        yUnit: 'bpm',
        smooth: 5,
      },
      cadence: {
        selector: '#cadenceCanvas',
        yData: data.cadences,
        color: CHART_COLORS.cadence,
        yUnit: 'rpm',
        smooth: 5,
      },
    }
    var cfg = configs[chartKey]
    if (!cfg || !cfg.yData) return null
    cfg.xData = data.distances
    cfg.bgElevation = bgEle
    return cfg
  },

  _drawTimeseriesChart: function (chartKey) {
    var cfg = this._getTimeseriesChartConfig(chartKey)
    if (!cfg) return

    var cursorIndex = this.chartCursors && this.chartCursors[chartKey] != null
      ? this.chartCursors[chartKey]
      : null
    bindchart.bindLineChart(this, cfg.selector, {
      xData: cfg.xData,
      yData: cfg.yData,
      color: cfg.color,
      yUnit: cfg.yUnit,
      fill: true,
      smooth: cfg.smooth,
      bgElevation: cfg.bgElevation,
      activeIndex: cursorIndex,
    })
  },

  onChartTouchStart: function (e) {
    this._updateChartCursor(e)
  },

  onChartTouchMove: function (e) {
    this._updateChartCursor(e)
  },

  onChartTouchEnd: function (e) {
    this._updateChartCursor(e)
  },

  _updateChartCursor: function (e) {
    var chartKey = e.currentTarget && e.currentTarget.dataset
      ? e.currentTarget.dataset.chart
      : ''
    var selector = this._selectorForChart(chartKey)
    if (!selector) return

    var touch = (e.touches && e.touches[0]) ||
      (e.changedTouches && e.changedTouches[0])
    if (!touch) return

    var idx = bindchart.getNearestIndexFromTouch(this, selector, touch)
    if (idx == null) return

    this.chartCursors = this.chartCursors || {}
    if (this.chartCursors[chartKey] === idx && this.activeChart === chartKey) return
    this.chartCursors[chartKey] = idx
    this.activeChart = chartKey
    this._scheduleChartRedraw(chartKey, e.type === 'touchstart' || e.type === 'touchend')
  },

  _redrawChartNow: function (chartKey) {
    if (chartKey === 'elevation') {
      this.drawElevationProfile()
    } else {
      this._drawTimeseriesChart(chartKey)
    }
  },

  _scheduleChartRedraw: function (chartKey, immediate) {
    this._chartRedrawTimers = this._chartRedrawTimers || {}
    if (immediate) {
      if (this._chartRedrawTimers[chartKey]) {
        clearTimeout(this._chartRedrawTimers[chartKey])
        this._chartRedrawTimers[chartKey] = null
      }
      this._redrawChartNow(chartKey)
      return
    }

    if (this._chartRedrawTimers[chartKey]) return
    var that = this
    this._chartRedrawTimers[chartKey] = setTimeout(function () {
      that._chartRedrawTimers[chartKey] = null
      that._redrawChartNow(chartKey)
    }, 32)
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
      .fields({ node: true, size: true, rect: true })
      .exec(function (res) {
        if (!res || !res[0] || !res[0].node) return

        var canvas = res[0].node
        var width = res[0].width
        var height = res[0].height
        var left = res[0].left || 0
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
        var pad = { top: 56, right: 16, bottom: 28, left: 44 }
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

        var xData = []
        for (var xi = 0; xi < data.length; xi++) {
          xData.push(data[xi].distance)
        }
        that.__bindchartStates = that.__bindchartStates || {}
        that.__bindchartStates['#elevationCanvas'] = {
          left: left,
          width: width,
          height: height,
          pad: pad,
          chartW: chartW,
          chartH: chartH,
          maxX: maxDist,
          xData: xData,
        }

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
        ctx.fillStyle = CHART_COLORS.elevation
        ctx.fill()

        // ── 4. 画顶部描边线（地形的"轮廓线"） ──
        ctx.beginPath()
        ctx.moveTo(toX(data[0].distance), toY(data[0].elevation))
        for (var i = 1; i < data.length; i++) {
          ctx.lineTo(toX(data[i].distance), toY(data[i].elevation))
        }
        ctx.strokeStyle = CHART_COLORS.elevationLine
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

        var cursorIndex = that.chartCursors && that.chartCursors.elevation != null
          ? that.chartCursors.elevation
          : null
        if (cursorIndex != null) {
          cursorIndex = Math.max(0, Math.min(data.length - 1, cursorIndex))
          var point = data[cursorIndex]
          var cx = toX(point.distance)
          var cy = toY(point.elevation)
          ctx.save()
          ctx.strokeStyle = '#000000'
          ctx.lineWidth = 2
          ctx.beginPath()
          ctx.moveTo(cx, pad.top - 10)
          ctx.lineTo(cx, pad.top + chartH)
          ctx.stroke()

          ctx.fillStyle = '#000000'
          ctx.beginPath()
          ctx.arc(cx, cy, 4.5, 0, Math.PI * 2)
          ctx.fill()

          var valueText = Math.round(point.elevation) + ' m'
          var distanceText = (Math.round(point.distance * 100) / 100).toFixed(2) + ' km'
          var bubbleW = 92
          var bubbleH = 42
          var bubbleX = Math.max(pad.left, Math.min(width - pad.right - bubbleW, cx - bubbleW / 2))
          var bubbleY = 4
          var radius = 6
          ctx.beginPath()
          ctx.moveTo(bubbleX + radius, bubbleY)
          ctx.lineTo(bubbleX + bubbleW - radius, bubbleY)
          ctx.quadraticCurveTo(bubbleX + bubbleW, bubbleY, bubbleX + bubbleW, bubbleY + radius)
          ctx.lineTo(bubbleX + bubbleW, bubbleY + bubbleH - radius)
          ctx.quadraticCurveTo(bubbleX + bubbleW, bubbleY + bubbleH, bubbleX + bubbleW - radius, bubbleY + bubbleH)
          ctx.lineTo(bubbleX + radius, bubbleY + bubbleH)
          ctx.quadraticCurveTo(bubbleX, bubbleY + bubbleH, bubbleX, bubbleY + bubbleH - radius)
          ctx.lineTo(bubbleX, bubbleY + radius)
          ctx.quadraticCurveTo(bubbleX, bubbleY, bubbleX + radius, bubbleY)
          ctx.closePath()
          ctx.fillStyle = CHART_COLORS.elevation
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
   * task-4.6：打开/关闭隐私设置抽屉
   */
  togglePrivacyDrawer: function () {
    this.setData({ privacyDrawerOpen: !this.data.privacyDrawerOpen })
  },

  /**
   * task-4.6：visibility switch 切换 → 调 PATCH endpoint 更新
   * 用 switch 的 detail.value（true=私密 / false=公开）
   */
  onPrivacyVisibilityChange: function (e) {
    var visibility = e.detail.value ? 'private' : 'public'
    this._patchPrivacy({ visibility: visibility }, 'visibility', visibility)
  },

  onPrivacyHidePowerChange: function (e) {
    var value = !!e.detail.value
    this._patchPrivacy({ hide_power: value }, 'hide_power', value)
  },

  onPrivacyHideHeartrateChange: function (e) {
    var value = !!e.detail.value
    this._patchPrivacy({ hide_heartrate: value }, 'hide_heartrate', value)
  },

  /**
   * 内部：发 PATCH 请求 + 成功后更新本地 privacyForm + 重拉 detail 让字段挖空生效
   */
  _patchPrivacy: function (patch, fieldKey, newValue) {
    var that = this
    var activityId = this.activityId
    if (!activityId) return

    api.updateActivityPrivacy(activityId, patch)
      .then(function () {
        // 更新本地 form 状态
        var form = Object.assign({}, that.data.privacyForm)
        form[fieldKey] = newValue
        that.setData({ privacyForm: form })
        wx.showToast({ title: '已保存', icon: 'success', duration: 1000 })
        // 重拉 detail：让 hide_power=true 触发字段挖空（但本人看自己始终完整 / 这步主要为 UI 刷新一致）
        that.fetchDetail(activityId)
        that.fetchTimeseries(activityId)
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '保存失败', icon: 'none' })
        // 回滚 UI：A 审 I1 修——必须创建新对象引用，否则微信 setData 浅比较认为 privacyForm
        // 没变（同一引用）→ 不触发 wxml 重渲染 → switch 卡在新值与服务端不一致
        that.setData({ privacyForm: Object.assign({}, that.data.privacyForm) })
      })
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
