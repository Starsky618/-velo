/**
 * 账号与数据 —— 低频账号操作的二级页。
 *
 * 退出登录保留账号和云端数据；注销账号沿用原设置页的两次确认和后端删除合同。
 */

const api = require('../../utils/api')
const app = getApp()

function clearLocalSession() {
  if (app && typeof app.logout === 'function') {
    app.logout()
    return
  }
  wx.removeStorageSync('token')
  wx.removeStorageSync('userId')
  if (app) {
    app.globalData.token = null
    app.globalData.userId = 0
    app.globalData.userInfo = null
  }
}

Page({
  onShow() {
    if (!app.globalData.token) {
      wx.reLaunch({ url: '/pages/profile/profile' })
    }
  },

  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需要重新登录才能查看个人数据。',
      confirmText: '退出',
      confirmColor: '#e64340',
      cancelText: '取消',
      success: function (res) {
        if (!res.confirm) return
        clearLocalSession()
        wx.reLaunch({ url: '/pages/profile/profile' })
      },
    })
  },

  onDeleteAccount() {
    wx.showModal({
      title: '注销账号',
      content: '将永久删除账号、骑行、赛段成绩、功率、训练与授权数据。你创建的路书都会解除关联后保留；已开放约骑会取消并解除关联后保留。确定继续吗？',
      confirmText: '继续',
      confirmColor: '#e64340',
      cancelText: '取消',
      success: function (res) {
        if (!res.confirm) return
        wx.showModal({
          title: '最后确认',
          content: '注销无法撤销。请先处理可自助删除的内容；需删除已开放约骑，请通过官网隐私邮箱申请。',
          confirmText: '确认注销',
          confirmColor: '#e64340',
          cancelText: '再想想',
          success: function (res2) {
            if (!res2.confirm) return
            wx.showLoading({ title: '注销中', mask: true })
            api.deleteAccount()
              .then(function () {
                wx.hideLoading()
                clearLocalSession()
                wx.showToast({ title: '账号已注销', icon: 'success' })
                setTimeout(function () {
                  wx.reLaunch({ url: '/pages/profile/profile' })
                }, 800)
              })
              .catch(function (err) {
                wx.hideLoading()
                if (err && err.code === 401) {
                  clearLocalSession()
                  wx.reLaunch({ url: '/pages/profile/profile' })
                  return
                }
                wx.showToast({ title: (err && err.message) || '注销失败，请重试', icon: 'none' })
              })
          },
        })
      },
    })
  },
})
