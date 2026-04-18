/**
 * 排行榜页 — 骑行者的"荣誉殿堂"
 *
 * 核心反馈环的关键闭合点：看到排名 → 被激励 → 继续骑。
 *
 * 结构：
 * - 顶部：赛段选择器（横向滚动标签，点击切换）
 * - 中间：选中赛段的基本信息
 * - 下方：排行榜列表（按用时升序，快的排前面）
 */

const api = require('../../utils/api')
const app = getApp()

Page({
  data: {
    // 赛段列表
    segments: [],
    // 当前选中的赛段 index
    activeIdx: 0,
    // 当前赛段详情（含排行榜 top20）
    detail: null,
    loading: true,
  },

  /**
   * v4 task-7.10：接收外部跳转传来的 segment_id（从通知中心 / 荣誉页 navigateTo 时带）。
   * onLoad 只触发一次（页面首次创建），把意图存到实例字段，等 onShow → fetchSegments
   * 取到列表后再定位到对应赛段。找不到则 fallback 到 list[0]。
   */
  onLoad(options) {
    var sid = options && options.segment_id
    this._pendingSegmentId = sid ? parseInt(sid, 10) : null
  },

  onShow() {
    this.fetchSegments()
  },

  /**
   * 第一步：拉取所有赛段列表
   */
  fetchSegments() {
    var that = this
    this.setData({ loading: true })
    api.get('/api/segments?page=1&page_size=100')
      .then(function (data) {
        var list = data.items || []

        // v4 task-7.10：优先定位到外部跳转指定的 segment_id
        // 找到则用 list 中对应 index；找不到（比如赛段被删）fallback 到 list[0]
        var targetIdx = 0
        var pendingId = that._pendingSegmentId
        if (pendingId && list.length > 0) {
          for (var i = 0; i < list.length; i++) {
            if (list[i].id === pendingId) {
              targetIdx = i
              break
            }
          }
          // 消费一次后清掉，防止后续 onShow 重定位（用户切 tab 该按 activeIdx 走）
          that._pendingSegmentId = null
        }

        that.setData({ segments: list, activeIdx: targetIdx })
        if (list.length > 0) {
          that.fetchDetail(list[targetIdx].id)
        } else {
          that.setData({ loading: false })
        }
      })
      .catch(function () {
        that.setData({ loading: false })
      })
  },

  /**
   * 第二步：拉取选中赛段的详情 + 排行榜 TOP20
   */
  fetchDetail(segmentId) {
    var that = this
    this.setData({ loading: true })
    api.get('/api/segments/' + segmentId)
      .then(function (data) {
        // 预处理排行榜数据：格式化用时
        var lb = (data.leaderboard || []).map(function (item) {
          return {
            rank: item.rank,
            user_id: item.user_id,
            nickname: item.nickname || '骑行者',
            initial: (item.nickname || '骑')[0],
            elapsed_time: item.elapsed_time,
            timeText: that.formatTime(item.elapsed_time),
            avg_speed: item.avg_speed,
            avg_power: item.avg_power,
            // 检查是否是当前用户
            isMe: app.globalData.userInfo
              ? item.user_id === app.globalData.userInfo.id
              : false,
          }
        })
        that.setData({
          detail: {
            id: data.id,
            name: data.name,
            distance: data.distance,
            elevation_gain: data.elevation_gain,
            leaderboard: lb,
          },
          loading: false,
        })
      })
      .catch(function () {
        that.setData({ loading: false })
      })
  },

  /**
   * 点击赛段标签切换
   */
  switchSegment(e) {
    var idx = e.currentTarget.dataset.idx
    var seg = this.data.segments[idx]
    if (seg) {
      this.setData({ activeIdx: idx })
      this.fetchDetail(seg.id)
    }
  },

  /**
   * 秒数转 "2:14" 或 "1:32:14" 格式
   */
  formatTime(seconds) {
    if (!seconds) return '-'
    var h = Math.floor(seconds / 3600)
    var m = Math.floor((seconds % 3600) / 60)
    var s = seconds % 60
    if (h > 0) {
      return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
    }
    return m + ':' + String(s).padStart(2, '0')
  },
})
