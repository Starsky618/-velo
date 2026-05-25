/**
 * 训练结构页 —— 展示最近 6 周训练时间怎么分布。
 *
 * 数据来源：GET /api/training/distribution?range=6w
 * 页面只展示后端给的判断、文案和分布数据，不从活动列表自己拼结果。
 */
const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    loadError: false,
    dataComplete: false,
    insufficientPower: false,
    distribution: null,
    groups: [],
    rawZones: [],
    actions: [],
    weekPlan: [],
  },

  onLoad() {
    this.fetchDistribution()
  },

  onPullDownRefresh() {
    this.fetchDistribution().finally(function () {
      wx.stopPullDownRefresh()
    })
  },

  fetchDistribution() {
    const that = this
    this.setData({ loading: true, loadError: false })

    return api.get('/api/training/distribution', { range: '6w' })
      .then(function (res) {
        const dataComplete = !!(res && res.data_complete)
        const insufficientPower = !!(res && res.insufficient_power_data)
        that.setData({
          loading: false,
          loadError: false,
          dataComplete: dataComplete,
          insufficientPower: insufficientPower,
          distribution: res || null,
          groups: res && Array.isArray(res.groups) ? res.groups : [],
          rawZones: res && Array.isArray(res.raw_zones) ? res.raw_zones : [],
          actions: res && Array.isArray(res.actions) ? res.actions : [],
          weekPlan: res && Array.isArray(res.week_plan) ? res.week_plan : [],
        })
      })
      .catch(function (err) {
        console.error('[training-distribution] fetch failed', err)
        that.setData({
          loading: false,
          loadError: true,
          distribution: null,
          groups: [],
          rawZones: [],
          actions: [],
          weekPlan: [],
        })
        wx.showToast({
          title: '训练结构加载失败 / 请重试',
          icon: 'none',
          duration: 3000,
        })
      })
  },
})
