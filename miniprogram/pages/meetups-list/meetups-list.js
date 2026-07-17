const api = require('../../utils/api')
// 格式化函数抽到 utils/meetup-format.js（约骑三页单一真相源），不再各页各抄一份
const { formatDistance, formatClimb, formatTime, paceText } = require('../../utils/meetup-format')
const routeThumb = require('../../utils/route-thumb')

// 只给升级前没有冻结快照的旧约骑兜底；新约骑直接使用列表响应里的低点数快照。
var trackCache = {}

Page({
  data: {
    meetups: [],
    page: 1,
    hasMore: true,
    loading: false,
  },

  onShow: function () {
    // 列表是底部常驻 tab：用 onShow 而非 onLoad，每次切回（含发布约骑后返回）都刷新，
    // 否则用户发完约骑回到列表看不到自己刚发的那条。loadMeetups 内有 loading 守卫防重入。
    this.loadMeetups(1)
  },

  onPullDownRefresh: function () {
    this.loadMeetups(1, function () {
      wx.stopPullDownRefresh()
    })
  },

  onReachBottom: function () {
    if (this.data.hasMore && !this.data.loading) {
      this.loadMeetups(this.data.page + 1)
    }
  },

  loadMeetups: function (page, done) {
    var that = this
    if (this.data.loading) return
    this.setData({ loading: true })

    api.getMeetupsList({ status: 'OPEN', page: page, page_size: 20 })
      .then(function (res) {
        var items = (res.items || []).map(function (item) {
          var count = item.participants_count || 0
          var max = item.max_participants || 0
          return Object.assign({}, item, {
            timeText: formatTime(item.start_time),
            distanceText: formatDistance(item.snapshot_distance),
            climbText: formatClimb(item.snapshot_climb),
            paceText: paceText(item.pace_level),
            seatsText: count + '/' + max,
            full: max > 0 && count >= max,
          })
        })
        that.setData({
          meetups: page === 1 ? items : that.data.meetups.concat(items),
          page: page,
          hasMore: items.length >= 20,
        }, function () {
          that.loadTracks()
        })
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '加载失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ loading: false })
        if (done) done()
      })
  },

  // 新记录直接画约骑自己的冻结快照，避免私有路书权限让公开约骑丢图，
  // 也避免列表为每张卡再发一次请求。旧记录没有快照时才走原路书兜底。
  loadTracks: function () {
    var that = this
    this.data.meetups.forEach(function (item) {
      if (item.hasTrack) return
      if (Array.isArray(item.snapshot_route_points) && item.snapshot_route_points.length >= 2) {
        that.markTrack(item.id, item.snapshot_route_points)
        return
      }
      if (!item.route_book_id || !api.getRouteBookDetail) return
      if (trackCache[item.route_book_id]) {
        that.markTrack(item.id, trackCache[item.route_book_id])
        return
      }
      api.getRouteBookDetail(item.route_book_id).then(function (routeBook) {
        var points = routeBook.preview_points || []
        trackCache[item.route_book_id] = points
        that.markTrack(item.id, points)
      }).catch(function () {
        // 路书被删/不可读：这张卡保持无轨迹，列表其余信息照常
      })
    })
  },

  // 按约骑 id 回写 hasTrack 再绘制——异步回来时数组可能已被刷新重建，
  // 所以现场重找下标，找不到（已翻页刷掉）就放弃。
  // ⚠ 绘制坐标 351×110px = wxss .track-canvas 702×220rpx 的一半（旧 canvas API 2:1）
  markTrack: function (meetupId, points) {
    var that = this
    if (!Array.isArray(points) || points.length < 2) return
    var index = -1
    this.data.meetups.forEach(function (m, i) {
      if (m.id === meetupId) index = i
    })
    if (index < 0) return
    var key = 'meetups[' + index + '].hasTrack'
    this.setData({ [key]: true }, function () {
      setTimeout(function () {
        routeThumb.drawRouteThumb('track-' + meetupId, points, {
          width: 351,
          height: 110,
          lineWidth: 2,
        })
      }, 120)
    })
  },

  onTapMeetup: function (event) {
    var id = event.currentTarget.dataset.id
    wx.navigateTo({ url: '/pages/meetup-detail/meetup-detail?id=' + id })
  },

  onTapCreate: function () {
    wx.navigateTo({ url: '/pages/meetup-create/meetup-create' })
  },
})
