/**
 * 个人中心页 — 用户的"仪表盘"
 *
 * 想象成骑行者的"个人成就墙"：
 * - 未登录：显示登录按钮
 * - 已登录：显示昵称、累计统计、FTP/体重等信息
 *
 * 登录流程：
 * 点击按钮 → app.login() → 拿到 token → 获取 profile + stats → 刷新页面
 */

const api = require('../../utils/api')
const app = getApp()

Page({
  data: {
    isLoggedIn: false,
    loading: false,
    // 用户资料（来自 GET /api/user/profile）
    profile: null,
    // 骑行统计（来自 GET /api/user/stats?period=all）
    stats: null,
  },

  /**
   * onShow 而不是 onLoad：
   * 每次切到"我的"tab 都检查登录状态并刷新数据。
   * onLoad 只在页面首次创建时触发一次，
   * onShow 每次页面显示都会触发（包括从其他 tab 切回来）。
   */
  onShow() {
    if (app.globalData.token) {
      this.setData({ isLoggedIn: true })
      this.fetchUserData()
    } else {
      this.setData({ isLoggedIn: false, profile: null, stats: null })
    }
  },

  /**
   * 点击"微信一键登录"按钮
   */
  handleLogin() {
    // 防止重复点击
    if (this.data.loading) return
    this.setData({ loading: true })

    wx.showLoading({ title: '登录中...' })

    app.login()
      .then((loginData) => {
        this.setData({ isLoggedIn: true })
        // 登录成功后立即获取用户数据
        return this.fetchUserData()
      })
      .then(() => {
        wx.hideLoading()
        wx.showToast({ title: '登录成功', icon: 'success' })
      })
      .catch((err) => {
        wx.hideLoading()
        wx.showToast({
          title: err.message || '登录失败',
          icon: 'none',
        })
      })
      .finally(() => {
        this.setData({ loading: false })
      })
  },

  /**
   * 获取用户资料和统计数据
   *
   * 两个请求并行发出（不用等 profile 返回再发 stats），
   * 就像同时寄两封信，不用等第一封回信再寄第二封。
   */
  fetchUserData() {
    const profileReq = api.get('/api/user/profile')
      .then((data) => {
        app.globalData.userInfo = data
        // WXML 模板不支持 .toFixed() 方法调用，所以在 JS 层算好 W/kg
        const wpkg = (data.ftp && data.weight)
          ? (data.ftp / data.weight).toFixed(1)
          : null
        this.setData({ profile: data, wpkg: wpkg })
      })
      .catch((err) => {
        // 401 说明 token 过期，清除登录状态
        if (err.code === 401) {
          app.logout()
          this.setData({ isLoggedIn: false, profile: null, stats: null })
        }
      })

    const statsReq = api.get('/api/user/stats?period=all')
      .then((data) => {
        this.setData({ stats: data })
      })
      .catch(() => {
        // 统计获取失败不影响页面展示，静默处理
      })

    return Promise.all([profileReq, statsReq])
  },

  /**
   * 退出登录
   */
  handleLogout() {
    wx.showModal({
      title: '确认退出',
      content: '退出后需要重新登录',
      success: (res) => {
        if (res.confirm) {
          app.logout()
          this.setData({ isLoggedIn: false, profile: null, stats: null })
          wx.showToast({ title: '已退出', icon: 'success' })
        }
      },
    })
  },
})
