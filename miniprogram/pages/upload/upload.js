/**
 * 上传页 — 整个 App 的核心入口
 *
 * 想象成一个"投递口"：
 * 用户把 GPX 文件丢进来，系统自动解析出骑行数据。
 *
 * 状态机：idle → confirming → uploading → polling → done / error
 * 每个状态对应一种 UI，用户一步步往前走。
 */

const api = require('../../utils/api')
const app = getApp()

Page({
  data: {
    // 状态机：idle / confirming / uploading / polling / done / error
    step: 'idle',
    // 选中的文件信息
    fileName: '',
    filePath: '',
    fileSize: 0,
    // 上传和解析进度
    statusText: '',
    // 解析结果（activity 详情）
    activityId: null,
    result: null,
    // 错误信息
    errorMsg: '',
  },

  onShow() {
    // 每次切到上传 tab，如果之前已完成或出错，重置状态
    // 这样用户可以上传下一个文件
  },

  /**
   * 选择文件
   *
   * wx.chooseMessageFile：从微信聊天记录里选文件。
   * 这是骑行者最常用的路径：
   * 码表 App（iGPSport/迈金/佳明）→ 分享 GPX 到微信 → 在小程序里选择这个文件
   */
  chooseFile() {
    var that = this
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['gpx'],
      success: function (res) {
        var file = res.tempFiles[0]
        that.setData({
          step: 'confirming',
          fileName: file.name,
          filePath: file.path,
          fileSize: file.size,
          fileSizeKB: Math.round(file.size / 1024),
        })
      },
      fail: function () {
        // 用户取消选择，不做任何处理
      },
    })
  },

  /**
   * 取消上传，回到初始状态
   */
  cancel() {
    this.setData({
      step: 'idle',
      fileName: '',
      filePath: '',
      fileSize: 0,
      errorMsg: '',
    })
  },

  /**
   * 确认上传 → 发送文件到服务器 → 轮询解析状态
   */
  startUpload() {
    var that = this

    // 检查登录状态
    if (!app.globalData.token) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }

    this.setData({ step: 'uploading', statusText: '正在上传文件...' })

    // 第一步：上传文件
    api.upload('/api/activities/upload', this.data.filePath, 'file')
      .then(function (data) {
        // 上传成功，拿到 activity_id，开始轮询解析状态
        that.setData({
          activityId: data.activity_id,
          step: 'polling',
          statusText: '正在解析 GPX 数据...',
        })
        that.pollStatus(data.activity_id)
      })
      .catch(function (err) {
        that.setData({
          step: 'error',
          errorMsg: err.message || '上传失败',
        })
      })
  },

  /**
   * 轮询解析状态
   *
   * 每 2 秒问一次后端"解析完了吗？"，直到 completed 或 failed。
   * 就像快递查询：每隔一会儿刷一下"到哪了"。
   *
   * 超时保护：最多轮询 60 次（2 分钟），防止无限等待。
   */
  pollStatus(activityId) {
    var that = this
    var attempts = 0
    var maxAttempts = 60

    var timer = setInterval(function () {
      attempts++

      api.get('/api/activities/' + activityId + '/status')
        .then(function (data) {
          if (data.status === 'completed') {
            clearInterval(timer)
            // Sprint 5 task-2 dedupe：检测到与已有骑行重复 → toast + 跳转到主活动
            // duplicate_of 非空表示后端 dedupe 算法判定本上传是重复（同时间 / 同轨迹 / 同地点）
            // 主活动是数据更全的那份（带功率/心率/踏频或数据点更多），用户体验上看一条更优
            if (data.duplicate_of) {
              wx.showToast({
                title: '已合并到已有骑行',
                icon: 'none',
                duration: 2500,
              })
              setTimeout(function () {
                wx.redirectTo({
                  url: '/pages/detail/detail?id=' + data.duplicate_of,
                })
              }, 1500)
              return
            }
            // 解析完成，获取完整详情
            that.setData({ statusText: '解析完成，加载数据...' })
            that.fetchResult(activityId)
          } else if (data.status === 'failed') {
            // 解析失败
            clearInterval(timer)
            that.setData({
              step: 'error',
              errorMsg: data.error_message || '解析失败，请重试',
            })
          } else {
            // 还在处理中，更新提示文字
            var dots = '.'.repeat((attempts % 3) + 1)
            that.setData({
              statusText: '正在解析 GPX 数据' + dots,
            })
          }
        })
        .catch(function () {
          // 网络错误不中断轮询，等下次重试
        })

      // 超时保护
      if (attempts >= maxAttempts) {
        clearInterval(timer)
        that.setData({
          step: 'error',
          errorMsg: '解析超时，请稍后在首页查看结果',
        })
      }
    }, 2000)

    // 保存 timer 引用，页面销毁时清理
    this._pollTimer = timer
  },

  /**
   * 获取解析完成后的完整数据
   */
  fetchResult(activityId) {
    var that = this
    api.get('/api/activities/' + activityId)
      .then(function (data) {
        // WXML 模板不支持 .toFixed()，在 JS 层预计算格式化数据
        var durationMin = data.duration ? Math.round(data.duration / 60) : 0
        // 平均功率 / 心率 / 踏频统一取整：DB 存 Float 但展示层不要小数
        if (data.avg_power != null) data.avg_power = Math.round(data.avg_power)
        if (data.avg_hr != null) data.avg_hr = Math.round(data.avg_hr)
        if (data.avg_cadence != null) data.avg_cadence = Math.round(data.avg_cadence)
        that.setData({
          step: 'done',
          result: data,
          durationMin: durationMin,
        })
      })
      .catch(function (err) {
        that.setData({
          step: 'error',
          errorMsg: err.message || '获取数据失败',
        })
      })
  },

  /**
   * 查看详情 → 跳转到详情页
   */
  viewDetail() {
    wx.navigateTo({
      url: '/pages/detail/detail?id=' + this.data.activityId,
    })
  },

  /**
   * 重新上传（从 done 或 error 状态回到 idle）
   */
  reset() {
    this.setData({
      step: 'idle',
      fileName: '',
      filePath: '',
      fileSize: 0,
      statusText: '',
      activityId: null,
      result: null,
      errorMsg: '',
    })
  },

  /**
   * 页面卸载时清理轮询定时器，防止内存泄漏
   */
  onUnload() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer)
    }
  },
})
