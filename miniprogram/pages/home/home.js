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
// 轨迹缩略点拉取（profile 页同款 / 带模块级缓存，翻页不重复请求）：
// 大图卡的封面就是这条骑行的轨迹形状，由 ride-card 组件 observer + route-thumb canvas 自画。
const rideThumbs = require('../../utils/ride-thumbs')
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
    // v5 新增：分页 / 加载更多状态（onReachBottom 触发）
    currentPage: 1,
    hasMore: true,
    loadingMore: false,
    // v4 新增：未读通知数（控制铃铛红点显示）
    unreadCount: 0,
  },

  onShow() {
    if (app.globalData.token) {
      this.setData({ isLoggedIn: true })
      this.ensureUserInfo()   // 拉自己的昵称/头像（动态流头像行要用，像 Strava 那样）
      this.fetchWeeklyStats()
      this.fetchRides()
      // v4 新增：每次进首页都刷新未读数
      // 用 onShow 而非 onLoad——因为用户从通知页返回时要看到红点消失
      this.refreshUnreadCount()
    } else {
      this.setData({ isLoggedIn: false, rides: [], unreadCount: 0 })
    }
  },

  /**
   * 查询未读通知数，控制右上角红点显示。
   *
   * 设计说明：
   * - 免打扰开关开启时不发请求，直接清 0（省流量 + 符合用户意图）
   * - 未登录时不发请求（Authorization 会空，后端返 401 又清 token 循环）
   * - 失败静默——首页主功能是骑行流，查红点失败不应该干扰主流程
   *
   * 类比：就像手机锁屏上的消息图标——
   * 开了勿扰模式图标就不亮，没登录也没东西可亮，
   * 查不到网络就维持老样子，总之不打扰用户看主要内容。
   */
  refreshUnreadCount() {
    // truthiness 陷阱：显式 === true 比 if (muted) 安全
    // 如果 storage 里存的是旧版字符串 'true' 或 undefined，if 判断会出意外
    var muted = wx.getStorageSync('mute_notifications') === true
    if (muted) {
      this.setData({ unreadCount: 0 })
      return
    }

    if (!app.globalData.token) {
      this.setData({ unreadCount: 0 })
      return
    }

    var that = this
    // page_size=1：只关心响应里的 unread_count 字段，列表数据无需真下发
    api.get('/api/notifications', { unread_only: true, page_size: 1 })
      .then(function (res) {
        that.setData({ unreadCount: res.unread_count || 0 })
      })
      .catch(function () {
        // 失败静默，保持上次值，避免闪烁
      })
  },

  /**
   * 拉自己的昵称 + 头像，供动态流卡片头像行用（像 Strava：真头像 + 真昵称 + 时间）。
   *
   * 为什么 home 要自己拉：app.globalData.userInfo 只有进过"我的"页才会被填，
   * 用户直接打开"动态"页时它是 null → 昵称回落成"骑行者"、头像只有字母占位。
   * 这里在 onShow 主动拉一次 GET /api/user/profile（profile 页同一接口），
   * 缓存进 globalData.userInfo 避免重复请求，拿到后回填到已渲染的 rides 卡片。
   *
   * 时序：和 fetchRides 并行不阻塞列表——profile 回来后再批量给所有卡片补昵称/头像
   * （home 是单人流，所有卡片的作者都是自己，昵称/头像一致）。
   */
  ensureUserInfo() {
    var that = this
    var cached = app.globalData.userInfo
    if (cached && cached.nickname) {
      this._applyAuthorToRides(cached)
      return
    }
    api.get('/api/user/profile')
      .then(function (info) {
        app.globalData.userInfo = info
        that._applyAuthorToRides(info)
      })
      .catch(function () {
        // 失败静默：拉不到就维持"骑行者"占位，不阻塞动态流主功能
      })
  },

  /**
   * 把作者信息（昵称 + 头像）回填到当前所有 rides 卡片。
   * 单人流下所有卡片作者都是自己，统一覆盖；按下标批量 setData。
   */
  _applyAuthorToRides(info) {
    var nickname = (info && info.nickname) || '骑行者'
    var avatarUrl = (info && info.avatar_url) || ''
    var initial = nickname[0]
    this._author = { nickname: nickname, avatarUrl: avatarUrl, initial: initial }
    var rides = this.data.rides || []
    if (rides.length === 0) return
    var updates = {}
    rides.forEach(function (r, i) {
      updates['rides[' + i + '].nickname'] = nickname
      updates['rides[' + i + '].avatarUrl'] = avatarUrl
      updates['rides[' + i + '].initial'] = initial
    })
    this.setData(updates)
  },

  /**
   * 点铃铛跳通知中心页。
   */
  goNotifications() {
    wx.navigateTo({ url: '/pages/notification/notification' })
  },

  /**
   * 空状态"去上传"按钮——上传页是 tab 页，必须用 switchTab。
   */
  goUpload() {
    wx.switchTab({ url: '/pages/upload/upload' })
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

  /**
   * 拉骑行列表 / 支持分页（v5 加载更多）。
   *
   * @param {number} page 默认 1。
   *   page=1：首屏 / 替换 rides + 重置 hasMore（onShow / 用户切回首页）
   *   page>1：onReachBottom 触发 / append 到现有 rides
   */
  fetchRides(page) {
    var that = this
    if (page === undefined) page = 1
    var isFirst = page === 1
    if (isFirst) this.setData({ loading: true })
    else this.setData({ loadingMore: true })

    api.get('/api/activities?page=' + page + '&page_size=20')
      .then(function (data) {
        // 作者信息（昵称/头像/首字）：优先用已拉到的 _author（ensureUserInfo 填），
        // 还没拉到则先用 globalData 或"骑行者"占位，待 ensureUserInfo 回来 _applyAuthorToRides 补全。
        var author = that._author
          || (app.globalData.userInfo && {
                nickname: app.globalData.userInfo.nickname || '骑行者',
                avatarUrl: app.globalData.userInfo.avatar_url || '',
                initial: (app.globalData.userInfo.nickname || '骑行者')[0],
              })
          || { nickname: '骑行者', avatarUrl: '', initial: '骑' }

        var list = (data.items || []).map(function (item) {
          return {
            id: item.id,
            title: item.title || '骑行记录',
            status: item.status,
            nickname: author.nickname,
            initial: author.initial,
            avatarUrl: author.avatarUrl,
            // 核心三项
            distance: item.distance || 0,
            // 时长统一显示"移动时间"/ 老活动 GPX 没存 moving_time 时 fallback duration
            duration: item.moving_time || item.duration || 0,
            durationText: that.fmtDur(item.moving_time || item.duration),
            elevation_gain: Math.round(item.elevation_gain || 0),
            // 次要数据
            avg_speed: item.avg_speed,
            avg_power: item.avg_power != null ? Math.round(item.avg_power) : null,
            avg_hr: item.avg_hr != null ? Math.round(item.avg_hr) : null,
            // 时间
            dateText: that.fmtDate(item.started_at || item.created_at),
            // ride-card 组件 cover 模式头像行的时间槽位读 startedAtDisplay（组件契约字段名）
            startedAtDisplay: that.fmtDate(item.started_at || item.created_at),
            // 赛段成绩（后续异步填充）
            segments: [],
            segLoaded: false,
          }
        })

        // page=1 替换 / page>1 append（保持加载更多体验连续）
        var rides = isFirst ? list : that.data.rides.concat(list)
        var total = data.total || rides.length
        var hasMore = rides.length < total

        that.setData({
          rides: rides,
          loading: false,
          loadingMore: false,
          currentPage: page,
          hasMore: hasMore,
        })

        // 列表落地后异步补轨迹缩略点（拿到才有图，ride-card 组件 observer 自画大图）。
        that.fillTrackThumbs()

        // 对每条已完成的骑行 / 异步加载赛段匹配结果。
        // startIdx 必须是该 page 在最终 rides 数组里的起点（page_size=20 hardcode）。
        var startIdx = (page - 1) * 20
        list.forEach(function (ride, idx) {
          if (ride.status === 'completed') {
            that.fetchSegments(ride.id, startIdx + idx)
          }
        })
      })
      .catch(function () {
        that.setData({ loading: false, loadingMore: false })
      })
  },

  /**
   * 滚动到底部触发 / 加载下一页。
   * loadingMore lock 防重复触发；hasMore=false 直接忽略。
   */
  onReachBottom() {
    if (!this.data.isLoggedIn) return
    if (this.data.loadingMore) return
    if (!this.data.hasMore) return
    this.fetchRides(this.data.currentPage + 1)
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

  // 骑行卡片点击 → 跳详情。
  // ride-card 组件 triggerEvent('tap-ride', { activity_id }) → 这里接 e.detail（和 profile 同契约）。
  onRideTap(e) {
    var id = e.detail && e.detail.activity_id
    if (!id) return
    wx.navigateTo({ url: '/pages/detail/detail?id=' + id })
  },

  // 给当前 rides 批量补轨迹缩略点（utils/ride-thumbs 带模块级缓存，翻页/回页不重复请求）。
  // 按 id 现场重找下标回写——异步回来时数组可能已被下拉刷新重建，防错位（profile 同款 pattern）。
  fillTrackThumbs() {
    var that = this
    rideThumbs.fetchTrackPoints(this.data.rides).then(function (cache) {
      var updates = {}
      that.data.rides.forEach(function (r, i) {
        if (r && cache[r.id] && !r.trackPoints) {
          updates['rides[' + i + '].trackPoints'] = cache[r.id]
        }
      })
      if (Object.keys(updates).length > 0) {
        that.setData(updates)
      }
    })
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
    // 跨年活动加年份（避免 2023年4月12日 和 2026年4月12日 看起来一样）
    if (d.getFullYear() !== now.getFullYear()) {
      return d.getFullYear() + '年' + month + '月' + day + '日 ' + hour + ':' + min
    }
    return month + '月' + day + '日 ' + hour + ':' + min
  },
})
