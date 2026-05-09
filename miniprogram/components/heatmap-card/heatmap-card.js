/**
 * 骑行热力图 component（Sprint 4 task-4.2.B / D21 模块化）
 *
 * 这是个"自给自足的小卡片"：profile 页面只需要一行 <heatmap-card city="xxx" />
 * 就能让用户看到自己骑过的区域。所有数据获取、状态切换、坐标转换都在
 * component 内部消化，page 层完全不用管。
 *
 * 类比：就像把"显示天气"这件事打包成一个独立小部件——
 * 你不需要知道它怎么取数据、怎么渲染图标，把它放到页面上就完事了。
 *
 * props 设计（4.3 复用关键）：
 *   - userId: Number 默认 0
 *       0 = 看自己，调用 GET /api/user/me/heatmap
 *       非 0 = 看他人，调用 GET /api/user/{userId}/heatmap（task-4.3 才补该 endpoint）
 *   - city: String 默认 ''
 *       '' = component 内部 fallback 'unknown'
 *       城市必须是后端 UserCity 7 枚举之一：
 *       beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan / unknown
 *
 * 4 状态机：
 *   loading → error（网络炸） / 渲染 / empty
 *   渲染态 = tracks 非空 且 activity_count > 0（D27 v2 polish）
 *
 * 数据流：
 *   attached / props 变化 → _fetchAndRender → setData(loading)
 *   → api.get → 成功 → _convertToPolylines → setData(polylines + center)
 *                  → 失败 → setData(error)
 *
 * 注意（坑预防）：
 *   1. 后端 tracks 是 list of list / 每条轨迹是 [[lon, lat], ...] GeoJSON 约定 lon 在前，
 *      小程序 marker 要的是 latitude / longitude，转换时别搞反！
 *   2. props 变化不会自动触发 attached，需要 observers 监听重新 fetch
 *   3. tracks 保留 activity 边界让前端画 polyline / 多条 opacity 重叠形成自然热力（不需 count 字段）；
 *      所以"按 count 排序、颜色越深"是未来事，本期所有 marker 用同一个 grey icon
 */

const api = require('../../utils/api')

// 城市默认中心点（坐标列表为空时的兜底中心，避免 map 显示在大洋上）
// 数据来源：百度地图各市政府所在地经纬度近似值
const CITY_DEFAULT_CENTER = {
  beijing: { lat: 39.9042, lng: 116.4074 },
  shanghai: { lat: 31.2304, lng: 121.4737 },
  hangzhou: { lat: 30.2741, lng: 120.1551 },
  shenzhen: { lat: 22.5431, lng: 114.0579 },
  chengdu: { lat: 30.5728, lng: 104.0668 },
  taiyuan: { lat: 37.8706, lng: 112.5489 },
  unknown: { lat: 39.9042, lng: 116.4074 },  // 未知城市兜底为北京
}

Component({
  /**
   * 外部传入的属性（properties）
   * 类比：就像组装家具时的螺丝接口——告诉外面"我接受什么参数"
   */
  properties: {
    userId: {
      type: Number,
      value: 0,
      observer: '_onPropsChange',
    },
    city: {
      type: String,
      value: '',
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
    polylines: [],         // 小程序 map 接受的 polylines 数组（D27 v2 polish / 每 activity 一条）
    center: { lat: 39.9042, lng: 116.4074 },  // map 中心（默认北京）
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
     * 核心方法：拉数据 → 转换 → 渲染
     *
     * 流程：
     *   1. setData 进入 loading 态
     *   2. 根据 userId 选择 endpoint（看自己 vs 看他人）
     *   3. 拿到响应后判空 → 转 polylines → setData 渲染态
     *   4. 任何步骤报错 → setData error 态
     */
    _fetchAndRender() {
      this._fetchedOnce = true
      // 进入 loading 态（清掉上次的 error/empty 状态）
      this.setData({ loading: true, error: false, isEmpty: false })

      // city fallback：'' → 'unknown'（D9 / D17 严守）
      const cityToUse = this.data.city || 'unknown'

      // userId === 0 调 me / 非 0 调 user/{id}（task-4.3 后端补）
      const url = this.data.userId === 0
        ? '/api/user/me/heatmap?city=' + cityToUse
        : '/api/user/' + this.data.userId + '/heatmap?city=' + cityToUse

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

          // 转 polylines + 算中心
          const polylines = this._convertToPolylines(tracks)
          const center = this._computeCenter(tracks, cityToUse)

          this.setData({
            loading: false,
            error: false,
            isEmpty: false,
            polylines: polylines,
            center: center,
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
     * 把后端 tracks 数组转成小程序 polylines 数组（D27 v2 polish）
     *
     * 输入：[[[lon, lat], [lon, lat], ...], ...] / 每内层 list 是一个 activity 的轨迹
     * 输出：[{points: [{latitude, longitude}, ...], color, width, ...}, ...]
     *
     * 视觉策略：
     * - 每条 activity 一条独立 polyline / 黄色 #FFD700（接近 ride.fitcard.app 风格）
     * - opacity 0.5 让多条 polyline 重叠时颜色叠加变深 → 自然热力效果（骑得越多越亮）
     * - 不需要后端聚合 count / 重叠次数自带视觉梯度
     *
     * 类比：透明黄色马克笔在地图上多次描同一条路 → 自然变成更亮的黄
     */
    _convertToPolylines(tracks) {
      const polylines = []
      for (let i = 0; i < tracks.length; i++) {
        const track = tracks[i]
        if (!Array.isArray(track) || track.length < 2) continue
        const points = []
        for (let j = 0; j < track.length; j++) {
          const c = track[j]
          if (!Array.isArray(c) || c.length < 2) continue
          const lon = c[0]
          const lat = c[1]
          if (typeof lon !== 'number' || typeof lat !== 'number') continue
          points.push({ latitude: lat, longitude: lon })
        }
        if (points.length < 2) continue  // 单点不能成 polyline / 跳过
        polylines.push({
          points: points,
          color: '#FFD700CC',           // 亮黄 + 80% alpha 让重叠色叠加（CC = 204/255 ≈ 80%）
          width: 4,
          arrowLine: false,
          dottedLine: false,
        })
      }
      return polylines
    },

    /**
     * 计算 map 中心点（接 tracks 输入 / D27 v2 polish）
     *
     * 策略：
     *   - tracks 非空 → 扁平化所有点取均值，让 map 大致对准用户活动范围
     *   - tracks 空 → 用 city 默认中心兜底（理论上不触发，空 tracks 已进 isEmpty 分支）
     *
     * 为什么用平均值不用边界中心：边界中心会被一两个偏远点拉偏，
     * 平均值更能代表"用户主要骑哪儿"。
     */
    _computeCenter(tracks, cityToUse) {
      if (!tracks || tracks.length === 0) {
        return CITY_DEFAULT_CENTER[cityToUse] || CITY_DEFAULT_CENTER.unknown
      }
      let sumLon = 0
      let sumLat = 0
      let n = 0
      for (let i = 0; i < tracks.length; i++) {
        const track = tracks[i]
        if (!Array.isArray(track)) continue
        for (let j = 0; j < track.length; j++) {
          const c = track[j]
          if (!Array.isArray(c) || c.length < 2) continue
          if (typeof c[0] !== 'number' || typeof c[1] !== 'number') continue
          sumLon += c[0]
          sumLat += c[1]
          n += 1
        }
      }
      if (n === 0) {
        return CITY_DEFAULT_CENTER[cityToUse] || CITY_DEFAULT_CENTER.unknown
      }
      return {
        lat: sumLat / n,
        lng: sumLon / n,
      }
    },
  },
})
