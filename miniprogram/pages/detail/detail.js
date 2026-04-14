/**
 * 骑行详情页 — 一次骑行的"完整报告"
 *
 * 从上传完成页或首页的骑行列表点进来，
 * 通过 URL 参数 ?id=xxx 拿到 activity_id，
 * 再调接口获取完整数据展示。
 *
 * 类比：如果首页是"成绩公告栏"，这里就是"详细成绩单"。
 */

const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    activity: null,
    // 格式化后的时长（方便 wxml 直接显示）
    durationText: '',
    // 格式化后的日期
    dateText: '',
  },

  onLoad(options) {
    if (options.id) {
      this.fetchDetail(options.id)
    }
  },

  fetchDetail(id) {
    var that = this
    api.get('/api/activities/' + id)
      .then(function (data) {
        that.setData({
          loading: false,
          activity: data,
          durationText: that.formatDuration(data.duration),
          dateText: that.formatDate(data.started_at || data.created_at),
        })
      })
      .catch(function (err) {
        that.setData({ loading: false })
        wx.showToast({
          title: err.message || '加载失败',
          icon: 'none',
        })
      })
  },

  /**
   * 秒数转为"1:32:14"格式
   */
  formatDuration(seconds) {
    if (!seconds) return '0:00'
    var h = Math.floor(seconds / 3600)
    var m = Math.floor((seconds % 3600) / 60)
    var s = seconds % 60
    if (h > 0) {
      return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
    }
    return m + ':' + String(s).padStart(2, '0')
  },

  /**
   * ISO 日期转为"2026-04-14 16:30"格式
   */
  formatDate(isoStr) {
    if (!isoStr) return ''
    var d = new Date(isoStr)
    var month = String(d.getMonth() + 1).padStart(2, '0')
    var day = String(d.getDate()).padStart(2, '0')
    var hour = String(d.getHours()).padStart(2, '0')
    var min = String(d.getMinutes()).padStart(2, '0')
    return d.getFullYear() + '-' + month + '-' + day + ' ' + hour + ':' + min
  },

  /**
   * 返回上一页
   */
  goBack() {
    wx.navigateBack()
  },
})
