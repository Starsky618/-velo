/**
 * RIDEMAP 小程序入口文件
 *
 * 这是整个小程序的"总开关"——小程序启动时第一个执行的文件。
 * 职责：
 * 1. 管理全局状态（登录信息、用户数据）
 * 2. 提供全局登录方法，供各页面调用
 *
 * 可以把它想象成一栋大楼的物业管理处：
 * 住户（页面）有事找物业（getApp()）拿公共信息，
 * 物业不管每户内部怎么装修，只管公共事务。
 */

App({
  globalData: {
    // 后端 API 地址（当前用 IP 直连，备案后换域名）
    baseUrl: 'http://114.132.190.245',
    // JWT token，登录后存这里，所有请求带上它证明身份
    token: null,
    // 当前用户信息（profile 接口返回的数据）
    userInfo: null,
  },

  onLaunch() {
    // 小程序启动时执行
    // 先从本地缓存恢复 token（用户关了再开不用重新登录）
    const token = wx.getStorageSync('token')
    if (token) {
      this.globalData.token = token
    }
  },

  /**
   * 微信登录全流程
   *
   * 完整链路：
   * wx.login() 拿临时 code → POST /api/user/login 换 JWT token → 存本地缓存
   *
   * 返回 Promise，调用方可以 .then() 拿到 { token, user_id, is_new_user }
   */
  login() {
    return new Promise((resolve, reject) => {
      // 第一步：调微信接口拿临时 code
      wx.login({
        success: (loginRes) => {
          if (!loginRes.code) {
            reject(new Error('wx.login 失败：未获取到 code'))
            return
          }

          // 第二步：把 code 发给后端换 JWT token
          // 在这里 require 而不是文件顶部，避免循环依赖：
          // app.js require api.js → api.js 调 getApp() → App 还没创建完 → 爆炸
          var api = require('./utils/api')
          api.post('/api/user/login', { code: loginRes.code })
            .then((data) => {
              // 第三步：存 token（内存 + 本地缓存双保险）
              this.globalData.token = data.token
              wx.setStorageSync('token', data.token)
              resolve(data)
            })
            .catch((err) => {
              reject(err)
            })
        },
        fail: (err) => {
          reject(new Error('wx.login 调用失败'))
        },
      })
    })
  },

  /**
   * 退出登录：清除 token 和用户信息
   */
  logout() {
    this.globalData.token = null
    this.globalData.userInfo = null
    wx.removeStorageSync('token')
  },
})
