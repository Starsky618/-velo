const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    error: '',
    webUrl: '',
  },

  onLoad(query) {
    const parsed = Number(query && (query.userId || query.user_id))
    this._targetUserId = Number.isInteger(parsed) && parsed > 0 ? parsed : null
    this._openHeatmap()
  },

  _openHeatmap() {
    this.setData({ loading: true, error: '', webUrl: '' })
    const payload = this._targetUserId ? { target_user_id: this._targetUserId } : {}
    api.post('/api/user/me/heatmap/web-session', payload)
      .then((data) => {
        if (!data || !data.url) throw new Error('热图链接缺失')
        this.setData({
          loading: false,
          error: '',
          webUrl: api.resolveUrl(data.url),
        })
      })
      .catch((error) => {
        this.setData({
          loading: false,
          error: (error && error.message) || '热图加载失败',
          webUrl: '',
        })
      })
  },

  onRetry() {
    this._openHeatmap()
  },

  onWebViewError() {
    const suffix = this._targetUserId ? '?userId=' + this._targetUserId : ''
    wx.redirectTo({
      url: '/pages/heatmap/heatmap' + suffix,
      fail: () => {
        this.setData({
          loading: false,
          error: '热图页面加载失败，请检查网络后重试',
          webUrl: '',
        })
      },
    })
  },
})
