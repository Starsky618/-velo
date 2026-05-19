/**
 * 设置页 — 用户的"控制台"（Sprint 6 task-5 大幅扩写）
 *
 * 干啥用：
 *   把三件用户每天不点 / 但关键时刻一定要能点到的事集中管理：
 *   1. 改 FTP（账号资料 / 后续可扩 weight / 车辆等）
 *   2. 解绑 Strava（第三方账号 / 不删历史活动 / 仅停止后续同步）
 *   3. 退出登录（清 token + 跳回 profile）
 *
 * 类比：
 *   手机系统设置——平时不进，要换号/退账/改重要参数时第一时间能找到入口。
 *
 * 数据流：
 *   - onShow：拉 GET /api/user/profile（FTP）+ GET /api/strava/status（bound）
 *   - 改 FTP：wx.showModal editable → PUT /api/user/profile { ftp }
 *   - 解绑 Strava：wx.showModal confirm → POST /api/strava/unbind（204）
 *   - 退出：wx.showModal confirm → app.logout() + wx.redirectTo /profile
 *
 * 红线（v0.2/v0.3 task 卡 / 永久规则）：
 *   - 解绑 / 退出**强制二次确认**（wx.showModal confirm）
 *   - FTP 范围 50-500 前后双重校验（前端拒收 + 后端 422）
 *   - bound 状态走 GET /api/strava/status 的 bound 字段（不从 profile 拉 strava_athlete_id）
 *   - "-" 占位符永久规则：FTP 未设时显示 "未设置"（不是 "-"）
 *
 * 注意事项：
 *   - 进入设置页前已要求登录态（"我的"页设置 icon 仅登录后显示 / task-4）
 *     兜底仍判 app.globalData.token —— 防 deep link 或缓存异常情况
 *   - 二次确认按钮颜色：confirmColor #e64340 (system red) 高对比 / 防误点
 *   - 函数名 onUnbindStrava / onBindStrava 与 wxml bindtap 严格对齐（前端协议自校验 / Sprint 5 task-3 教训）
 */

const api = require('../../utils/api')
const analytics = require('../../utils/analytics')
const app = getApp()

Page({
  data: {
    ftp: null,
    stravaBound: false,
  },

  /**
   * onShow 而不是 onLoad：从子流程（如 Strava 授权回浏览器再回小程序）返回时
   * 也能拉到最新状态。
   */
  onShow() {
    analytics.trackPageView('settings')
    // 兜底：未登录直接跳回 profile（理论上"我的"页设置入口已挡 / 双保险）
    if (!app.globalData.token) {
      wx.redirectTo({ url: '/pages/profile/profile' })
      return
    }
    this._fetchProfile()
    this._fetchStravaStatus()
  },

  /**
   * 拉当前用户 profile（取 FTP 字段）
   * 失败静默处理：进入设置页不应因网络问题阻断主流程 / FTP 显示"未设置"即可
   */
  _fetchProfile() {
    api.get('/api/user/profile')
      .then((p) => {
        // 三审 Important 修：用 != null 不用 ||（防 truthiness 陷阱 / 即使 ftp=0 也不会被当 null）
        // FTP schema 范围 50-500 / 实际 0 不会出现 / 但防御性写法
        this.setData({ ftp: p.ftp != null ? p.ftp : null })
      })
      .catch((err) => {
        if (err && err.code === 401) {
          // token 已被 api.js 清掉 / 跳回 profile
          wx.redirectTo({ url: '/pages/profile/profile' })
        }
      })
  },

  /**
   * 拉 Strava 绑定状态
   * 实证字段：app/strava/service_token.py:71 返字段 = "bound" (boolean / "connected" 别名同义)
   */
  _fetchStravaStatus() {
    api.get('/api/strava/status')
      .then((s) => {
        this.setData({ stravaBound: !!s.bound })
      })
      .catch(() => {
        // 静默：拉不到默认显示"未绑定"，点"绑定"按钮可触发完整 OAuth 流程
      })
  },

  /**
   * 编辑 FTP——wx.showModal editable 唤起原生输入框
   *
   * 校验顺序：
   *   1. 用户取消 → 直接 return（不弹 toast）
   *   2. 解析整数 + 边界 50-500 → 不通过 toast 提示用户
   *   3. PUT 后端 → 后端再次 422 兜底（schema Field ge=50 le=500）
   */
  onEditFtp() {
    const that = this
    wx.showModal({
      title: '编辑 FTP',
      content: '',
      editable: true,
      placeholderText: '请输入 50-500 之间的整数',
      success: function (res) {
        if (!res.confirm) return                 // 用户点取消
        const raw = (res.content || '').trim()
        if (!raw) return                          // 空输入静默忽略
        const ftp = parseInt(raw, 10)
        if (isNaN(ftp) || ftp < 50 || ftp > 500) {
          wx.showToast({ title: 'FTP 范围 50-500', icon: 'none' })
          return
        }
        api.put('/api/user/profile', { ftp: ftp })
          .then(function () {
            that.setData({ ftp: ftp })
            wx.showToast({ title: 'FTP 已更新', icon: 'success' })
          })
          .catch(function (err) {
            wx.showToast({
              title: (err && err.message) || '更新失败',
              icon: 'none',
            })
          })
      },
    })
  },

  /**
   * 解绑 Strava——强制二次确认（红线）
   *
   * 后端契约：POST /api/strava/unbind → 204 No Content（同事务清 4 字段 + active import → paused）
   * 历史 activities 保留 / 不会被删
   */
  onUnbindStrava() {
    const that = this
    wx.showModal({
      title: '解绑 Strava',
      content: '解绑后历史活动保留，但不再自动同步新活动。如需重新同步，可再次绑定。',
      confirmText: '解绑',
      confirmColor: '#e64340',           // system red / 提示危险操作
      cancelText: '取消',
      success: function (res) {
        if (!res.confirm) return          // 用户点取消 / 不执行
        api.post('/api/strava/unbind', {})
          .then(function () {
            that.setData({ stravaBound: false })
            wx.showToast({ title: '已解绑', icon: 'success' })
          })
          .catch(function (err) {
            wx.showToast({
              title: (err && err.message) || '解绑失败，请重试',
              icon: 'none',
            })
          })
      },
    })
  },

  /**
   * 绑定 Strava——Sprint 6 task-4 三次 hotfix / Tim 2026-05-16 真用拍
   *
   * 旧流程：复制 URL → 切微信传输助手 → 粘贴 → 浏览器打开（用户嫌麻烦）
   * 新流程：拿 authorize_url → 跳本地 web-view 页直接打开 Strava 授权
   *        用户在小程序内授权完 → 后端 callback 返成功 HTML → 用户左上返回 settings
   *        settings.onShow 自动拉新 bound 状态
   *
   * 前置：小程序公众平台业务域名加 https://www.strava.com + https://114.132.190.245
   *      开发版可工具勾选"不校验合法域名"临时跳过
   */
  onBindStrava() {
    wx.showLoading({ title: '准备授权链接…' })
    api.get('/api/strava/authorize')
      .then((data) => {
        wx.hideLoading()
        const url = data && data.authorize_url
        if (!url) {
          wx.showToast({ title: '后端未返链接', icon: 'none' })
          return
        }
        // 跳 web-view 页 / 用户在小程序内完成 Strava OAuth
        wx.navigateTo({
          url: '/pages/strava-auth/strava-auth?url=' + encodeURIComponent(url),
          fail: (err) => {
            console.error('[settings] navigate strava-auth failed', err)
            // 兜底：navigate 失败仍走旧复制流程
            wx.setClipboardData({
              data: url,
              success: () => {
                wx.showModal({
                  title: '请复制链接到浏览器',
                  content: '链接已复制 / 跳转 web-view 失败 / 请手动粘贴打开授权',
                  showCancel: false,
                })
              },
            })
          },
        })
      })
      .catch(function (err) {
        wx.hideLoading()
        if (err && err.code === 401) return
        wx.showToast({
          title: (err && err.message) || '获取授权链接失败',
          icon: 'none',
        })
      })
  },

  /**
   * 退出登录——强制二次确认（红线）
   *
   * 流程：
   *   1. wx.showModal confirm（confirmColor 红色 / 提示后果）
   *   2. 用户确认 → app.logout()（清 token / userId / userInfo）
   *   3. wx.redirectTo 跳回 profile 页（"我的"页未登录态显示"微信一键登录"）
   *
   * 注意：用 redirectTo 不用 navigateTo / switchTab：
   *   - settings 不在 tabBar 里 / navigateBack 不合适（栈里上一页就是 profile）
   *   - redirectTo 关闭当前页 + 跳新页 / 防止用户回退按钮回到已退出状态的 settings
   */
  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需要重新登录才能查看个人数据。',
      confirmText: '退出',
      confirmColor: '#e64340',
      cancelText: '取消',
      success: function (res) {
        if (!res.confirm) return
        if (app && typeof app.logout === 'function') {
          app.logout()                    // 清 globalData.token / userId / userInfo + storage
        } else {
          // 兜底：app.logout 不存在时手动清（防 app.js 未来重构丢失方法）
          wx.removeStorageSync('token')
          wx.removeStorageSync('userId')
          if (app) {
            app.globalData.token = null
            app.globalData.userId = 0
            app.globalData.userInfo = null
          }
        }
        wx.redirectTo({ url: '/pages/profile/profile' })
      },
    })
  },
})
