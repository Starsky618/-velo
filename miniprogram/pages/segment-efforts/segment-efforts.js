/**
 * 我在某赛段的全部成绩列表（task-4.5）
 *
 * 入口：segment 详情页"你的成绩 N 项 ›"
 * 数据：task-4.3 后端接口 GET /api/segments/{id}/my-efforts
 * 渲染：按年份分组（图 1 风格 / 黑底白字 / PR 黄点）
 */

const api = require('../../utils/api')
const { formatTime } = require('../../utils/format')

Page({
  data: {
    segmentId: null,
    groupedItems: [],   // [{ year: '2024', items: [{date, time, speed, power, is_pr, activity_id}] }]
    loading: true,
    loadFailed: false,
    notFound: false,
    notLoggedIn: false,
  },

  onLoad(options) {
    // 入口校验：segment_id 必须是合法正整数（≥1 / 排除 "0" / 排除前导 0 / 排除 "123abc"）
    const raw = options && options.segment_id
    if (typeof raw !== 'string' || !/^[1-9]\d*$/.test(raw)) {
      wx.showToast({ title: '无效赛段', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 1500)
      return
    }
    const segmentId = parseInt(raw, 10)

    const app = getApp()
    const isLoggedIn = !!(app.globalData && app.globalData.token)
    if (!isLoggedIn) {
      // 这条页面只对登录用户有意义（我的成绩单 / 未登录跳不到这里 / 兜底友好提示）
      this.setData({ segmentId, loading: false, notLoggedIn: true })
      return
    }

    this.setData({ segmentId })
    this.fetchData()
  },

  fetchData() {
    this.setData({ loading: true, loadFailed: false })
    api.getMySegmentEfforts(this.data.segmentId)
      .then((data) => {
        const items = (data && data.items) || []
        const grouped = this.groupByYear(items)
        this.setData({ groupedItems: grouped, loading: false })
      })
      .catch((err) => {
        if (err && err.code === 404) {
          this.setData({ loading: false, notFound: true })
        } else {
          this.setData({ loading: false, loadFailed: true })
        }
      })
  },

  /**
   * 按 created_at 的年份分组。
   *
   * 后端已经按 created_at 倒序返回，前端只需顺序扫一遍，
   * 遇到新年份就开一个新分组——类比相册按月份分组，但这里按年。
   * 不重排序（保留后端已确定的同年内倒序顺序）。
   *
   * 时区说明（task-4.5 B 审 I2）：用 new Date(...).getFullYear() 等是**设备本地时区**
   * （北京 UTC+8）—— 跟用户感知的"我哪天骑的"对齐（不是 UTC）。
   * 跨年边界场景：UTC 12 月 31 日 16:00 后 = 北京 1 月 1 日凌晨 → 算"下一年"，
   * 跟用户对"凌晨骑车算新一年"的直觉一致。不要改成 UTC 模式。
   */
  groupByYear(items) {
    const groups = []
    let current = null
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      const date = new Date(item.created_at)
      // Codex 异源审兜底：老 Android 基础库可能把 "+00:00" 后缀解析为 Invalid Date → NaN 年份分组
      // 失败时把这条扔进"未知"组兜底（不崩 / 不显示 "NaN" 标题）
      if (isNaN(date.getTime())) {
        if (current === null || current.year !== '未知') {
          current = { year: '未知', items: [] }
          groups.push(current)
        }
        current.items.push({
          activity_id: item.activity_id,
          dateLabel: '-',
          timeText: formatTime(item.elapsed_time),
          speedText: '-',
          powerText: '-',
          is_pr: item.is_pr === true,
        })
        continue
      }
      const year = String(date.getFullYear())
      const month = date.getMonth() + 1
      const day = date.getDate()
      if (current === null || current.year !== year) {
        current = { year, items: [] }
        groups.push(current)
      }
      current.items.push({
        activity_id: item.activity_id,
        dateLabel: month + '月' + day + '日',
        timeText: formatTime(item.elapsed_time),
        speedText: (item.avg_speed !== null && item.avg_speed !== undefined)
          ? item.avg_speed.toFixed(1) + ' km/h'
          : '-',
        powerText: (item.avg_power !== null && item.avg_power !== undefined)
          ? Math.round(item.avg_power) + ' W'
          : '-',
        is_pr: item.is_pr === true,
      })
    }
    return groups
  },

  /**
   * 点击一行成绩 → 跳那次原始骑行详情页。
   * 不带 from_activity_id（避免 detail → segment → segment-efforts → detail 形成循环）。
   */
  onTapRow(e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    wx.navigateTo({ url: '/pages/detail/detail?id=' + id })
  },

  /**
   * 加载失败重试入口
   */
  onTapRetry() {
    this.fetchData()
  },

  goLogin() {
    wx.switchTab({ url: '/pages/profile/profile' })
  },
})
