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
  return '爬升 ' + Math.round(n) + ' m'
}

function decorateGuide(item) {
  var highlights = Array.isArray(item.highlights) ? item.highlights : []
  var meta = []
  var distance = formatDistance(item.distance)
  var climb = formatClimb(item.climb)
  if (distance) meta.push(distance)
  if (climb) meta.push(climb)
  return Object.assign({}, item, {
    firstHighlight: highlights[0] || '',
    metaText: meta.join(' · '),
    coverSrc: item.cover_url || '/assets/route-placeholder.svg',
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
