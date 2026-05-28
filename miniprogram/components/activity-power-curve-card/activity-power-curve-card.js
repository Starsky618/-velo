/**
 * 单次 activity 功率曲线分析卡片。
 *
 * 这张卡只服务详情页：它不看历史最好成绩，只回答“这一次骑行里，
 * 任意持续时长的最强平均功率是多少”。组件自己请求、自己画图，
 * 详情页只负责把 activityId 递进来，避免 detail.js 继续变胖。
 *
 * 数据流：
 *   activityId → GET /api/activities/{id}/power-curve?points=1000
 *     → setData(visible=true) → setTimeout(100) 画 canvas
 *   手指拖动 → 先吸附到已返回点 → touchend 后 GET /effort?duration_sec=秒
 *     → 气泡更新成精确秒级结果。
 */

const api = require('../../utils/api')

const COLOR = '#8A22E6'
const GRID_COLOR = '#E8E2EE'
const TEXT_MUTED = '#8E8E93'
const TEXT_MAIN = '#1D1D1F'

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function pad2(value) {
  return value < 10 ? '0' + value : '' + value
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

Component({
  properties: {
    activityId: {
      type: Number,
      value: 0,
      observer: function (value) {
        if (this.data._mounted && value) this._fetchSummary()
      },
    },
  },

  data: {
    loading: false,
    error: false,
    visible: false,
    activePowerText: '-- W',
    activeDurationText: '--',
    activeRangeText: '',
    resolutionLabel: '',
    _mounted: false,
  },

  lifetimes: {
    attached: function () {
      this.setData({ _mounted: true })
      if (this.data.activityId) this._fetchSummary()
    },
    detached: function () {
      if (this._redrawTimer) clearTimeout(this._redrawTimer)
    },
  },

  methods: {
    retry: function () {
      this._fetchSummary()
    },

    _fetchSummary: function () {
      const that = this
      const activityId = this.data.activityId
      if (!activityId) return

      this.setData({ loading: true, error: false, visible: false })

      const summaryUrl = '/api/activities/' + activityId + '/power-curve'
      api.get(summaryUrl, { points: 1000 })
        .then(function (data) {
          const rawPoints = data && data.points ? data.points : []
          const points = that._normalizePoints(rawPoints)

          if (!data || data.has_power !== true || points.length < 2) {
            that._points = []
            that.setData({ loading: false, error: false, visible: false })
            return
          }

          that._points = points
          that._maxDurationSec = Number(data.max_duration_sec) || points[points.length - 1].duration_sec
          const initial = that._findNearestPoint(3600) || points[Math.floor(points.length / 2)]
          that._activePoint = initial

          that.setData({
            loading: false,
            error: false,
            visible: true,
            resolutionLabel: data.resolution_label || '',
            activePowerText: that._formatPower(initial.best_power_w),
            activeDurationText: that._formatDuration(initial.duration_sec),
            activeRangeText: that._formatRange(initial.start_sec, initial.end_sec),
          }, function () {
            setTimeout(function () {
              that._renderCanvas()
            }, 100)
          })
        })
        .catch(function () {
          that.setData({ loading: false, error: true, visible: false })
        })
    },

    _normalizePoints: function (rawPoints) {
      return rawPoints
        .map(function (point) {
          return {
            duration_sec: Number(point.duration_sec) || 0,
            best_power_w: point.best_power_w == null ? null : Number(point.best_power_w),
            start_sec: point.start_sec == null ? null : Number(point.start_sec),
            end_sec: point.end_sec == null ? null : Number(point.end_sec),
          }
        })
        .filter(function (point) {
          return point.duration_sec >= 1 && point.best_power_w != null
        })
        .sort(function (a, b) { return a.duration_sec - b.duration_sec })
    },

    _formatPower: function (power) {
      if (power == null) return '-- W'
      return Math.round(power) + ' W'
    },

    _formatDuration: function (sec) {
      sec = Math.max(0, Math.round(Number(sec) || 0))
      const hours = Math.floor(sec / 3600)
      const minutes = Math.floor((sec % 3600) / 60)
      const seconds = sec % 60
      if (hours > 0) return hours + ':' + pad2(minutes) + ':' + pad2(seconds)
      return minutes + ':' + pad2(seconds)
    },

    _formatRange: function (startSec, endSec) {
      if (startSec == null || endSec == null) return ''
      return this._formatDuration(startSec) + ' - ' + this._formatDuration(endSec)
    },

    _findNearestPoint: function (durationSec) {
      const points = this._points || []
      if (!points.length) return null
      let best = points[0]
      let bestDiff = Math.abs(Math.log(points[0].duration_sec) - Math.log(durationSec))
      for (let i = 1; i < points.length; i++) {
        const diff = Math.abs(Math.log(points[i].duration_sec) - Math.log(durationSec))
        if (diff < bestDiff) {
          best = points[i]
          bestDiff = diff
        }
      }
      return best
    },

    _setActivePoint: function (point) {
      if (!point) return
      this._activePoint = point
      this.setData({
        activePowerText: this._formatPower(point.best_power_w),
        activeDurationText: this._formatDuration(point.duration_sec),
        activeRangeText: this._formatRange(point.start_sec, point.end_sec),
      })
      this._scheduleRender()
    },

    _fetchExactEffort: function (durationSec) {
      const that = this
      const activityId = this.data.activityId
      if (!activityId || !durationSec) return

      const effortUrl = '/api/activities/' + activityId + '/power-curve/effort'
      api.get(effortUrl, { duration_sec: durationSec })
        .then(function (data) {
          if (!data || data.has_power !== true || data.best_power_w == null) return
          that._setActivePoint({
            duration_sec: Number(data.duration_sec) || durationSec,
            best_power_w: Number(data.best_power_w),
            start_sec: data.start_sec == null ? null : Number(data.start_sec),
            end_sec: data.end_sec == null ? null : Number(data.end_sec),
          })
        })
        .catch(function () {
          // 精确查询失败时保留拖动过程中的近似点，不打断用户看图。
        })
    },

    onCurveTouchStart: function (e) {
      this._updateFromTouch(e, false)
    },

    onCurveTouchMove: function (e) {
      this._updateFromTouch(e, false)
    },

    onCurveTouchEnd: function (e) {
      this._updateFromTouch(e, true)
    },

    _updateFromTouch: function (e, shouldFetchExact) {
      const touch = (e.touches && e.touches[0]) ||
        (e.changedTouches && e.changedTouches[0])
      if (!touch || !this._chartState) return

      const durationSec = this._durationFromTouch(touch)
      if (!durationSec) return

      const nearest = this._findNearestPoint(durationSec)
      this._setActivePoint(nearest)
      if (shouldFetchExact) this._fetchExactEffort(durationSec)
    },

    _durationFromTouch: function (touch) {
      const state = this._chartState
      if (!state || !state.chartW) return null

      let localX
      if (touch.x != null) {
        localX = touch.x
      } else {
        const touchX = touch.clientX != null ? touch.clientX : touch.pageX
        if (touchX == null) return null
        localX = state.left != null ? touchX - state.left : touchX
      }

      localX = clamp(localX, state.pad.left, state.width - state.pad.right)
      const ratio = (localX - state.pad.left) / state.chartW
      const logDuration = state.logMin + ratio * (state.logMax - state.logMin)
      return clamp(Math.round(Math.exp(logDuration)), 1, state.maxDurationSec)
    },

    _scheduleRender: function () {
      if (this._redrawTimer) return
      const that = this
      this._redrawTimer = setTimeout(function () {
        that._redrawTimer = null
        that._renderCanvas()
      }, 32)
    },

    _renderCanvas: function () {
      const that = this
      const points = this._points || []
      if (!points.length || !this.data.visible) return

      const query = this.createSelectorQuery()
      query.select('#activityPowerCurveCanvas')
        .fields({ node: true, size: true, rect: true })
        .exec(function (res) {
          if (!res || !res[0] || !res[0].node) return

          const canvas = res[0].node
          const width = res[0].width
          const height = res[0].height
          const ctx = canvas.getContext('2d')
          const sysInfo = wx.getSystemInfoSync()
          const dpr = sysInfo.pixelRatio || 1
          canvas.width = width * dpr
          canvas.height = height * dpr
          ctx.scale(dpr, dpr)
          ctx.clearRect(0, 0, width, height)

          const pad = { top: 66, right: 18, bottom: 34, left: 44 }
          const chartW = width - pad.left - pad.right
          const chartH = height - pad.top - pad.bottom
          if (chartW <= 0 || chartH <= 0) return

          const maxDurationSec = Math.max(
            that._maxDurationSec || 1,
            points[points.length - 1].duration_sec
          )
          const logMin = Math.log(1)
          const logMax = Math.log(Math.max(2, maxDurationSec))
          let maxPower = 0
          for (let i = 0; i < points.length; i++) {
            if (points[i].best_power_w > maxPower) maxPower = points[i].best_power_w
          }
          const maxY = Math.max(100, Math.ceil(maxPower * 1.12 / 50) * 50)

          that._chartState = {
            width: width,
            left: res[0].left || 0,
            pad: pad,
            chartW: chartW,
            logMin: logMin,
            logMax: logMax,
            maxDurationSec: maxDurationSec,
          }

          function toX(durationSec) {
            const ratio = (Math.log(Math.max(1, durationSec)) - logMin) / (logMax - logMin)
            return pad.left + clamp(ratio, 0, 1) * chartW
          }

          function toY(power) {
            return pad.top + chartH - (clamp(power, 0, maxY) / maxY) * chartH
          }

          that._drawGrid(ctx, width, pad, chartW, chartH, maxY, maxDurationSec, toX)
          that._drawCurve(ctx, points, toX, toY)
          that._drawActivePoint(ctx, width, pad, toX, toY)
        })
    },

    _drawGrid: function (ctx, width, pad, chartW, chartH, maxY, maxDurationSec, toX) {
      ctx.save()
      ctx.strokeStyle = GRID_COLOR
      ctx.lineWidth = 1
      ctx.fillStyle = TEXT_MUTED
      ctx.font = '10px -apple-system, sans-serif'
      ctx.textBaseline = 'middle'
      ctx.textAlign = 'right'

      for (let i = 0; i <= 3; i++) {
        const y = pad.top + chartH * i / 3
        ctx.beginPath()
        ctx.moveTo(pad.left, y)
        ctx.lineTo(width - pad.right, y)
        ctx.stroke()
        const value = Math.round(maxY * (1 - i / 3))
        ctx.fillText(value, pad.left - 6, y)
      }

      const labels = this._axisDurations(maxDurationSec)
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      for (let j = 0; j < labels.length; j++) {
        const duration = labels[j]
        const x = toX(duration)
        ctx.beginPath()
        ctx.moveTo(x, pad.top)
        ctx.lineTo(x, pad.top + chartH)
        ctx.stroke()
        ctx.fillText(this._shortDuration(duration), x, pad.top + chartH + 8)
      }
      ctx.restore()
    },

    _drawCurve: function (ctx, points, toX, toY) {
      ctx.save()
      ctx.strokeStyle = COLOR
      ctx.lineWidth = 2.5
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      ctx.beginPath()
      for (let i = 0; i < points.length; i++) {
        const x = toX(points[i].duration_sec)
        const y = toY(points[i].best_power_w)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
      ctx.restore()
    },

    _drawActivePoint: function (ctx, width, pad, toX, toY) {
      const point = this._activePoint
      if (!point) return
      const x = toX(point.duration_sec)
      const y = toY(point.best_power_w)

      ctx.save()
      ctx.strokeStyle = '#1D1D1F'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(x, pad.top - 2)
      ctx.lineTo(x, y + 18)
      ctx.stroke()

      ctx.fillStyle = '#1D1D1F'
      ctx.beginPath()
      ctx.arc(x, y, 4.5, 0, Math.PI * 2)
      ctx.fill()

      const powerText = this._formatPower(point.best_power_w)
      const durationText = this._formatDuration(point.duration_sec)
      const bubbleW = clamp(Math.max(powerText.length * 9 + 36, 98), 98, 150)
      const bubbleH = 48
      const bubbleX = clamp(x - bubbleW / 2, pad.left, width - pad.right - bubbleW)
      const bubbleY = 8

      drawRoundRect(ctx, bubbleX, bubbleY, bubbleW, bubbleH, 8)
      ctx.fillStyle = COLOR
      ctx.fill()
      ctx.fillStyle = '#FFFFFF'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.font = '16px -apple-system, sans-serif'
      ctx.fillText(powerText, bubbleX + bubbleW / 2, bubbleY + 7)
      ctx.font = '11px -apple-system, sans-serif'
      ctx.fillText(durationText, bubbleX + bubbleW / 2, bubbleY + 28)
      ctx.restore()
    },

    _axisDurations: function (maxDurationSec) {
      const candidates = [5, 60, 300, 1200, 3600, 7200, 14400]
      const labels = candidates.filter(function (sec) { return sec <= maxDurationSec })
      if (labels.length < 2) return [1, maxDurationSec]
      return labels
    },

    _shortDuration: function (sec) {
      if (sec < 60) return sec + 's'
      if (sec < 3600) return Math.round(sec / 60) + 'm'
      return Math.round(sec / 3600) + 'h'
    },
  },
})
