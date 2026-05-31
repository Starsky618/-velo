const api = require('../../utils/api')

function formatNumber(value, unit) {
  if (value === undefined || value === null) return '--'
  return Number(value).toFixed(unit === 'km' ? 1 : 0) + ' ' + unit
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
  return map[value] || value || '--'
}

function decorateMeetup(meetup) {
  if (!meetup) return null
  var count = meetup.participants_count || 0
  var max = meetup.max_participants || 0
  return Object.assign({}, meetup, {
    startText: formatTime(meetup.start_time),
    endText: formatTime(meetup.estimated_end_time),
    distanceText: formatNumber(meetup.snapshot_distance, 'km'),
    climbText: formatNumber(meetup.snapshot_climb, 'm'),
    paceText: paceText(meetup.pace_level),
    seatsText: count + '/' + max,
    full: max > 0 && count >= max,
  })
}

Page({
  data: {
    meetupId: null,
    meetup: null,
    loading: true,
    joining: false,
  },

  onLoad: function (options) {
    this.setData({ meetupId: Number(options.id) })
    this.loadDetail()
  },

  onPullDownRefresh: function () {
    this.loadDetail(function () {
      wx.stopPullDownRefresh()
    })
  },

  loadDetail: function (done) {
    var that = this
    if (!this.data.meetupId) return
    this.setData({ loading: true })
    api.getMeetupDetail(this.data.meetupId)
      .then(function (res) {
        that.setData({ meetup: decorateMeetup(res) })
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '加载失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ loading: false })
        if (done) done()
      })
  },

  onTapJoin: function () {
    var that = this
    if (this.data.joining || (this.data.meetup && this.data.meetup.full)) return
    this.setData({ joining: true })
    api.joinMeetup(this.data.meetupId)
      .then(function (res) {
        that.setData({ meetup: decorateMeetup(res) })
        wx.showToast({ title: '已加入', icon: 'success' })
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '加入失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ joining: false })
      })
  },

  onTapLeave: function () {
    var that = this
    if (this.data.joining) return
    this.setData({ joining: true })
    api.leaveMeetup(this.data.meetupId)
      .then(function (res) {
        that.setData({ meetup: decorateMeetup(res) })
        wx.showToast({ title: '已退出', icon: 'success' })
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '退出失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ joining: false })
      })
  },
})
