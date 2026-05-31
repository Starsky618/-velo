const api = require('../../utils/api')

function formatDistance(value) {
  if (value === undefined || value === null) return ''
  return Number(value).toFixed(1) + ' km'
}

function formatClimb(value) {
  if (value === undefined || value === null) return ''
  return Math.round(Number(value)) + ' m'
}

function formatTime(value) {
  if (!value) return '待定'
  var date = new Date(value)
  if (isNaN(date.getTime())) return value
  var month = date.getMonth() + 1
  var day = date.getDate()
  var hour = String(date.getHours()).padStart(2, '0')
  var minute = String(date.getMinutes()).padStart(2, '0')
  return month + '月' + day + '日 ' + hour + ':' + minute
}

function paceText(value) {
  var map = {
    relaxed: '休闲',
    cruise: '巡航',
    training: '训练',
    race: '强度',
  }
  return map[value] || value || ''
}

Page({
  data: {
    meetups: [],
    page: 1,
    hasMore: true,
    loading: false,
  },

  onLoad: function () {
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
