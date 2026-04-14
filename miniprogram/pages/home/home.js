/**
 * 首页 — 骑行动态流
 *
 * 不是"数据列表"，而是"骑行朋友圈"：
 * 每条骑行记录呈现为一张卡片，卡片是产品的核心内容单元。
 *
 * 数据来源：
 * - 周统计：GET /api/user/stats?period=week
 * - 骑行列表：GET /api/activities?page=1&page_size=20
 * - 赛段成绩：GET /api/activities/{id}/segments（每条骑行附带）
 */

const api = require('../../utils/api')
const app = getApp()

Page({
  data: {
    isLoggedIn: false,
    // 本周统计
    weeklyKm: 0,
    weeklyRides: 0,
    weeklyElev: 0,
    weeklyGoal: 200,
    goalPercent: 0,
    // 骑行卡片列表
    rides: [],
    loading: false,
  },

  onShow() {
    if (app.globalData.token) {
      this.setData({ isLoggedIn: true })
      this.fetchWeeklyStats()
      this.fetchRides()
    } else {
      this.setData({ isLoggedIn: false, rides: [] })
    }
  },

  fetchWeeklyStats() {
    var that = this
    api.get('/api/user/stats?period=week')
      .then(function (data) {
        that.setData({
          weeklyKm: data.distance,
          weeklyRides: data.rides,
          weeklyElev: data.elevation_gain,
          weeklyGoal: data.weekly_goal,
          goalPercent: data.goal_percent,
        })
      })
      .catch(function () {})
  },

  fetchRides() {
    var that = this
    this.setData({ loading: true })
    api.get('/api/activities?page=1&page_size=20')
      .then(function (data) {
        var list = (data.items || []).map(function (item) {
          // 获取用户昵称首字（头像用）
          var userInfo = app.globalData.userInfo
          var nickname = (userInfo && userInfo.nickname) || '骑行者'
          var initial = nickname[0]

          return {
            id: item.id,
            title: item.title || '骑行记录',
            status: item.status,
            nickname: nickname,
            initial: initial,
            // 核心三项
            distance: item.distance || 0,
            duration: item.duration || 0,
            durationText: that.fmtDur(item.duration),
            elevation_gain: Math.round(item.elevation_gain || 0),
            // 次要数据
            avg_speed: item.avg_speed,
            avg_power: item.avg_power,
            avg_hr: item.avg_hr,
            // 时间
            dateText: that.fmtDate(item.started_at || item.created_at),
            // 赛段成绩（后续异步填充）
            segments: [],
            segLoaded: false,
          }
        })
        that.setData({ rides: list, loading: false })

        // 对每条已完成的骑行，异步加载赛段匹配结果
        list.forEach(function (ride, idx) {
          if (ride.status === 'completed') {
            that.fetchSegments(ride.id, idx)
          }
        })
      })
      .catch(function () {
        that.setData({ loading: false })
      })
  },

  /**
   * 异步加载某条骑行的赛段匹配结果
   * 成功后更新对应卡片的 segments 字段
   */
  fetchSegments(activityId, idx) {
    var that = this
    api.get('/api/activities/' + activityId + '/segments')
      .then(function (data) {
        var items = (data.items || []).map(function (s) {
          return {
            name: s.segment_name,
            rank: s.rank,
            is_pr: s.is_pr,
            timeText: that.fmtDur(s.elapsed_time),
          }
        })
        // 动态更新列表中对应项
        var key = 'rides[' + idx + '].segments'
        var key2 = 'rides[' + idx + '].segLoaded'
        var update = {}
        update[key] = items
        update[key2] = true
        that.setData(update)
      })
      .catch(function () {})
  },

  openRide(e) {
    var id = e.currentTarget.dataset.id
    wx.navigateTo({ url: '/pages/detail/detail?id=' + id })
  },

  fmtDur(seconds) {
    if (!seconds) return '0:00'
    var h = Math.floor(seconds / 3600)
    var m = Math.floor((seconds % 3600) / 60)
    var s = seconds % 60
    if (h > 0) {
      return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
    }
    return m + ':' + String(s).padStart(2, '0')
  },

  fmtDate(isoStr) {
    if (!isoStr) return ''
    var d = new Date(isoStr)
    var now = new Date()
    var month = String(d.getMonth() + 1).padStart(2, '0')
    var day = String(d.getDate()).padStart(2, '0')
    var hour = String(d.getHours()).padStart(2, '0')
    var min = String(d.getMinutes()).padStart(2, '0')
    if (d.toDateString() === now.toDateString()) {
      return '今天 ' + hour + ':' + min
    }
    var yesterday = new Date(now)
    yesterday.setDate(yesterday.getDate() - 1)
    if (d.toDateString() === yesterday.toDateString()) {
      return '昨天 ' + hour + ':' + min
    }
    return month + '月' + day + '日 ' + hour + ':' + min
  },
})
