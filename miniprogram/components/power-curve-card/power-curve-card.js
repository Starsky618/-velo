/**
 * 功率曲线 component（Sprint 4 task-4.2.A / D21 模块化哲学）
 *
 * ─── 这个组件是干什么的 ─────────────────────────────
 * 在用户个人页展示"我最近 30 天 / 90 天 / 半年 / 一年 / 全部历史"
 * 内的功率曲线（不同时长下的最佳平均功率），用一条折线展示
 * 7 个关键档的功率数值（D26 v2 polish）：
 *   瞬时（0s 单点最大）/ 3s（无氧爆发）/ 30s / 1min / 5min / 20min / 1h
 *
 * 4.3 看他人 profile 时复用本 component：传 userId !== 0 即切到看他人路径。
 * 未来想在别的 tab 展示也直接 `<power-curve-card />` 一行引入。
 *
 * ─── 数据流 ─────────────────────────────────────
 *   attached lifetime → _fetchAndRender()
 *     ├ userId === 0 → GET /api/user/me/power-curve?period=xxx
 *     └ userId !== 0 → GET /api/user/{userId}/power-curve?period=xxx（4.3 加 endpoint）
 *   后端返回 { period, buckets: { "0": W, "3": W, "30": W, "60": W, "300": W, "1200": W, "3600": W } }
 *     ├ 全 0 / 空 → setData isEmpty=true（显示"还没数据"）
 *     └ 有值 → setData hasData=true → setTimeout(100) → _renderCanvas() 画 1 条折线连 7 点
 *
 * ─── 状态机 ─────────────────────────────────────
 *   loading（初始 true）→ error / isEmpty / hasData
 *   error 时点击重试 → 回到 loading 重新发请求
 *
 * ─── 注意事项 ────────────────────────────────────
 * 1. canvas 用 hidden 而非 wx:if（CLAUDE.md 陷阱 #17 / F1 渲染时序坑）
 * 2. setData 后用 setTimeout(fn, 100) 触发 render（不用 wx.nextTick / 极慢机型兜底）
 * 3. observers 监听 userId / period 变化重新 fetch（4.3 / 未来 period 选择器复用关键）
 */

const api = require('../../utils/api')

/**
 * 横坐标 7 档（D26 v2 polish / Sprint 4 task-4.2 v2 / 全部展示，不跳过）
 * - 0s 瞬时最大功率（单点 max / 短时爆发力极限）
 * - 3s（无氧爆发起步）
 * - 30s（短冲）
 * - 1min（极短无氧）
 * - 5min（VO2max）
 * - 20min（FTP 接近值）
 * - 1h（长距离耐力）
 *
 * 后端 buckets 7 档（"0"/"3"/"30"/"60"/"300"/"1200"/"3600"）/ 全部展示对应 ride.fitcard 风格
 * Tim 拍：去掉 5s / 加 0s 瞬时 + 1h 长距离 / 6+1=7 个数据点连成曲线
 */
const DISPLAY_BUCKETS = [
  { key: '0', label: '瞬时' },
  { key: '3', label: '3s' },
  { key: '30', label: '30s' },
  { key: '60', label: '1min' },
  { key: '300', label: '5min' },
  { key: '1200', label: '20min' },
  { key: '3600', label: '1h' },
]

/**
 * period → 副标题文案
 */
const PERIOD_LABEL = {
  last_30_days: '最近 30 天',
  last_90_days: '最近 90 天',
  last_180_days: '最近半年',
  last_365_days: '最近一年',
  all_time: '全部历史',
}

Component({
  properties: {
    // 0 = 看自己 / 非 0 = 看他人（4.3 用）
    userId: {
      type: Number,
      value: 0,
      observer: function () {
        // userId 变化重新 fetch（4.3 看不同人路径切换）
        if (this.data._mounted) this._fetchAndRender()
      },
    },
    // 时间窗 prop（外部传入的初始值 / v3 polish 之后真相源是 data.currentPeriod）
    // 监听 prop 变化时同步到 currentPeriod / 让父组件控制初始档仍然生效
    period: {
      type: String,
      value: 'last_30_days',
      observer: function (newVal) {
        // 父组件改 prop → 同步到 currentPeriod 真相源 + 重 fetch
        if (newVal === this.data.currentPeriod) return
        this.setData({
          currentPeriod: newVal,
          subtitle: this._buildSubtitle(newVal),
        })
        if (this.data._mounted) this._fetchAndRender()
      },
    },
  },

  data: {
    loading: true,
    error: false,
    isEmpty: false,
    subtitle: '最近 30 天 · 瞬时 / 3s / 30s / 1min / 5min / 20min / 1h',
    // v3 polish 加 period 切换 UI 后的"真相源"：
    // - 用户点 segment control 改的是 currentPeriod（不改 props）
    // - properties.period 仅作为初始值 / 父组件想强制切档时用
    // - _fetchAndRender 永远读 currentPeriod
    currentPeriod: 'last_30_days',
    // 内部标记：attached 之后才允许 observer 触发 fetch（防 properties 默认值
    // 初始化时 observer 已触发一次 fetch，attached 又触发一次重复请求）
    _mounted: false,
  },

  lifetimes: {
    attached() {
      // 初始化：用真实 period prop 值同步到 currentPeriod + 副标题
      const initPeriod = this.data.period || 'last_30_days'
      this.setData({
        currentPeriod: initPeriod,
        subtitle: this._buildSubtitle(initPeriod),
        _mounted: true,
      })
      this._fetchAndRender()
    },
  },

  methods: {
    /**
     * 拼副标题：跟着 period 动态变（30 天 / 90 天 / 半年 / 一年 / 全部）
     */
    _buildSubtitle: function (period) {
      const periodText = PERIOD_LABEL[period] || '最近 30 天'
      return periodText + ' · 瞬时 / 3s / 30s / 1min / 5min / 20min / 1h'
    },

    /**
     * 重试入口（error 态点击触发）
     */
    _retryFetch: function () {
      this._fetchAndRender()
    },

    /**
     * period 切换入口（v3 polish 新加 / segment control bindtap 触发）
     *
     * 流程：
     *   1. 点同档不重 fetch（防止用户连点浪费请求 + canvas 重绘闪烁）
     *   2. 点新档 → 改 currentPeriod 真相源 + 同步副标题 → 触发重 fetch
     *
     * 类比：换电视频道——点当前频道遥控按了也没事，
     * 点新频道才真切过去再加载新节目。
     */
    _onPeriodTap: function (e) {
      const period = e.currentTarget.dataset.period
      if (!period || period === this.data.currentPeriod) return  // 同档跳过
      this.setData({
        currentPeriod: period,
        subtitle: this._buildSubtitle(period),
      })
      this._fetchAndRender()
    },

    /**
     * 主流程：拉数据 + 判断状态 + 触发渲染
     *
     * 类比：去厨房做菜——
     * 1. 进厨房（setData loading=true 让 UI 先显示"加载中"）
     * 2. 看菜谱（决定调哪个 endpoint）
     * 3. 取食材（发请求）
     * 4. 看食材新不新鲜（buckets 全 0 = 空数据 / 否则真渲染）
     * 5. 上桌（setTimeout 100ms 后画 canvas / 兜底等节点 ready）
     */
    _fetchAndRender: function () {
      const that = this

      // 重置状态进入 loading（重试 / period 切换都走这里）
      this.setData({ loading: true, error: false, isEmpty: false })

      // userId === 0 看自己 / 非 0 看他人（看他人 endpoint task-4.3 才补 / 现在留分支）
      // v3 polish：period 真相源是 currentPeriod（用户切档改这个 / props.period 仅作初始值）
      const userId = this.data.userId
      const period = this.data.currentPeriod || this.data.period || 'last_30_days'
      const url = userId === 0
        ? '/api/user/me/power-curve?period=' + period
        : '/api/user/' + userId + '/power-curve?period=' + period

      api.get(url)
        .then(function (data) {
          // 后端契约：{ period, buckets: { "1": float, "5": float, ... } }
          const buckets = (data && data.buckets) || {}

          // 空数据判断：所有 value 都是 0（用户数据不够 / 没骑过）
          // 注意：用 Number(v) 防御后端可能返回字符串数字
          const values = Object.keys(buckets).map(function (k) { return Number(buckets[k]) || 0 })
          const isEmpty = values.length === 0 || values.every(function (v) { return v === 0 })

          if (isEmpty) {
            that.setData({ loading: false, isEmpty: true })
            return
          }

          // 暂存 buckets 供 _renderCanvas 用（不放 data 里，纯渲染数据，setData 一次也别浪费）
          that._buckets = buckets

          that.setData({ loading: false }, function () {
            // F1 陷阱兜底：setTimeout 100ms 等 canvas 节点 ready
            setTimeout(function () {
              that._renderCanvas()
            }, 100)
          })
        })
        .catch(function () {
          // 网络断 / 401 / 服务器错全归到 error 态（统一文案 / 简化 UX）
          that.setData({ loading: false, error: true })
        })
    },

    /**
     * 在 canvas 上画 4 条折线（其实是一条折线连接 4 个点）
     *
     * 设计简化：因为 X 轴只有 4 档（5s / 30s / 5min / 20min），不画"4 条线"，
     * 而是画"1 条折线连接 4 个数据点 + 4 个圆点 + Y 轴刻度 + X 轴标签"。
     * task 卡说"渲染 4 条折线"是表述偏差，真实需求 = 4 个时长点连成的功率曲线。
     *
     * 绘制顺序（画家算法 / 后画的盖前面的）：
     * 1. 取 canvas 节点 + Retina 适配
     * 2. 计算坐标映射（X 4 档均分 / Y 0~max*1.1 留余量）
     * 3. 画水平网格线（最浅）
     * 4. 画连接 4 个点的折线（红色主色调）
     * 5. 画 4 个圆点（强调数据点）
     * 6. 画 Y 轴刻度数字 + X 轴档位标签 + 数据点上方功率数字
     */
    _renderCanvas: function () {
      const that = this
      const buckets = this._buckets
      if (!buckets) return

      // 用 component 的 createSelectorQuery 才能查到 component 内部节点
      // （直接 wx.createSelectorQuery 拿不到，因为它默认查 page 树）
      const query = this.createSelectorQuery()
      query.select('#powerCurveCanvas')
        .fields({ node: true, size: true })
        .exec(function (res) {
          if (!res || !res[0] || !res[0].node) return

          const canvas = res[0].node
          const width = res[0].width
          const height = res[0].height
          const ctx = canvas.getContext('2d')

          // ── Retina 适配（同 detail.js drawElevationProfile） ──
          const sysInfo = wx.getSystemInfoSync()
          const dpr = sysInfo.pixelRatio
          canvas.width = width * dpr
          canvas.height = height * dpr
          ctx.scale(dpr, dpr)

          // 清空（observer 切 period 重绘时防止叠加）
          ctx.clearRect(0, 0, width, height)

          // ── 布局参数 ──
          const pad = { top: 24, right: 16, bottom: 32, left: 48 }
          const chartW = width - pad.left - pad.right
          const chartH = height - pad.top - pad.bottom

          // ── 计算数据点 + Y 轴范围 ──
          const points = DISPLAY_BUCKETS.map(function (b) {
            return { label: b.label, value: Number(buckets[b.key]) || 0 }
          })

          let maxY = 0
          for (let i = 0; i < points.length; i++) {
            if (points[i].value > maxY) maxY = points[i].value
          }
          // Y 轴上界留 15% 余量；最小 100W 兜底（防全 0 早过滤但 1~50W 数据也能展示）
          maxY = Math.max(Math.ceil(maxY * 1.15 / 50) * 50, 100)
          const minY = 0

          // 坐标转换函数：数据空间 → 画布像素
          // X：4 个点均分 chartW（首尾贴边留 10% 内缩防数字被切）
          function toX(idx) {
            if (points.length === 1) return pad.left + chartW / 2
            const inset = chartW * 0.08
            const usable = chartW - inset * 2
            return pad.left + inset + (idx / (points.length - 1)) * usable
          }
          function toY(value) {
            return pad.top + (1 - (value - minY) / (maxY - minY)) * chartH
          }

          // ── 1. 水平网格线（4 条 / 最浅灰） ──
          ctx.strokeStyle = 'rgba(0, 0, 0, 0.08)'
          ctx.lineWidth = 0.5
          const yTickCount = 4
          for (let t = 0; t <= yTickCount; t++) {
            const y = pad.top + (chartH / yTickCount) * t
            ctx.beginPath()
            ctx.moveTo(pad.left, y)
            ctx.lineTo(width - pad.right, y)
            ctx.stroke()
          }

          // ── 2. 折线（连接 4 个点 / 主色调红 #FF2D55） ──
          ctx.strokeStyle = '#FF2D55'
          ctx.lineWidth = 2.5
          ctx.lineJoin = 'round'
          ctx.lineCap = 'round'
          ctx.beginPath()
          for (let i = 0; i < points.length; i++) {
            const x = toX(i)
            const y = toY(points[i].value)
            if (i === 0) ctx.moveTo(x, y)
            else ctx.lineTo(x, y)
          }
          ctx.stroke()

          // ── 3. 数据点圆点（白底红边 / Apple Fitness 风格） ──
          for (let i = 0; i < points.length; i++) {
            const x = toX(i)
            const y = toY(points[i].value)
            ctx.beginPath()
            ctx.arc(x, y, 5, 0, Math.PI * 2)
            ctx.fillStyle = '#ffffff'
            ctx.fill()
            ctx.strokeStyle = '#FF2D55'
            ctx.lineWidth = 2
            ctx.stroke()
          }

          // ── 4. Y 轴刻度（4 档 / 右对齐贴在图表左侧） ──
          ctx.fillStyle = 'rgba(0, 0, 0, 0.4)'
          ctx.font = '10px -apple-system, sans-serif'
          ctx.textAlign = 'right'
          ctx.textBaseline = 'middle'
          for (let t = 0; t <= yTickCount; t++) {
            const value = maxY - (maxY / yTickCount) * t
            const y = pad.top + (chartH / yTickCount) * t
            ctx.fillText(Math.round(value) + 'W', pad.left - 6, y)
          }

          // ── 5. X 轴标签（4 个时长档位） ──
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          for (let i = 0; i < points.length; i++) {
            ctx.fillText(points[i].label, toX(i), pad.top + chartH + 8)
          }

          // ── 6. 每个点上方标功率数值（让用户一眼看到具体 W） ──
          ctx.fillStyle = '#1D1D1F'
          ctx.font = 'bold 11px -apple-system, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'bottom'
          for (let i = 0; i < points.length; i++) {
            const x = toX(i)
            const y = toY(points[i].value)
            ctx.fillText(Math.round(points[i].value) + 'W', x, y - 10)
          }
        })
    },
  },
})
