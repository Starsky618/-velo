const api = require('../../utils/api')
// 格式化函数抽到 utils/meetup-format.js（约骑三页单一真相源），不再各页各抄一份
const { formatDistance, formatClimb, formatTime, paceText } = require('../../utils/meetup-format')

function decorateMeetup(meetup) {
  if (!meetup) return null
  var count = meetup.participants_count || 0
  var max = meetup.max_participants || 0
  var full = max > 0 && count >= max
  var isOpen = meetup.status === 'OPEN'
  // 距出发还有 >30 分钟才允许操作（和后端 cutoff 一致：临开始不让取消/加入/退出，保护已报名的人）
  var startMs = new Date(meetup.start_time).getTime()
  // 和后端 cutoff 完全对齐（start - 30min30s），否则那 30 秒窗口前端按钮亮、点了后端却 410
  var beforeCutoff = !isNaN(startMs) && startMs - Date.now() > (30 * 60 + 30) * 1000
  return Object.assign({}, meetup, {
    startText: formatTime(meetup.start_time),
    endText: formatTime(meetup.estimated_end_time),
    distanceText: formatDistance(meetup.snapshot_distance),
    climbText: formatClimb(meetup.snapshot_climb),
    paceText: paceText(meetup.pace_level),
    seatsText: count + '/' + max,
    // 按身份显示唯一一个操作按钮：发起人→取消 / 已加入→退出 / 没加入且没满→加入
    canCancel: meetup.is_creator && isOpen && beforeCutoff,
    canLeave: !meetup.is_creator && meetup.has_joined && isOpen && beforeCutoff,
    canJoin: !meetup.is_creator && !meetup.has_joined && isOpen && beforeCutoff && !full,
    // 没有可操作按钮时显示的状态文案（已取消/已结束/已满员/即将出发）
    statusHint: meetup.status === 'CANCELLED' ? '已取消'
      : meetup.status === 'COMPLETED' ? '已结束'
      : (isOpen && full && !meetup.has_joined && !meetup.is_creator) ? '已满员'
      : (isOpen && !beforeCutoff) ? '即将出发'
      : '',
  })
}

Page({
  data: {
    meetupId: null,
    meetup: null,
    loading: true,
    joining: false,
    mediaList: [], // 照片墙：每项含 url（拼好的可显示地址）+ isVideo
    mediaError: false, // 照片墙加载失败标记：true 时显示"加载失败"而非"还没有照片"，避免误导
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
        that.loadMedia()
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
    // guard 用 canJoin（已含未满/未过cutoff/未加入），和按钮显示条件一致，不再用旧的 full 判断
    if (this.data.joining || !(this.data.meetup && this.data.meetup.canJoin)) return
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
    if (this.data.joining || !(this.data.meetup && this.data.meetup.canLeave)) return
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

  onTapCancel: function () {
    var that = this
    if (this.data.joining || !(this.data.meetup && this.data.meetup.canCancel)) return
    // 取消是破坏性操作（参与者会看不到这场约骑），二次确认防误触
    wx.showModal({
      title: '取消约骑',
      content: '取消后参与者就看不到这场约骑了，确定取消？',
      confirmText: '取消约骑',
      confirmColor: '#ff2d55',
      cancelText: '再想想',
      success: function (modal) {
        if (!modal.confirm) return
        that.setData({ joining: true })
        api.cancelMeetup(that.data.meetupId)
          .then(function (res) {
            that.setData({ meetup: decorateMeetup(res) })
            wx.showToast({ title: '已取消', icon: 'success' })
          })
          .catch(function (err) {
            wx.showToast({ title: (err && err.message) || '取消失败', icon: 'none' })
          })
          .finally(function () {
            that.setData({ joining: false })
          })
      },
    })
  },

  // 照片墙：拉所有媒体，拼成可显示 URL（baseUrl + /uploads/ + file_id，caddy 静态服务）
  loadMedia: function () {
    var that = this
    api.getMeetupMedia(this.data.meetupId)
      .then(function (list) {
        var base = (getApp().globalData && getApp().globalData.baseUrl) || ''
        that.setData({
          mediaError: false,
          mediaList: (list || []).map(function (m) {
            return Object.assign({}, m, { url: base + '/uploads/' + m.file_id, isVideo: m.type === 'video' })
          }),
        })
      })
      .catch(function (err) {
        // 加载失败不阻塞详情主信息，但必须让用户知道是"加载失败"而非"还没有照片"——
        // 否则接口 401/500、图片域名没配 https 等任何失败都被吞成"没人发照片"，误导用户。
        console.error('照片墙加载失败', err)
        that.setData({ mediaError: true })
      })
  },

  // 仅 creator：微信选图/视频 → 逐个上传 → 刷新照片墙
  onTapAddMedia: function () {
    var that = this
    wx.chooseMedia({
      count: 9,
      mediaType: ['image', 'video'],
      success: function (res) {
        wx.showLoading({ title: '上传中', mask: true })
        var tasks = res.tempFiles.map(function (f) {
          return api.uploadMeetupMedia(that.data.meetupId, f.tempFilePath).catch(function () { return null })
        })
        Promise.all(tasks)
          .then(function (results) {
            if (results.some(function (r) { return r === null })) {
              wx.showToast({ title: '部分上传失败', icon: 'none' })
            }
            that.loadMedia()
          })
          .finally(function () {
            wx.hideLoading()
          })
      },
    })
  },

  onTapDeleteMedia: function (event) {
    var that = this
    var mediaId = event.currentTarget.dataset.id
    wx.showModal({
      title: '删除',
      content: '删除这张照片/视频？',
      success: function (modal) {
        if (!modal.confirm) return
        api.deleteMeetupMedia(that.data.meetupId, mediaId)
          .then(function () { that.loadMedia() })
          .catch(function (err) { wx.showToast({ title: (err && err.message) || '删除失败', icon: 'none' }) })
      },
    })
  },

  // 点图全屏预览（只在图片间预览，视频不进 previewImage）
  onTapPreviewMedia: function (event) {
    var url = event.currentTarget.dataset.url
    var images = this.data.mediaList.filter(function (m) { return !m.isVideo }).map(function (m) { return m.url })
    if (images.indexOf(url) >= 0) {
      wx.previewImage({ current: url, urls: images })
    }
  },
})
