/**
 * 设置页 — 目前只有"免打扰"本地开关
 *
 * 设计说明：
 * - 免打扰状态存本地（wx.setStorageSync），不上传后端
 *   理由：这是用户端偏好，没必要占数据库
 * - 切换后不需要通知首页——首页 onShow 每次进都会读本地存储刷新
 *
 * 类比：就像手机的"静音"开关——
 * 拨一下开关状态就变，下次拿起手机查看时自然生效，
 * 不需要"通知给手机系统"那种复杂通信。
 */
Page({
  data: {
    muted: false,
  },

  onLoad() {
    // 进页面时从本地存储同步一次当前状态
    // 显式 === true：防止 storage 里是 undefined 或旧版字符串被误判
    var muted = wx.getStorageSync('mute_notifications') === true
    this.setData({ muted: muted })
  },

  /**
   * 切换免打扰开关——同步写本地存储并提示用户。
   */
  onToggleMute(e) {
    // e.detail.value 是 switch 新值；用 === true 严格判
    var muted = e.detail.value === true
    wx.setStorageSync('mute_notifications', muted)
    this.setData({ muted: muted })
    wx.showToast({
      title: muted ? '免打扰已开启' : '免打扰已关闭',
      icon: 'none',
    })
  },
})
