/**
 * 骑行热力图 component（Sprint 4 task-4.2.B / D21 模块化 / v3 polish）
 *
 * 这是个"自给自足的小卡片"：profile 页面只需要一行 <heatmap-card />（自己）
 * 或 <heatmap-card userId="{{otherId}}" />（看他人）就能让用户看到骑过的区域。
 * 所有数据获取、状态切换、坐标转换都在 component 内部消化，page 层完全不用管。
 *
 * 类比：就像把"显示天气"这件事打包成一个独立小部件——
 * 你不需要知道它怎么取数据、怎么渲染图标，把它放到页面上就完事了。
 *
 * ─── v3 polish 关键改动（2026-05-08）───────────────
 * 1. 砍 city props：后端 v3 city 已可选，前端不再强制传 / 直接拉用户全部活动轨迹
 * 2. 内部 GCJ-02 转换：WGS-84 GPS → GCJ-02 中国地图坐标 / 防偏移 100-700 米
 *    转换时机：_convertToPolylines 和 _computeCenter 都在塞给小程序 map 之前转
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
 *   → api.get → 成功 → _convertToPolylines（含 GCJ-02 转换）→ setData(polylines + center)
 *                  → 失败 → setData(error)
 *
 * 注意（坑预防）：
 *   1. 后端 tracks 是 list of list / 每条轨迹是 [[lon, lat], ...] GeoJSON 约定 lon 在前，
 *      小程序 marker 要的是 latitude / longitude，转换时别搞反！
 *   2. props 变化不会自动触发 attached，需要 observers 监听重新 fetch
 *   3. tracks 保留 activity 边界让前端画 polyline / 多条 opacity 重叠形成自然热力（不需 count 字段）；
 *      所以"按 count 排序、颜色越深"是未来事，本期所有 polyline 用同一个透明黄色
 *   4. GCJ-02 转换：只在塞给小程序 map 之前转 / 后端 tracks 永远是 WGS-84（数据真相源不动）
 */

const api = require('../../utils/api')
const { wgs84ToGcj02 } = require('../../utils/coords')

// 兜底中心点（轨迹空时让 map 别飘到大洋上 / 默认北京天安门）
const DEFAULT_CENTER = { lat: 39.9042, lng: 116.4074 }

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
     *   3. 拿到响应后判空 → 转 polylines（含 GCJ-02）→ setData 渲染态
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

          // 转 polylines + 算中心（两步内部都做 GCJ-02 转换）
          const polylines = this._convertToPolylines(tracks)
          const center = this._computeCenter(tracks)

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
     * 把后端 tracks 数组转成小程序 polylines 数组（D27 v2 polish / v3 加 GCJ-02）
     *
     * 输入：[[[lon, lat], [lon, lat], ...], ...] / 每内层 list 是一个 activity 的 WGS-84 轨迹
     * 输出：[{points: [{latitude, longitude}, ...], color, width, ...}, ...] / 已转 GCJ-02
     *
     * 视觉策略：
     * - 每条 activity 一条独立 polyline / 黄色 #FFD700（接近 ride.fitcard.app 风格）
     * - opacity 0.5 让多条 polyline 重叠时颜色叠加变深 → 自然热力效果（骑得越多越亮）
     * - 不需要后端聚合 count / 重叠次数自带视觉梯度
     *
     * 坐标系（v3 polish 关键）：
     * - 后端存的是 WGS-84（GPS 国际标准）
     * - 小程序 <map> 在中国大陆显示要用 GCJ-02（中国加密坐标）
     * - 不转直接传 → 轨迹偏移 100-700 米（明明骑大马路，地图上画到小区里）
     *
     * 类比：透明黄色马克笔在地图上多次描同一条路 → 自然变成更亮的黄
     */
    _convertToPolylines(tracks) {
      // hotfix 链总结（2026-05-09 task-4.2 v3 polish 真用迭代）：
      // - v1 cap=8000 / 步长 21 → 网格状直线（失败）
      // - v2 cap=50000 / 步长 3 → 视觉接近原版但放大后仍有 km 级直线（部分修）
      // - v3 加 segment split 500m → 切断 km 级跳点（修一半）
      // - **v4 砍 cap**（当前 / Tim 拍 A）→ 恢复 v3 polish 第一次部署精度（30m 中位数）
      //   理由：curl 实测 Tim 真实数据 P90=119m / cap=50000 步长 4 把 30m 中位数拉到 120m
      //   → 拐弯严重失真（截图 #1 #2）/ 砍 cap 后 setData ~5MB / Tim 实测 v3 polish 第一次部署过 / OK
      //
      // 保留：MAX_SEGMENT_M segment split 防虚假长直线（hotfix v3 成果）
      //      GCJ-02 转换（v3 polish）
      //      Number.isFinite 防 NaN 静默通过（v3 polish Codex 异源审 Important）
      //
      // 山区 GPS 物理误差散网（截图 #3）= L1 物理限制 / 砍 cap 也救不了 / 必须 map matching / 留 Sprint 5/6
      const MAX_SEGMENT_M = 500  // 单条 polyline 内相邻两点距离上限 / 城市道路一个街区 ~200-500m

      // Haversine 球面距离（米）/ 用于 segment split 判断
      const distM = (a, b) => {
        const R = 6371000
        const dLat = (b.latitude - a.latitude) * Math.PI / 180
        const dLng = (b.longitude - a.longitude) * Math.PI / 180
        const lat1 = a.latitude * Math.PI / 180
        const lat2 = b.latitude * Math.PI / 180
        const aa = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2
        return R * 2 * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa))
      }

      const polylines = []
      // 抽出"把 points 数组打包成 polyline 对象"逻辑 / split 后多次调用
      const flushPolyline = (points) => {
        if (points.length < 2) return  // 单点不能成 polyline
        polylines.push({
          points: points,
          color: '#FFD700CC',
          width: 4,
          arrowLine: false,
          dottedLine: false,
        })
      }

      for (let i = 0; i < tracks.length; i++) {
        const track = tracks[i]
        if (!Array.isArray(track) || track.length < 2) continue
        let points = []
        let lastPoint = null
        for (let j = 0; j < track.length; j++) {  // 不采样 / 完整渲染原始 simplified_track 点
          const c = track[j]
          if (!Array.isArray(c) || c.length < 2) continue
          const lon = c[0]
          const lat = c[1]
          // Number.isFinite 防 NaN/Infinity 静默通过（Codex 异源审 Important / typeof NaN === 'number' 是 true 坑）
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
          // WGS-84 → GCJ-02（国外坐标在 wgs84ToGcj02 内部自动跳过转换）
          const [gcjLat, gcjLng] = wgs84ToGcj02(lat, lon)
          // 转换后再次校验防异常算法返回 NaN
          if (!Number.isFinite(gcjLat) || !Number.isFinite(gcjLng)) continue
          const newPoint = { latitude: gcjLat, longitude: gcjLng }
          // segment split：相邻两点距离 > MAX_SEGMENT_M 就切断当前 polyline 开新段
          // （防 simplified_track 源数据 km 级跳点画出虚假长直线 / Tim 真机看到的网格 bug）
          if (lastPoint && distM(lastPoint, newPoint) > MAX_SEGMENT_M) {
            flushPolyline(points)
            points = []
          }
          points.push(newPoint)
          lastPoint = newPoint
        }
        flushPolyline(points)  // 收尾 / 把当前 track 最后一段刷到 polylines
      }
      return polylines
    },

    /**
     * 计算 map 中心点（接 tracks 输入 / D27 v2 polish / v3 加 GCJ-02）
     *
     * 策略：
     *   - tracks 非空 → 扁平化所有点取均值，再转 GCJ-02 让 map 大致对准用户活动范围
     *   - tracks 空 → 用默认北京中心兜底（理论上不触发，空 tracks 已进 isEmpty 分支）
     *
     * 为什么用平均值不用边界中心：边界中心会被一两个偏远点拉偏，
     * 平均值更能代表"用户主要骑哪儿"。
     *
     * 为什么"先求均值再转 GCJ-02"而不是"先转每点再求均值"：
     * - GCJ-02 偏移在小区域（< 50km）内是接近线性的近似常量
     * - 先平均后转换 = 1 次 GCJ-02 计算（O(1)）/ 先转后平均 = N 次（O(N)）
     * - 视觉结果几乎一样（差 < 10 米 / map scale 11 看不出来）
     */
    _computeCenter(tracks) {
      if (!tracks || tracks.length === 0) {
        return DEFAULT_CENTER
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
          // Number.isFinite 防 NaN/Infinity 污染 sumLon/sumLat（Codex 异源审 Important）
          if (!Number.isFinite(c[0]) || !Number.isFinite(c[1])) continue
          sumLon += c[0]
          sumLat += c[1]
          n += 1
        }
      }
      if (n === 0) {
        return DEFAULT_CENTER
      }
      // 求 WGS-84 均值后转 GCJ-02（map center 必须给 GCJ-02 才不偏移）
      const avgLat = sumLat / n
      const avgLon = sumLon / n
      const [gcjLat, gcjLng] = wgs84ToGcj02(avgLat, avgLon)
      return {
        lat: gcjLat,
        lng: gcjLng,
      }
    },
  },
})
