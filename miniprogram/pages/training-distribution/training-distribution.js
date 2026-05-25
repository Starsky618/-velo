/**
 * 训练结构页 —— 展示最近 6 周训练时间怎么分布。
 *
 * 数据来源：GET /api/training/distribution?range=6w
 * 页面只展示后端给的判断、文案和分布数据，不从活动列表自己拼结果。
 */
const api = require('../../utils/api')
const EXCLUDE_ZERO_STORAGE_KEY = 'training_distribution_exclude_zero'

// 把三组占比拼成 conic-gradient 圆饼图背景（颜色和下方横条一一对应：耐力绿 / 中强度橙 / 高强度红）。
// 累积角度法：每组从上一组结束的百分比起、到累加后的百分比止，依次铺色，三段刚好转一圈。
function buildDonutStyle(groups) {
  if (!Array.isArray(groups) || groups.length === 0) return ''
  var colors = ['#2EAD6B', '#E6A23C', '#C9574C']
  var acc = 0
  var stops = []
  for (var i = 0; i < groups.length; i++) {
    var pct = Number(groups[i].percent) || 0
    var start = acc
    acc += pct
    // 三组各自 round 后总和可能是 99 或 101，最后一段强制收到 100% 补平，避免饼图留白缝或被截断
    var end = (i === groups.length - 1) ? 100 : acc
    stops.push(colors[i % colors.length] + ' ' + start + '% ' + end + '%')
  }
  if (acc <= 0) return ''  // 三组全 0（极端脏数据）不画饼图，wxml 用 wx:if 整块隐藏
  return 'conic-gradient(' + stops.join(', ') + ')'
}

Page({
  data: {
    loading: true,
    loadError: false,
    dataComplete: false,
    insufficientPower: false,
    distribution: null,
    excludeZero: false,
    donutStyle: '',
    groups: [],
    rawZones: [],
    actions: [],
    weekPlan: [],
  },

  onLoad() {
    var excludeZero = wx.getStorageSync(EXCLUDE_ZERO_STORAGE_KEY) === true
    this.setData({ excludeZero: excludeZero })
    this.fetchDistribution(excludeZero)
  },

  onPullDownRefresh() {
    this.fetchDistribution().finally(function () {
      wx.stopPullDownRefresh()
    })
  },

  fetchDistribution(excludeZero) {
    const that = this
    var shouldExcludeZero = excludeZero === undefined ? this.data.excludeZero : excludeZero
    var params = { range: '6w', exclude_zero: shouldExcludeZero }
    this.setData({ loading: true, loadError: false })

    return api.get('/api/training/distribution', params)
      .then(function (res) {
        const dataComplete = !!(res && res.data_complete)
        const insufficientPower = !!(res && res.insufficient_power_data)
        var groups = res && Array.isArray(res.groups) ? res.groups : []
        that.setData({
          loading: false,
          loadError: false,
          dataComplete: dataComplete,
          insufficientPower: insufficientPower,
          distribution: res || null,
          groups: groups,
          donutStyle: buildDonutStyle(groups),
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
          donutStyle: '',
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

  onExcludeZeroChange(e) {
    var excludeZero = !!(e && e.detail && e.detail.value)
    wx.setStorageSync(EXCLUDE_ZERO_STORAGE_KEY, excludeZero)
    this.setData({ excludeZero: excludeZero })
    this.fetchDistribution(excludeZero)
  },
})
