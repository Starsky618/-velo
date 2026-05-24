/**
 * 训练日历页 —— 展示 CTL / ATL / TSB 三条训练负荷曲线。
 *
 * 数据来源：GET /api/training/load?range=30d|90d|1y
 * 页面只展示后端给的 points + summary，不自己重算训练负荷。
 */
const api = require('../../utils/api')

const RANGE_LABELS = [
  { value: '30d', label: '30 天' },
  { value: '90d', label: '90 天' },
  { value: '1y', label: '全年' },
]

const STATUS_COPY = {
  fresh: '你状态饱满 / 可以上强度',
  ok: '状态 OK / 按计划训练即可',
  tired: '累 / 建议中低强度或休息',
  overreached: '过累 / 强烈建议休息 1-2 天',
}

Page({
  data: {
    ranges: RANGE_LABELS,
    currentRange: '30d',
    loading: true,
    loadError: false,
    summary: null,
    points: [],
    dataComplete: false,
    statusCopy: '',
    daysToComplete: 14,
  },

  onLoad() {
    this.fetchTrainingLoad()
  },

  onPullDownRefresh() {
    this.fetchTrainingLoad().finally(function () {
      wx.stopPullDownRefresh()
    })
  },

  onRangeTap(e) {
    const range = e.currentTarget.dataset.range
    if (!range || range === this.data.currentRange) return
    this.setData({ currentRange: range }, () => {
      this.fetchTrainingLoad()
    })
  },

  fetchTrainingLoad() {
    const that = this
    const range = this.data.currentRange
    this.setData({ loading: true, loadError: false })

    return api.get('/api/training/load', { range: range })
      .then(function (res) {
        const summary = res && res.summary ? res.summary : null
        const points = res && Array.isArray(res.points) ? res.points : []
        const dataComplete = !!(summary && summary.data_complete && points.length > 0)
        const statusBand = summary && summary.current_status_band ? summary.current_status_band : 'ok'
        const statusLabel = summary && summary.current_status_label ? summary.current_status_label : '状态 OK'
        const daysToComplete = Math.max(0, 14 - points.length)
        const statusCopy = dataComplete
          ? (STATUS_COPY[statusBand] || STATUS_COPY.ok)
          : '再骑 ' + daysToComplete + ' 天能看到完整训练负荷曲线'
        if (summary) summary.current_status_label = statusLabel

        that.setData({
          loading: false,
          summary: summary,
          points: points,
          dataComplete: dataComplete,
          statusCopy: statusCopy,
          daysToComplete: daysToComplete,
        }, function () {
          setTimeout(function () {
            that.renderChart()
          }, 100)
        })
      })
      .catch(function (err) {
        console.error('[training-calendar] fetch failed', err)
        that.setData({ loading: false, loadError: true })
        wx.showToast({
          title: (err && err.message) || '训练分析加载失败 / 请重试',
          icon: 'none',
          duration: 3000,
        })
        setTimeout(function () {
          wx.navigateBack({ delta: 1 })
        }, 1200)
      })
  },

  renderChart() {
    if (!this.data.dataComplete) {
      return
    }
    const points = this.data.points || []
    if (points.length === 0) return

    const query = this.createSelectorQuery()
    query.select('#pmc-chart')
      .fields({ node: true, size: true })
      .exec((res) => {
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

        const pad = { top: 28, right: 28, bottom: 34, left: 44 }
        const chartW = width - pad.left - pad.right
        const chartH = height - pad.top - pad.bottom
        const ctlAtlValues = points.map((p) => Math.max(Number(p.ctl) || 0, Number(p.atl) || 0))
        const maxLoad = Math.max.apply(null, ctlAtlValues.concat([100]))
        const minTsb = Math.min.apply(null, points.map((p) => Number(p.tsb) || 0).concat([-30]))
        const maxTsb = Math.max.apply(null, points.map((p) => Number(p.tsb) || 0).concat([30]))

        function toX(index) {
          if (points.length === 1) return pad.left + chartW / 2
          return pad.left + (index / (points.length - 1)) * chartW
        }

        function toLoadY(value) {
          return pad.top + (1 - (Number(value) || 0) / maxLoad) * chartH
        }

        function toTsbY(value) {
          const v = Number(value) || 0
          return pad.top + (1 - (v - minTsb) / (maxTsb - minTsb)) * chartH
        }

        this.drawGrid(ctx, width, height, pad, chartH)
        this.drawLine(ctx, points, toX, toLoadY, 'ctl', '#2EAD6B')
        this.drawLine(ctx, points, toX, toLoadY, 'atl', '#E6A23C')
        this.drawLine(ctx, points, toX, toTsbY, 'tsb', '#2F80ED')
        this.drawAxisLabels(ctx, points, width, height, pad, maxLoad, minTsb, maxTsb)
      })
  },

  drawGrid(ctx, width, height, pad, chartH) {
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.08)'
    ctx.lineWidth = 0.5
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (chartH / 4) * i
      ctx.beginPath()
      ctx.moveTo(pad.left, y)
      ctx.lineTo(width - pad.right, y)
      ctx.stroke()
    }
    ctx.strokeStyle = 'rgba(47, 128, 237, 0.18)'
    const zeroY = pad.top + chartH / 2
    ctx.beginPath()
    ctx.moveTo(pad.left, zeroY)
    ctx.lineTo(width - pad.right, zeroY)
    ctx.stroke()
  },

  drawLine(ctx, points, toX, toY, key, color) {
    ctx.strokeStyle = color
    ctx.lineWidth = key === 'tsb' ? 2 : 2.5
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.beginPath()
    points.forEach(function (point, index) {
      const x = toX(index)
      const y = toY(point[key])
      if (index === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()
  },

  drawAxisLabels(ctx, points, width, height, pad, maxLoad, minTsb, maxTsb) {
    ctx.fillStyle = '#8A8F98'
    ctx.font = '10px sans-serif'
    ctx.fillText('0', 12, height - pad.bottom)
    ctx.fillText(String(Math.round(maxLoad)), 10, pad.top + 4)
    ctx.fillText(String(Math.round(maxTsb)), width - pad.right + 4, pad.top + 4)
    ctx.fillText(String(Math.round(minTsb)), width - pad.right + 4, height - pad.bottom)

    if (points.length > 0) {
      ctx.textAlign = 'left'
      ctx.fillText(points[0].date.slice(5), pad.left, height - 10)
      ctx.textAlign = 'right'
      ctx.fillText(points[points.length - 1].date.slice(5), width - pad.right, height - 10)
      ctx.textAlign = 'start'
    }
  },
})
