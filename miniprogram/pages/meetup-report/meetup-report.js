/**
 * 约骑战报页 — 一场集体骑行的成绩册。
 *
 * 这个页面像班级成绩墙：上面是全班合计，中间贴照片，下面每个人一格。
 * 注意事项：没交卷的人也必须出现灰格；缺失字段直接隐藏，不用横线或占位文案。
 * 数据流：分享/详情页带 id 和可选 token 进来 → 拉详情取标题 → 拉 report 取合计、照片和格子。
 */

const api = require('../../utils/api')

function formatNumber(value, digits) {
  if (value === null || value === undefined || isNaN(Number(value))) return ''
  var n = Number(value)
  return digits === 0 ? String(Math.round(n)) : n.toFixed(digits)
}

function buildUploadPath(meetupId, token) {
  var path = '/pages/upload/upload?meetup_id=' + meetupId
  if (token) path += '&token=' + encodeURIComponent(token)
  return path
}

function decorateCell(cell, meetupId, token) {
  var distanceText = cell.distance_km !== null && cell.distance_km !== undefined
    ? formatNumber(cell.distance_km, 1)
    : ''
  var avgSpeedText = cell.avg_speed !== null && cell.avg_speed !== undefined
    ? formatNumber(cell.avg_speed, 1)
    : ''
  var climbText = cell.climb_m !== null && cell.climb_m !== undefined
    ? formatNumber(cell.climb_m, 0)
    : ''
  return Object.assign({}, cell, {
    distanceText: distanceText,
    avgSpeedText: avgSpeedText,
    climbText: climbText,
    hasDistance: distanceText !== '',
    hasAvgSpeed: avgSpeedText !== '',
    hasClimb: climbText !== '',
    uploadPath: buildUploadPath(meetupId, token),
  })
}

Page({
  data: {
    meetupId: '',
    shareToken: '',
    routeName: '',
    loading: true,
    errorMsg: '',
    totals: null,
    mediaList: [],
    cells: [],
  },

  onLoad: function (options) {
    options = options || {}
    var meetupId = options.id || options.meetup_id || ''
    var token = options.token || ''
    this._sourceParam = options.source || ''
    this.setData({ meetupId: meetupId, shareToken: token })
    this.loadPage()
    wx.showShareMenu({ withShareTicket: true })
  },

  loadPage: function () {
    var that = this
    if (!this.data.meetupId) {
      this.setData({ loading: false, errorMsg: '加载失败' })
      return
    }
    this.setData({ loading: true, errorMsg: '' })
    this.loadDetailTitle()
    api.get('/api/meetups/' + this.data.meetupId + '/report', this.data.shareToken ? { token: this.data.shareToken } : null)
      .then(function (report) {
        that.applyReport(report)
      })
      .catch(function (err) {
        that.setData({ errorMsg: (err && err.message) || '加载失败' })
      })
      .finally(function () {
        that.setData({ loading: false })
      })
  },

  loadDetailTitle: function () {
    var that = this
    var source = this._sourceParam
    this._sourceParam = ''
    api.getMeetupDetail(this.data.meetupId, this.data.shareToken, source)
      .then(function (meetup) {
        that.setData({ routeName: meetup.snapshot_route_name || '' })
      })
      .catch(function () {
        that.setData({ routeName: '' })
      })
  },

  applyReport: function (report) {
    var base = (getApp().globalData && getApp().globalData.baseUrl) || ''
    var mediaList = ((report && report.media) || []).map(function (media) {
      return Object.assign({}, media, {
        url: base + '/uploads/' + media.file_id,
        isVideo: media.type === 'video',
      })
    })
    var cells = ((report && report.cells) || []).map(function (cell) {
      return decorateCell(cell, report.meetup_id, this.data.shareToken)
    }, this)
    this.setData({
      totals: report.totals || null,
      mediaList: mediaList,
      cells: cells,
    })
  },

  onTapSubmit: function (event) {
    var path = event.currentTarget.dataset.path
    if (!path) return
    // upload 是 tabBar 页：navigateTo 跳 tabBar 直接 fail，且 switchTab 带不了 url 参数——
    // 约骑上下文走 globalData 寄存柜（与 pendingMapPoint 同约定），upload 页 onShow 读走即清空
    var app = getApp()
    if (app && app.globalData) {
      app.globalData.pendingUploadMeetup = {
        meetupId: this.data.meetupId,
        token: this.data.shareToken || '',
      }
    }
    wx.switchTab({ url: '/pages/upload/upload' })
  },

  onTapPreviewMedia: function (event) {
    var url = event.currentTarget.dataset.url
    var images = this.data.mediaList.filter(function (item) { return !item.isVideo }).map(function (item) { return item.url })
    if (images.indexOf(url) >= 0) {
      wx.previewImage({ current: url, urls: images })
    }
  },

  onShareAppMessage: function () {
    var totals = this.data.totals || {}
    var title = this.data.routeName ? this.data.routeName + ' 战报' : 'VELO 战报'
    if (totals.submitted_count !== undefined && totals.rider_count !== undefined) {
      title += ' · 已交卷 ' + totals.submitted_count + '/' + totals.rider_count
    }
    var path = '/pages/meetup-report/meetup-report?id=' + this.data.meetupId + '&source=report_card'
    if (this.data.shareToken) path += '&token=' + encodeURIComponent(this.data.shareToken)
    return { title: title, path: path }
  },
})
