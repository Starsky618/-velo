/**
 * 通知中心页 — 显示后端收集的所有通知事件（PR / KOM / KOM 被超越）
 *
 * 数据流：
 *   onLoad → 并行调两个接口
 *     ① GET /api/notifications?page=1&page_size=20 拿列表
 *     ② POST /api/notifications/mark-all-read 把所有未读标读
 *   分页：onReachBottom 触发下一页
 *   下拉：onPullDownRefresh 清空 + 重拉
 *
 * 类比：就像微信的"服务通知"——
 * 一进来所有消息视觉上都变灰（UI 已读），
 * 后台悄悄通知服务器"我读过了"，即使网络慢也不影响视觉体验。
 */
var api = require('../../utils/api')

Page({
  data: {
    items: [],
    page: 1,
    pageSize: 20,
    loading: false,
    noMore: false,
  },

  onLoad() {
    // 两个请求并行发出，互不等——符合 task 约定（先加载列表，后台标读）
    this.loadFirstPage()
    this.markAllRead()
  },

  onPullDownRefresh() {
    // 下拉刷新：清空当前列表，重新拉第一页
    this.setData({ items: [], page: 1, noMore: false })
    this.loadFirstPage()
    wx.stopPullDownRefresh()
  },

  onReachBottom() {
    // 触底加载下一页，防并发（loading 中或已无更多则跳过）
    if (!this.data.loading && !this.data.noMore) {
      this.loadNextPage()
    }
  },

  /**
   * 标全部已读——幂等接口，失败可下次进来时再调。
   * 不等返回也不显示 toast，用户感知不到。
   */
  markAllRead() {
    api.post('/api/notifications/mark-all-read').catch(function () {
      // 失败静默；注意必须写 catch，否则 Promise 抛异常会被小程序吞掉
    })
  },

  /**
   * 加载第一页通知列表。
   */
  loadFirstPage() {
    this.setData({ loading: true })
    var that = this
    api.get('/api/notifications', { page: 1, page_size: this.data.pageSize })
      .then(function (res) {
        var items = (res.items || []).map(that.decorate)
        that.setData({
          items: items,
          page: 1,
          loading: false,
          noMore: items.length >= (res.total || 0),
        })
      })
      .catch(function (err) {
        that.setData({ loading: false })
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
      })
  },

  /**
   * 加载下一页并追加到现有列表。
   */
  loadNextPage() {
    var nextPage = this.data.page + 1
    this.setData({ loading: true })
    var that = this
    api.get('/api/notifications', { page: nextPage, page_size: this.data.pageSize })
      .then(function (res) {
        var newItems = (res.items || []).map(that.decorate)
        var allItems = that.data.items.concat(newItems)
        that.setData({
          items: allItems,
          page: nextPage,
          loading: false,
          noMore: allItems.length >= (res.total || 0),
        })
      })
      .catch(function () {
        that.setData({ loading: false })
      })
  },

  /**
   * 把后端通知对象装饰成 UI 友好字段。
   *
   * 设计说明：
   * - 后端返回原始数据（event_type='pr' 等），前端负责格式化
   * - event_type CHECK 约束只有 pr / kom / kom_lost 三种
   *   （top10 只在荣誉表语义里，不是通知类型——不要脑补加进来）
   * - segment_name 为 null 时降级为"已失效赛段"（外键 SET NULL 后的情况）
   */
  decorate(n) {
    var iconMap = { pr: '🏆', kom: '👑', kom_lost: '💔' }
    var titleMap = {
      pr: '破纪录！',
      kom: '恭喜夺得 KOM',
      kom_lost: 'KOM 被超越',
    }

    var segName = n.segment_name || '已失效赛段'
    var sub
    if (n.event_type === 'kom_lost' && n.rival_nickname) {
      sub = n.rival_nickname + ' 在 "' + segName + '" 超越了你'
    } else if (n.rank) {
      sub = segName + ' · #' + n.rank
    } else {
      sub = segName
    }

    return {
      id: n.id,
      // is_read 用 === true 严格判断（防 NULL / undefined 被当 false）
      is_read: n.is_read === true,
      iconText: iconMap[n.event_type] || '📢',
      titleText: titleMap[n.event_type] || '通知',
      subText: sub,
      timeText: formatRelativeTime(n.created_at),
      segment_id: n.segment_id,  // null 时点击不跳
    }
  },

  /**
   * 点击一条通知：跳对应赛段的排行榜页；segment_id 为 null 时提示失效。
   */
  onTapItem(e) {
    var segmentId = e.currentTarget.dataset.segment
    if (!segmentId) {
      wx.showToast({ title: '该记录已失效', icon: 'none' })
      return
    }
    // 用 leaderboard 页接收 segment_id 参数——这是项目现有路由习惯
    wx.navigateTo({ url: '/pages/leaderboard/leaderboard?segment_id=' + segmentId })
  },
})

/**
 * ISO 时间串 → 相对时间文本（如"3 小时前"）。
 *
 * 类比：微信消息时间的显示逻辑——
 * 1 分钟内"刚刚"，1 小时内显示"X 分钟前"，
 * 1 天内"X 小时前"，1 月内"X 天前"，超过就给完整日期。
 */
function formatRelativeTime(iso) {
  if (!iso) return ''
  var t = new Date(iso).getTime()
  var diff = (Date.now() - t) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前'
  if (diff < 2592000) return Math.floor(diff / 86400) + ' 天前'
  return new Date(iso).toLocaleDateString()
}
