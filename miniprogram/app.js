/**
 * VELO 小程序入口文件
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
    // 后端 API 地址（2026-06-12 切回 https 域名）：备案白名单已同步（80 端口 308 跳转实证）、
    // 证书已签发在管（Let's Encrypt 至 2026-09）、Caddy 内测 443 返回业务 401 全链路健康。
    // ⚠ 前置条件 = 腾讯云控制台安全组放行 TCP 443（2026-06-12 诊断的唯一卡点），
    // 没放行前编译运行会全量请求失败。改这里必须同步 api.js 的 BASE_URL（两处一起）。
    baseUrl: 'https://api.weiluai.top',
    // JWT token，登录后存这里，所有请求带上它证明身份
    token: null,
    // 当前用户 ID（轻量 / 登录立刻可用 / 给 isOwner 判断用）
    // 跟 userInfo 不同：userInfo 是 profile tab 主动激活后才拉的完整信息（昵称/头像/统计）
    // userId 是登录后第一时间就有 → detail 页 isOwner 判断不依赖 profile tab 被打开过
    userId: 0,
    // 当前用户完整信息（profile 接口返回的数据 / 仅 profile tab 激活后才有）
    userInfo: null,
    // 自研地图选点页返回创建页时的临时寄存位。
    // 它像前台临时寄存柜：map-picker 写一次，meetup-create 读走后立刻清空，避免下次误用旧点。
    pendingMapPoint: null,
  },

  onLaunch() {
    // 小程序启动时执行
    // 先从本地缓存恢复 token + userId（用户关了再开不用重新登录 / isOwner 也能立刻判断）
    const token = wx.getStorageSync('token')
    if (token) {
      this.globalData.token = token
    }
    const userId = wx.getStorageSync('userId')
    if (userId) {
      this.globalData.userId = userId
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
      console.log('[app.login] step A: calling wx.login()')
      // 第一步：调微信接口拿临时 code
      wx.login({
        success: (loginRes) => {
          console.log('[app.login] step B: wx.login success / code =', loginRes && loginRes.code ? loginRes.code.substring(0, 10) + '...' : 'EMPTY')
          if (!loginRes.code) {
            reject(new Error('wx.login 失败：未获取到 code'))
            return
          }

          // 第二步：把 code 发给后端换 JWT token
          // 在这里 require 而不是文件顶部，避免循环依赖：
          // app.js require api.js → api.js 调 getApp() → App 还没创建完 → 爆炸
          var api = require('./utils/api')
          console.log('[app.login] step C: calling POST /api/user/login')
          api.post('/api/user/login', { code: loginRes.code })
            .then((data) => {
              console.log('[app.login] step D: POST /api/user/login success', data)
              // 第三步：存 token + userId（内存 + 本地缓存双保险）
              // userId 给 isOwner 判断用（detail 页 task-4.6 隐私入口 / 不等 profile tab 激活）
              this.globalData.token = data.token
              this.globalData.userId = data.user_id || 0
              wx.setStorageSync('token', data.token)
              if (data.user_id) wx.setStorageSync('userId', data.user_id)
              resolve(data)
            })
            .catch((err) => {
              console.error('[app.login] step D FAIL: POST /api/user/login rejected', err)
              reject(err)
            })
        },
        fail: (err) => {
          console.error('[app.login] step B FAIL: wx.login itself failed', err)
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
    this.globalData.userId = 0
    this.globalData.userInfo = null
    wx.removeStorageSync('token')
    wx.removeStorageSync('userId')
  },
})
