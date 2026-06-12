const api = require('../../utils/api')

function formatDistance(value) {
  if (value === undefined || value === null) return ''
  var n = Number(value)
  if (!Number.isFinite(n)) return ''
  return n.toFixed(1) + ' km'
}

function formatClimb(value) {
  if (value === undefined || value === null) return ''
  var n = Number(value)
  if (!Number.isFinite(n)) return ''
  // 数据行走等宽数字节奏（"10.0 km · 561 m"），中文前缀会破坏 mono 对齐
  return Math.round(n) + ' m'
}

function decorateGuide(item) {
  var highlights = Array.isArray(item.highlights) ? item.highlights : []
  var meta = []
  var distance = formatDistance(item.distance)
  var climb = formatClimb(item.climb)
  if (distance) meta.push(distance)
  if (climb) meta.push(climb)
  // 封面相对路径（/uploads/...）拼 baseUrl：域名/IP 切换都不用重灌内容
  var cover = item.cover_url
  if (cover && cover.indexOf('/uploads/') === 0) {
    cover = ((getApp().globalData && getApp().globalData.baseUrl) || '') + cover
  }
  return Object.assign({}, item, {
    firstHighlight: highlights[0] || '',
    metaText: meta.join(' · '),
    coverSrc: cover || '/assets/route-placeholder.svg',
  })
}

Page({
  data: {
    loading: true,
    error: '',
    guides: [],
  },

  onLoad: function () {
    this.fetchGuides()
  },

  onPullDownRefresh: function () {
    this.fetchGuides().finally(function () {
      wx.stopPullDownRefresh()
    })
  },

  fetchGuides: function () {
    var that = this
    this.setData({ loading: true, error: '' })
    return api.get('/api/route-guides')
      .then(function (res) {
        that.setData({
          guides: (res.items || []).map(decorateGuide),
          loading: false,
        })
      })
      .catch(function () {
        that.setData({ loading: false, error: '路线暂时加载失败' })
      })
  },

  openGuide: function (event) {
    var id = event.currentTarget.dataset.id
    if (!id) return
    wx.navigateTo({ url: '/pages/route-detail/route-detail?id=' + id })
  },
})
