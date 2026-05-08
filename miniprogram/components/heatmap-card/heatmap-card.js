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
 *   渲染态 = multipoint.coordinates 非空 且 activity_count > 0
 *
 * 数据流：
 *   attached / props 变化 → _fetchAndRender → setData(loading)
 *   → api.get → 成功 → _convertToMarkers → setData(markers + center)
 *                  → 失败 → setData(error)
 *
 * 注意（坑预防）：
 *   1. 后端 multipoint.coordinates 是 GeoJSON 约定的 [lon, lat] 顺序，
 *      小程序 marker 要的是 latitude / longitude，转换时别搞反！
 *   2. props 变化不会自动触发 attached，需要 observers 监听重新 fetch
 *   3. 当前后端 multipoint 返回的只是坐标列表，没有 count 字段；
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
    markers: [],           // 小程序 map 接受的 markers 数组
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
     *   3. 拿到响应后判空 → 转 markers → setData 渲染态
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
          // 后端契约：{city, multipoint: {type, coordinates: [[lon,lat],...]}, activity_count}
          const coords = (data && data.multipoint && data.multipoint.coordinates) || []
          const activityCount = (data && data.activity_count) || 0

          // 空状态判定：任一为空都算空（防御式判定）
          if (coords.length === 0 || activityCount === 0) {
            this.setData({
              loading: false,
              error: false,
              isEmpty: true,
            })
            return
          }

          // 转 markers + 算中心
          const markers = this._convertToMarkers(coords)
          const center = this._computeCenter(coords, cityToUse)

          this.setData({
            loading: false,
            error: false,
            isEmpty: false,
            markers: markers,
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
     * 把后端 GeoJSON coordinates 数组转成小程序 markers 数组
     *
     * 输入：[[lon, lat], [lon, lat], ...]   GeoJSON 约定 lon 在前
     * 输出：[{id, latitude, longitude, iconPath, width, height}, ...]
     *
     * 当前简化版：所有 marker 用同一个 grey icon——后端 multipoint 还没返回 count 字段，
     *           按 count 上色是未来事（task 卡 Step B.4 提到但本期不做，避免伪造数据）。
     *
     * 类比：先把所有"骑过的点"用同样的灰点标出来，
     *       未来后端如果改成返回 grid + count，这里再升级"红橙蓝"梯度。
     */
    _convertToMarkers(coords) {
      // 真机回归实证（2026-05-08）：生产 server city=unknown 返回 ~14000 个坐标点
      // 14000 个 markers 每个 ~50 字节 ≈ 700KB / 接近小程序 setData 1MB 硬限制
      // 后果：setData 静默截断或渲染异常（Tim 真机看到"蓝色海面无 markers"）
      // 修复：均匀采样到 MAX_MARKERS / 视觉上 200-500 已足够看出"骑过哪些区域"
      // 未来 task：后端做 grid 聚合返回 grid+count（task 卡 Step B.4 提到 / 当前不做）
      const MAX_MARKERS = 200
      const step = coords.length > MAX_MARKERS ? Math.ceil(coords.length / MAX_MARKERS) : 1

      const markers = []
      for (let i = 0; i < coords.length; i += step) {
        const c = coords[i]
        // 防御：坐标格式不对就跳过这个点（不让一个坏点搞挂整个图）
        if (!Array.isArray(c) || c.length < 2) continue
        const lon = c[0]
        const lat = c[1]
        if (typeof lon !== 'number' || typeof lat !== 'number') continue

        markers.push({
          id: i,                       // 小程序 markers 必须有唯一 id
          latitude: lat,               // 小程序要 latitude（注意和 GeoJSON 反着！）
          longitude: lon,
          iconPath: '/components/heatmap-card/icons/grey.png',
          width: 16,
          height: 16,
        })
      }
      return markers
    },

    /**
     * 计算 map 中心点
     *
     * 策略：
     *   - 坐标非空 → 取中位数（mean）作为中心，让 map 大致对准用户活动范围
     *   - 坐标空 → 用 city 默认中心兜底（理论上这条永不触发，因为空坐标已进 isEmpty 分支）
     *
     * 为什么用平均值不用边界中心：边界中心会被一两个偏远点拉偏，
     * 平均值更能代表"用户主要骑哪儿"。
     */
    _computeCenter(coords, cityToUse) {
      if (!coords || coords.length === 0) {
        return CITY_DEFAULT_CENTER[cityToUse] || CITY_DEFAULT_CENTER.unknown
      }
      let sumLon = 0
      let sumLat = 0
      let n = 0
      for (let i = 0; i < coords.length; i++) {
        const c = coords[i]
        if (!Array.isArray(c) || c.length < 2) continue
        if (typeof c[0] !== 'number' || typeof c[1] !== 'number') continue
        sumLon += c[0]
        sumLat += c[1]
        n += 1
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
