/**
 * 赛段详情页 — 看某条赛段的全貌（task-4.5 / 4 区块完整版）
 *
 * 这个文件干什么的：
 *   接收 query.id（segment_id），并行拉 3 份数据（赛段详情 / 我的记录 / 排行榜），
 *   塞给 wxml 渲染 4 个区块。每份数据独立失败（不一损俱损）。
 *
 *   类比：就像点开餐厅的"菜品详情页"——
 *   主厨介绍（赛段名 + 4 数字）/ 食客评价（AI 介绍）/
 *   你点过的记录（我的记录）/ 销量排行（全网榜）—— 4 块独立加载，
 *   有一块出问题不影响其他几块还能看。
 *
 * 操作注意事项：
 *   1. 三 fetch 并行 / 各自独立 catch（红线 #5 / 防一损俱损）
 *   2. 海拔曲线 canvas 必须 hidden 不 wx:if（CLAUDE.md 陷阱 #17）
 *   3. 用真字段：segment.description（不是 introduction）/ leaderboard.items（不是 top）
 *   4. globalData.userInfo.id（不是 userId 直字段 / grep 实证）
 *   5. /api/segments/{id}/efforts/me 是 v5 即时反馈 endpoint（更精准 / 不用 /api/user/efforts）
 *
 * 输入输出：
 *   输入：query.id（赛段 ID / parseInt 后必须 > 0）
 *   输出：4 区块渲染（含三态降级 + 独立错误恢复 + 海拔图占位）
 */

const api = require('../../utils/api')
const { getCityLabel } = require('../../utils/city')
const { formatTime } = require('../../utils/format')

Page({
  data: {
    segmentId: 0,
    loading: true,
    notFound: false,

    // 登录态 + 当前用户 ID（用作排行榜高亮 / 真字段 globalData.userInfo.id）
    isLoggedIn: false,
    myUserId: 0,

    // 区块 1：第一屏
    segment: null,
    cityLabel: '',
    elevationGainText: '-',
    avgGradientText: '-',
    maxGradientText: '-',
    hasElevationProfile: false,  // 后端暂不返 elevation_profile / 永远 false（区块降级）

    // 区块 2：AI 介绍
    shouldShowExpand: false,
    introExpanded: false,

    // 区块 3：我的记录（基于 EffortCompareResponse 6 字段）
    myEffort: null,             // 后端 6 字段对象
    myEffortDisplay: null,      // 前端渲染用：{ prTime, progressText }
    myEffortError: false,

    // 区块 4：全网排行榜
    leaderboard: null,          // 后端响应：{ items, total, page, page_size }
    leaderboardItems: [],       // 渲染用：top 10 + isMe 标记 + timeFormatted
    leaderboardError: false,
    myRankOutOfTop: false,      // 我的排名是否在 top 10 之外（决定是否显示独立行）
    myRankRow: null,            // 我的排名独立行渲染数据：{ rank, timeFormatted }
  },

  onLoad(options) {
    const segmentId = parseInt(options && options.id, 10)
    if (!segmentId || isNaN(segmentId) || segmentId <= 0) {
      wx.showToast({ title: '无效赛段', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 1500)
      return
    }

    const app = getApp()
    // globalData.userInfo 在登录后才有 / 未登录时是 null
    const userInfo = (app.globalData && app.globalData.userInfo) || null
    const isLoggedIn = !!(app.globalData && app.globalData.token)

    this.setData({
      segmentId,
      loading: true,
      isLoggedIn,
      myUserId: (userInfo && userInfo.id) || 0,
    })

    this.fetchAllData(segmentId)
  },

  /**
   * 三 fetch 并行 / 独立失败
   *
   * 设计思路（task-4.5.md §红线 #5）：
   *   - segment fetch 失败 → 整页错误（核心信息缺失，没法降级）
   *   - myEffort fetch 失败 → 我的记录区块显示"加载失败 + 重试"，不影响其他
   *   - leaderboard fetch 失败 → 排行榜区块显示"加载失败 + 重试"，不影响其他
   *
   *   关键技巧：用 Promise.allSettled 让 3 个 promise 各自走自己的 then/catch，
   *   不用 Promise.all（任一失败全 reject）。
   */
  fetchAllData(segmentId) {
    const tasks = []

    // task 1：赛段详情（必须成功 / 失败=整页错误）
    tasks.push(api.getSegmentDetail(segmentId))

    // task 2：我的记录（仅登录用户拉 / 未登录直接 resolve null）
    if (this.data.isLoggedIn) {
      tasks.push(
        api.getMySegmentEffort(segmentId).catch((err) => {
          // 区分 404（segment 不存在 / 由 segment fetch 主控）和其他错误
          // 这里只标记本区块加载失败，不阻断其他区块
          if (err && err.code === 404) {
            // segment 不存在 → segment fetch 也会 404，主流程会转 notFound
            return { __not_found: true }
          }
          this.setData({ myEffortError: true })
          return null
        }),
      )
    } else {
      tasks.push(Promise.resolve(null))
    }

    // task 3：全网排行榜（不需登录 / 失败标记 leaderboardError）
    tasks.push(
      api.getSegmentLeaderboard(segmentId, 10).catch((err) => {
        if (err && err.code === 404) {
          return { __not_found: true }
        }
        this.setData({ leaderboardError: true })
        return null
      }),
    )

    Promise.all([
      // 仅 segment 走主路径 catch（404 → notFound / 其他错误 → toast）
      tasks[0].catch((err) => {
        if (err && err.code === 404) {
          this.setData({ notFound: true, loading: false })
          throw new Error('__notFound__')
        }
        wx.showToast({ title: '加载失败', icon: 'none' })
        this.setData({ loading: false })
        throw new Error('__segmentFail__')
      }),
      tasks[1],
      tasks[2],
    ])
      .then(([segment, myEffort, leaderboard]) => {
        this.applySegment(segment)
        this.applyMyEffort(myEffort)
        this.applyLeaderboard(leaderboard)
        this.setData({ loading: false })

        // 海拔曲线 canvas 渲染（当前 hasElevationProfile=false / 不渲染）
        // 未来后端补 elevation_profile 字段时，此处用 setTimeout(100) 兜底（陷阱 #17）
      })
      .catch((e) => {
        // segment fetch 失败已在 catch 里处理 setData，这里仅吞错误防 unhandledRejection
        if (e && e.message !== '__notFound__' && e.message !== '__segmentFail__') {
          // 兜底（理论上不会到这）
          this.setData({ loading: false })
        }
      })
  },

  /**
   * 应用区块 1 + 2 数据（segment 详情）
   *
   * 注意陷阱 #1（truthiness）：
   *   - elevation_gain / avg_gradient / max_gradient 后端可能返 null（未算出）/ 0（算出但平地）
   *   - 用 `x === null || x === undefined` 显式判存在 / 不用 `!x`
   */
  applySegment(segment) {
    if (!segment) return

    const cityLabel = getCityLabel(segment.city)

    // 4 数字防御：null / undefined → '-'
    const elevationGainText = (segment.elevation_gain === null || segment.elevation_gain === undefined)
      ? '-'
      : Math.round(segment.elevation_gain)
    const avgGradientText = (segment.avg_gradient === null || segment.avg_gradient === undefined)
      ? '-'
      : segment.avg_gradient.toFixed(1) + '%'
    const maxGradientText = (segment.max_gradient === null || segment.max_gradient === undefined)
      ? '-'
      : segment.max_gradient.toFixed(1) + '%'

    // AI 介绍展开收起判断（80 字以上才显示展开按钮）
    const desc = segment.description || ''
    const shouldShowExpand = desc.length > 80

    this.setData({
      segment,
      cityLabel,
      elevationGainText,
      avgGradientText,
      maxGradientText,
      shouldShowExpand,
      // hasElevationProfile：当前后端 detail response 不返该字段 → 永远 false
      // 未来后端补字段时改为 `!!segment.elevation_profile && segment.elevation_profile.length > 0`
      hasElevationProfile: false,
    })

    // 设置导航栏标题（让用户在小程序最上方就看到赛段名）
    if (segment.name) {
      wx.setNavigationBarTitle({ title: segment.name })
    }
  },

  /**
   * 应用区块 3 数据（我的记录 / EffortCompareResponse 6 字段）
   *
   * 设计思路（基于 spec §3.2.1 / schemas.py:169 EffortCompareResponse）：
   *   - is_first_attempt=true → 没骑过 / 显示引导文案
   *   - pr_elapsed_time != null → 有 PR / 显示主成绩 + 可选进步对比
   *   - last_attempt_elapsed_time != null → 算"上次 X 提到 这次 Y"进步文案
   *   - current_attempt_is_pr=true → 显示"这次创下新纪录"
   *
   * 关键陷阱（CLAUDE.md #1 truthiness）：
   *   - pr_elapsed_time / last_attempt_elapsed_time 是秒数，0 是合法值
   *   - 但用时 0 秒不可能（赛段最短也要几十秒）→ 这里用 `!= null` 判存在
   *   - 防御写：`!== null && !== undefined`
   */
  applyMyEffort(myEffort) {
    // null（未登录或加载失败）/ __not_found（segment 不存在 / 已转 notFound）→ 不展示
    if (!myEffort || myEffort.__not_found) {
      this.setData({ myEffort: null, myEffortDisplay: null })
      return
    }

    const pr = myEffort.pr_elapsed_time
    const last = myEffort.last_attempt_elapsed_time
    const current = myEffort.current_attempt_elapsed_time

    // 没 PR 就视为没骑过（is_first_attempt=true 兜底）
    if (pr === null || pr === undefined) {
      this.setData({ myEffort, myEffortDisplay: null })
      return
    }

    // 进步文案：这次 vs 上次（仅当 last 存在时显示）
    let progressText = ''
    if (last !== null && last !== undefined && current !== null && current !== undefined) {
      const diff = last - current  // 正数 = 变快
      if (diff > 0) {
        progressText = '上次 ' + formatTime(last) + '，这次 ' + formatTime(current) + '，快了 ' + diff + ' 秒'
      } else if (diff < 0) {
        progressText = '上次 ' + formatTime(last) + '，这次 ' + formatTime(current) + '，慢了 ' + (-diff) + ' 秒'
      } else {
        progressText = '上次和这次用时一样'
      }
    }

    this.setData({
      myEffort,
      myEffortDisplay: {
        prTime: formatTime(pr),
        progressText,
      },
    })
  },

  /**
   * 应用区块 4 数据（全网排行榜）
   *
   * 设计思路：
   *   - 后端返 items 数组（前 10 名 / 已含 rank 1-10）
   *   - 前端两件事：① 给每行加 isMe 标记 + timeFormatted ② 算"我的排名是否在 top 10 之外"
   *
   * 我的排名 算法（后端无 my_rank 字段 / 前端 fallback）：
   *   - 在 items 里找 user_id == myUserId 的行 → 取 rank
   *   - 没找到 → 我在 top 10 外 → 用 myEffort.pr_elapsed_time 算 rank（前端不能精确算 / 暂用引导文案）
   *
   *   注：精确"我的排名"应由后端在 leaderboard endpoint 加 my_rank 字段，
   *   当前 v5 期暂用"items 里 filter"兜底（在 top 10 内能高亮 / 在 top 10 外引导用户登录看完整榜）。
   */
  applyLeaderboard(leaderboard) {
    if (!leaderboard || leaderboard.__not_found) {
      this.setData({ leaderboard: null, leaderboardItems: [] })
      return
    }

    const myUserId = this.data.myUserId
    const items = (leaderboard.items || []).map((item) => ({
      rank: item.rank,
      user_id: item.user_id,
      nickname: item.nickname,
      avatar_url: item.avatar_url,
      elapsed_time: item.elapsed_time,
      timeFormatted: formatTime(item.elapsed_time),
      isMe: !!(myUserId && item.user_id === myUserId),
    }))

    // 找我在 top 10 里的位置
    const meInTop = items.find((row) => row.isMe)

    // 我有成绩但不在 top 10 → 显示独立行
    let myRankOutOfTop = false
    let myRankRow = null
    if (this.data.isLoggedIn && !meInTop) {
      // 我有 PR 但不在 top 10 内 → 显示独立行（只展示 PR 时间，rank 用 # 占位）
      const myEffort = this.data.myEffort
      if (myEffort && myEffort.pr_elapsed_time !== null && myEffort.pr_elapsed_time !== undefined) {
        myRankOutOfTop = true
        myRankRow = {
          rank: '#',  // 后端无 my_rank 字段 / 暂用 # 占位（防误显示具体名次）
          timeFormatted: formatTime(myEffort.pr_elapsed_time),
        }
      }
    }

    this.setData({
      leaderboard,
      leaderboardItems: items,
      myRankOutOfTop,
      myRankRow,
    })
  },

  /**
   * 单独重试我的记录（区块 3 错误重试按钮）
   */
  fetchMyEffort() {
    if (!this.data.isLoggedIn) return
    this.setData({ myEffortError: false })
    api.getMySegmentEffort(this.data.segmentId)
      .then((data) => this.applyMyEffort(data))
      .catch((err) => {
        if (err && err.code === 404) {
          this.setData({ notFound: true })
        } else {
          this.setData({ myEffortError: true })
        }
      })
  },

  /**
   * 单独重试全网排行榜（区块 4 错误重试按钮）
   */
  fetchLeaderboard() {
    this.setData({ leaderboardError: false })
    api.getSegmentLeaderboard(this.data.segmentId, 10)
      .then((data) => this.applyLeaderboard(data))
      .catch((err) => {
        if (err && err.code === 404) {
          this.setData({ notFound: true })
        } else {
          this.setData({ leaderboardError: true })
        }
      })
  },

  /**
   * 切换 AI 介绍展开/收起
   */
  toggleIntro() {
    this.setData({ introExpanded: !this.data.introExpanded })
  },

  /**
   * 跳转登录（用 profile tab 的登录入口 / 跟其他页面一致）
   */
  goLogin() {
    wx.switchTab({ url: '/pages/profile/profile' })
  },

  /**
   * 返回（404 / 无效赛段时用）
   */
  goBack() {
    wx.navigateBack({
      fail: () => {
        // 没有上一页（直接 share 进来的）→ 切到 explore tab
        wx.switchTab({ url: '/pages/explore/explore' })
      },
    })
  },
})
