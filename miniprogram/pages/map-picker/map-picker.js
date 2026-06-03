const mapTheme = require('../../utils/map-theme')

const DEFAULT_CENTER = { latitude: 37.8706, longitude: 112.5489 }

function normalizeKind(kind) {
  return kind === 'end' ? 'end' : 'start'
}

function finiteNumber(value, fallback) {
  var n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function safeDecode(value) {
  if (!value) return ''
  try {
    return decodeURIComponent(value)
  } catch (err) {
    return ''
  }
}

Page({
  data: Object.assign({}, mapTheme.getPaperMapData(), {
    kind: 'start',
    title: '选择起点',
    confirmText: '确认起点',
    name: '',
    latitude: DEFAULT_CENTER.latitude,
    longitude: DEFAULT_CENTER.longitude,
  }),

  onLoad: function (options) {
    var kind = normalizeKind(options && options.kind)
    var title = kind === 'start' ? '选择起点' : '选择终点'
    var confirmText = kind === 'start' ? '确认起点' : '确认终点'
    this.setData({
      kind: kind,
      title: title,
      confirmText: confirmText,
      name: safeDecode(options && options.name),
      latitude: finiteNumber(options && options.latitude, DEFAULT_CENTER.latitude),
      longitude: finiteNumber(options && options.longitude, DEFAULT_CENTER.longitude),
    })
    wx.setNavigationBarTitle({ title: title })
  },

  onReady: function () {
    this.mapContext = wx.createMapContext('picker-map')
  },

  onRegionChange: function (event) {
    if (!event || event.type !== 'end') return
    this.refreshCenter()
  },

  onNameInput: function (event) {
    this.setData({ name: event.detail.value })
  },

  refreshCenter: function (done) {
    var that = this
    var context = this.mapContext || wx.createMapContext('picker-map')
    context.getCenterLocation({
      success: function (res) {
        var point = {
          latitude: finiteNumber(res.latitude, that.data.latitude),
          longitude: finiteNumber(res.longitude, that.data.longitude),
        }
        that.setData(point)
        if (done) done(point)
      },
      fail: function () {
        var fallback = {
          latitude: that.data.latitude,
          longitude: that.data.longitude,
        }
        if (done) done(fallback)
      },
    })
  },

  selectMapPoint: function () {
    var that = this
    this.refreshCenter(function (center) {
      var app = getApp()
      if (app && app.globalData) {
        app.globalData.pendingMapPoint = {
          kind: that.data.kind,
          latitude: center.latitude,
          longitude: center.longitude,
          name: that.data.name || (that.data.kind === 'start' ? '路线起点' : '路线终点'),
        }
      }
      wx.navigateBack()
    })
  },

  onTapCancel: function () {
    wx.navigateBack()
  },
})
