const api = require('../../utils/api')
// 格式化函数抽到 utils/meetup-format.js（约骑三页单一真相源），不再各页各抄一份
const { formatDistance, formatClimb, formatTime, paceText } = require('../../utils/meetup-format')

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

  onTapMeetup: function (event) {
    var id = event.currentTarget.dataset.id
    wx.navigateTo({ url: '/pages/meetup-detail/meetup-detail?id=' + id })
  },

  onTapCreate: function () {
    wx.navigateTo({ url: '/pages/meetup-create/meetup-create' })
  },
})
