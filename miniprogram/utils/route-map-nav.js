/**
 * 路线地图跳转助手——把路线数据临时放进全局寄存柜，再打开独立地图页。
 *
 * 为什么不把路线点塞进 URL：一条路线可能有很多点，URL 像一张小纸条，写长了会被微信截断。
 * globalData.pendingRouteMap 像前台临时寄存柜：当前页放进去，route-map 页马上取出来展示。
 */

function hasEnoughPoints(points) {
  return Array.isArray(points) && points.length >= 2
}

function openRouteMapPage(payload) {
  if (!payload || !hasEnoughPoints(payload.includePoints)) {
    wx.showToast({ title: '暂无路线预览', icon: 'none' })
    return
  }
  var app = getApp()
  if (app && app.globalData) {
    app.globalData.pendingRouteMap = {
      title: payload.title || '路线地图',
      center: payload.center || payload.includePoints[0],
      markers: Array.isArray(payload.markers) ? payload.markers : [],
      polylines: Array.isArray(payload.polylines) ? payload.polylines : [],
      includePoints: payload.includePoints,
    }
  }
  wx.navigateTo({ url: '/pages/route-map/route-map' })
}

module.exports = {
  openRouteMapPage,
}
