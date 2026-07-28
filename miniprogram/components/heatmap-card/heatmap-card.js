/**
 * 个人页骑行热图卡片：一张真实底图 + 半透明骑行轨迹层。
 *
 * 卡片本身支持拖动和缩放；“全屏查看”进入独立地图页继续探索、切年份和颜色。
 * userId=0 看自己，非 0 看他人，沿用现有公开主页契约。
 */

const api = require('../../utils/api')
const heatmapMap = require('../../utils/heatmap-map')

Component({
  properties: {
    userId: {
      type: Number,
      value: 0,
      observer: '_onPropsChange',
    },
  },

  data: {
    loading: true,
    error: false,
    isEmpty: false,
    center: { latitude: 39.9042, longitude: 116.4074 },
    includePoints: [],
    polylines: [],
    activityCount: 0,
  },

  lifetimes: {
    attached() {
      this._fetchHeatmap()
    },
  },

  methods: {
    _onPropsChange() {
      if (!this._fetchedOnce) return
      this._fetchHeatmap()
    },

    _fetchHeatmap() {
      this._fetchedOnce = true
      this.setData({ loading: true, error: false, isEmpty: false })

      var url = this.data.userId === 0
        ? '/api/user/me/heatmap'
        : '/api/user/' + this.data.userId + '/heatmap'

      api.get(url, { detail: 'card' })
        .then((data) => {
          var tracks = data && Array.isArray(data.tracks) ? data.tracks : []
          var activityCount = Number(data && data.activity_count) || 0
          // 兼容尚未升级的旧后端：客户端也把卡片渲染层锁在 4000 点以内。
          var model = heatmapMap.buildHeatmapMapModel(tracks, 'orange', 3, 4000)
          if (!model || activityCount === 0) {
            this.setData({
              loading: false,
              error: false,
              isEmpty: true,
              polylines: [],
              activityCount: 0,
            })
            return
          }

          this.setData({
            loading: false,
            error: false,
            isEmpty: false,
            center: model.center,
            includePoints: model.focusPoints,
            polylines: model.polylines,
            activityCount: activityCount,
          })
        })
        .catch(() => {
          this.setData({ loading: false, error: true, isEmpty: false })
        })
    },

    _retryFetch() {
      this._fetchHeatmap()
    },

    _openFullScreen() {
      var userQuery = this.data.userId > 0 ? '?userId=' + this.data.userId : ''
      wx.navigateTo({ url: '/pages/heatmap/heatmap' + userQuery })
    },
  },
})
