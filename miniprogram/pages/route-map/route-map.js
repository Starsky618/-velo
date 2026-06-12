Page({
  data: {
    title: '路线地图',
    error: '',
    center: { latitude: 37.8706, longitude: 112.5489 },
    markers: [],
    polylines: [],
    includePoints: [],
  },

  onLoad: function () {
    var app = getApp()
    var payload = app && app.globalData && app.globalData.pendingRouteMap
    // 寄存柜约定"取即清空"（与 pendingMapPoint 同规矩）：防止本页被非正常路径
    // 再次打开时，展示上一条路线的陈旧数据
    if (app && app.globalData) {
      app.globalData.pendingRouteMap = null
    }
    if (!payload || !Array.isArray(payload.includePoints) || payload.includePoints.length < 2) {
      this.setData({ error: '路线暂时不可用' })
      return
    }
    this.setData({
      title: payload.title || '路线地图',
      center: payload.center || payload.includePoints[0],
      markers: Array.isArray(payload.markers) ? payload.markers : [],
      polylines: Array.isArray(payload.polylines) ? payload.polylines : [],
      includePoints: payload.includePoints,
    })
  },

  onTapBack: function () {
    wx.navigateBack()
  },
})
