/**
 * 骑行热力图 component（Sprint 4 task-4.2.B / D21 模块化 / v3 polish）
 *
 * 这是个"自给自足的小卡片"：profile 页面只需要一行 <heatmap-card />（自己）
 * 或 <heatmap-card userId="{{otherId}}" />（看他人）就能让用户看到骑过的区域。
 * 所有数据获取、状态切换、轨迹绘制都在 component 内部消化，page 层完全不用管。
 *
 * 类比：就像把"显示天气"这件事打包成一个独立小部件——
 * 你不需要知道它怎么取数据、怎么渲染图标，把它放到页面上就完事了。
 *
 * ─── v3 polish 关键改动（2026-05-08）───────────────
 * 1. 砍 city props：后端 v3 city 已可选，前端不再强制传 / 直接拉用户全部活动轨迹
 * 2. 展示层改为 canvas 自绘纸面轨迹：只画路线形状，不再依赖原生地图底图
 *
 * ─── 2026-06-13 修白屏：旧 canvas API → 新版 Canvas 2D ───
 * 全量轨迹（几十万点）塞旧 wx.createCanvasContext + ctx.draw() 会渲染超时白屏。
 * 改用新版 Canvas 2D（type="2d" + this.createSelectorQuery，详情页图表同款）：
 * 同步立即渲染；服务端按卡片像素生成轻量预览，前端完整绘制响应中的点。
 *
 * props 设计（4.3 复用关键）：
 *   - userId: Number 默认 0
 *       0 = 看自己，调用 GET /api/user/me/heatmap
 *       非 0 = 看他人，调用 GET /api/user/{userId}/heatmap（task-4.3 才补该 endpoint）
 *
 * 4 状态机：
 *   loading → error（网络炸） / 渲染 / empty
 *   渲染态 = tracks 非空 且 activity_count > 0（D27 v2 polish）
 *
 * 数据流：
 *   attached / props 变化 → _fetchAndRender → setData(loading)
 *   → api.get → 成功 → 轨迹留在逻辑层实例 → canvas 自绘纸面轨迹
 *                  → 失败 → setData(error)
 *
 * 注意（坑预防）：
 *   1. 后端 tracks 是 list of list / 每条轨迹是 [[lon, lat], ...] GeoJSON 约定 lon 在前，
 *      canvas 画形状时仍按 lon/lat 读，别把经纬度顺序搞反
 *   2. props 变化不会自动触发 attached，需要 observers 监听重新 fetch
 *   3. tracks 保留 activity 边界让前端逐条画线 / 多条 opacity 重叠形成自然热力（不需 count 字段）；
 *      所以"按 count 排序、颜色越深"是未来事，本期所有轨迹线用同一个透明橙
 */

const api = require('../../utils/api')
const routeThumb = require('../../utils/route-thumb')

Component({
  /**
   * 外部传入的属性（properties）
   * 类比：就像组装家具时的螺丝接口——告诉外面"我接受什么参数"
   *
   * v3 polish 砍掉 city props：后端 v3 city 已可选，不再需要强制传
   */
  properties: {
    userId: {
      type: Number,
      value: 0,
      observer: '_onPropsChange',
    },
  },

  /**
   * 组件内部数据（data）
   * 类比：组件自己的"小本本"，只有自己看，外面看不到也改不到
   */
  data: {
    loading: true,         // 初始进入就是 loading 态
    error: false,          // 网络/接口报错
    isEmpty: false,        // 数据空（无活动记录）
  },

  /**
   * 生命周期
   * attached = component 被插入到页面节点时触发，是发起首次 fetch 的最佳时机
   */
  lifetimes: {
    attached() {
      this._fetchAndRender()
    },
  },

  methods: {
    /**
     * props 变化观察者
     *
     * 注意：observer 在 component 初始化时也会触发一次（每个 property 都会），
     * 那时 attached 还没跑、data 还是初始值，重复 fetch 会浪费请求。
     * 这里加个简单兜底：用 _fetchedOnce 标记跳过初始触发。
     */
    _onPropsChange() {
      if (!this._fetchedOnce) return  // 初始化阶段忽略，由 attached 统一发起
      this._fetchAndRender()
    },

    /**
     * 核心方法：拉数据 → 渲染
     *
     * 流程：
     *   1. setData 进入 loading 态
     *   2. 根据 userId 选择 endpoint（看自己 vs 看他人）
     *   3. 拿到响应后判空 → 轨迹留在逻辑层实例 → canvas 渲染态
     *   4. 任何步骤报错 → setData error 态
     */
    _fetchAndRender() {
      this._fetchedOnce = true
      // 进入 loading 态（清掉上次的 error/empty 状态）
      this.setData({ loading: true, error: false, isEmpty: false })

      // userId === 0 调 me / 非 0 调 user/{id}（task-4.3 后端补）
      // v3 polish：不再传 city query / 后端拉用户全部轨迹
      const url = this.data.userId === 0
        ? '/api/user/me/heatmap'
        : '/api/user/' + this.data.userId + '/heatmap'

      api.get(url)
        .then((data) => {
          // 后端契约（D27 v2 polish）：{city, tracks: [[[lon,lat],...], ...], activity_count}
          // tracks 是 list of list / 保留 activity 边界 / 每个 activity 一条独立轨迹
          const tracks = (data && data.tracks) || []
          const activityCount = (data && data.activity_count) || 0

          // 空状态判定：任一为空都算空（防御式判定）
          if (tracks.length === 0 || activityCount === 0) {
            this.setData({
              loading: false,
              error: false,
              isEmpty: true,
            })
            return
          }

          // 轨迹只给逻辑层 Canvas 2D 使用，WXML 从不读取。不能塞进 data：
          // 293 条活动会触发约 6.7 MB setData，把同一份坐标再复制到视图层，
          // 重启/热重载后容易阻塞渲染。放组件实例上即可，状态层只传 3 个布尔值。
          this._tracks = tracks
          this.setData({
            loading: false,
            error: false,
            isEmpty: false,
          }, () => {
            this._drawHeatmap()
          })
        })
        .catch(() => {
          // 任何错误都进 error 态（401 由 utils/api.js 已处理跳登录，这里只显示文案）
          this.setData({
            loading: false,
            error: true,
            isEmpty: false,
          })
        })
    },

    /**
     * 用户点击"加载失败 · 点击重试"时触发
     */
    _retryFetch() {
      this._fetchAndRender()
    },

    /**
     * 个人页热力图是展示卡，不需要拖动地图。
     * 用新版 Canvas 2D 自绘纸面 + 显示精度轨迹线：旧版 ctx.draw() 在巨量轨迹
     * 时渲染超时白屏；现在服务端按卡片像素预算生成预览，前端不再二次抽稀。
     */
    _drawHeatmap() {
      if (!this._tracks || this._tracks.length === 0) return
      // setTimeout 兜底 canvas 节点初始化（setData 翻转渲染态与节点 ready 不同帧）
      setTimeout(() => {
        routeThumb.drawHeatmap2d(this, '#heatmap-canvas', this._tracks, {
          lineWidth: 2,
        })
      }, 120)
    },
  },
})
