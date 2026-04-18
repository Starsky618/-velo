/**
 * 我的荣誉页 — 显示用户所有 KOM 和前十成绩
 *
 * 数据来源：GET /api/user/honors
 *   返回 { koms: [...], top10s: [...], kom_count, top10_count }
 *
 * 两个 tab 切换同一列表区域，用本地 currentList 字段映射当前选中的数据集。
 *
 * 类比：就像运动员的奖杯柜——
 * 柜子分两层（KOM / 前十），点哪层就显示哪层的奖杯，
 * 点一个奖杯能跳到对应比赛的排行榜去炫耀。
 */
var api = require('../../utils/api')

Page({
  data: {
    currentTab: 'kom',
    komCount: 0,
    top10Count: 0,
    komList: [],
    top10List: [],
    currentList: [],
    loading: false,
  },

  onLoad() {
    this.loadHonors()
  },

  loadHonors() {
    this.setData({ loading: true })
    var that = this
    api.get('/api/user/honors')
      .then(function (res) {
        var koms = (res.koms || []).map(that.decorate)
        var top10s = (res.top10s || []).map(that.decorate)
        that.setData({
          komList: koms,
          top10List: top10s,
          komCount: res.kom_count || 0,
          top10Count: res.top10_count || 0,
          currentList: koms,  // 默认显示 KOM tab
          loading: false,
        })
      })
      .catch(function (err) {
        that.setData({ loading: false })
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
      })
  },

  /**
   * 把后端荣誉对象装饰成 UI 友好字段。
   * 时间格式化：≥1h 显示 "1:02:05"，否则 "62:05" → 改为 "1:02:05"
   * 修复双审 I-1：长爬坡赛段（>60min）原 m:ss 格式会显示 "62:05" 而非 "1:02:05"
   */
  decorate(h) {
    return {
      segment_id: h.segment_id,
      segment_name: h.segment_name || '未命名赛段',
      rank: h.rank,
      timeText: formatHMS(h.elapsed_time || 0),
      speedText: h.avg_speed != null ? h.avg_speed.toFixed(1) + ' km/h' : '-',
    }
  },

  /**
   * 切换 tab：同时更新 currentTab 标识和 currentList 数据源。
   */
  switchTab(e) {
    var tab = e.currentTarget.dataset.tab
    this.setData({
      currentTab: tab,
      currentList: tab === 'kom' ? this.data.komList : this.data.top10List,
    })
  },

  /**
   * 点击一条荣誉条目：跳对应赛段排行榜。
   */
  goSegment(e) {
    wx.navigateTo({
      url: '/pages/leaderboard/leaderboard?segment_id=' + e.currentTarget.dataset.id,
    })
  },
})


/**
 * 秒数 → "M:SS" 或 "H:MM:SS" 格式。
 * 和 leaderboard.js 的 formatTime 同款逻辑（保持一致体验）。
 */
function formatHMS(seconds) {
  if (!seconds) return '-'
  var h = Math.floor(seconds / 3600)
  var m = Math.floor((seconds % 3600) / 60)
  var s = seconds % 60
  var ss = s < 10 ? '0' + s : '' + s
  if (h > 0) {
    var mm = m < 10 ? '0' + m : '' + m
    return h + ':' + mm + ':' + ss
  }
  return m + ':' + ss
}
