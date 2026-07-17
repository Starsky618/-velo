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
const bindchart = require('../../utils/bindchart')
const { getCityLabel } = require('../../utils/city')
const { formatTime, formatDate } = require('../../utils/format')

// niceScale / formatNum 复用活动详情页用的同款工具（保持视觉风格一致）
const niceScale = bindchart.niceScale
const formatNum = bindchart.formatNum

/**
 * 把后端 elevation_profile（约 80 个海拔数值的均匀采样数组）
 * 转成绘图函数要的 [{distance, elevation}] 结构。
 *
 * 为什么 X 轴可以按 i/(N-1) 均匀分布：
 *   后端 _sample_elevation_profile 是按沿赛段参考线累计距离做的等距采样
 *   （app/segment/_geo_utils.py:38），不是按时间或点序号，
 *   所以 80 个采样点在地理上就是均匀间隔的，前端无需还原真实距离。
 *
 * 类比：把卷尺贴在地形侧面 80 个等间距标记点上拍照，每张照片记录该处海拔。
 *   现在要把这 80 张照片按"卷尺刻度"摆开 → 直接用 i/(N-1) * 总长度。
 *
 * @param {Array<number>} profile 海拔数值数组（米）
 * @param {number} totalDistanceKm 赛段总距离（公里）
 * @returns {Array<{distance: number, elevation: number}>}
 *   distance 单位公里，elevation 单位米。profile 为空或单点时返回 []。
 */
function buildElevationData(profile, totalDistanceKm) {
  if (!profile || profile.length < 2 || !totalDistanceKm || totalDistanceKm <= 0) {
    return []
  }
  // 后端已在固定物理网格上生成 GLO-30 成品剖面；前端只做轻度视觉圆滑，
  // 不再参与总爬升计算，也不改变保存的路线海拔快照。
  const smoothed = movingAverage(profile, 7)
  const n = smoothed.length
  const result = []
  for (let i = 0; i < n; i++) {
    result.push({
      distance: (i / (n - 1)) * totalDistanceKm,
      elevation: smoothed[i],
    })
  }
  return result
}

/**
 * 滑动平均平滑 / 比中位数更"圆滑"（中位数会留台阶 / 平均出曲线）。
 * 边界处窗口自动缩短不补 0（首末 ~3 点偏移真实值 0.5-1m / 视觉无感）。
 */
function movingAverage(arr, window) {
  const n = arr.length
  const half = Math.floor(window / 2)
  const out = []
  for (let i = 0; i < n; i++) {
    let sum = 0
    let count = 0
    for (let j = Math.max(0, i - half); j <= Math.min(n - 1, i + half); j++) {
      if (arr[j] != null) {
        sum += arr[j]
        count++
      }
    }
    out.push(count > 0 ? sum / count : arr[i])
  }
  return out
}

Page({
  data: {
    segmentId: 0,
    loading: true,
    notFound: false,
    // segmentLoadFailed：segment fetch 非 404 失败（500 / 网络）时的独立状态
    // 跟 notFound 分开避免误显示"赛段不存在"（同 user.js Critical-2 同 pattern）
    // Claude 综合审 I2 修：原版 segment fetch 非 404 失败时主页面渲染但 segment=null → 黑屏
    segmentLoadFailed: false,

    // 登录态 + 当前用户 ID（用作排行榜高亮 / 真字段 globalData.userInfo.id）
    isLoggedIn: false,
    myUserId: 0,

    // 区块 1：第一屏
    segment: null,
    cityLabel: '',
    elevationGainText: '',
    avgGradientText: '',
    hasElevationProfile: false,  // applySegment 里按 segment.elevation_profile 决定 true/false

    // 区块 2：AI 介绍
    shouldShowExpand: false,
    introExpanded: false,

    // 区块 3：我的记录（基于 EffortCompareResponse 6 字段）
    myEffort: null,             // 后端 6 字段对象
    myEffortDisplay: null,      // 前端渲染用：{ prTime, prDate, progressText }
    myEffortError: false,
    // task-4.4：双行结构 + N 项入口数据
    fromActivityId: null,       // 从骑行详情进入时带的 activity_id（决定是否显示"本次"行）
    currentAttempt: null,       // "本次"行渲染数据：{ time, date }（仅从 detail 进入且找到对应 effort 时）
    myEffortsCount: 0,          // "你的成绩 N 项" 中的 N（点击跳转 task-4.5 才接通）
    prDateFromEfforts: '',      // PR 那条 effort 的 created_at（applyMyEfforts 算出后给 applyMyEffort 用）

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

    // task-4.4：从骑行详情点进来时带 from_activity_id，让"我的记录"卡显示"本次"行
    // 从 explore / 通知进来不带 → 只显示 PR 行
    // task-4.4 Codex 异源审 I1：严格匹配纯数字串，防 "123abc" 这种脏参数被 parseInt 接受成 123
    // 把别人的 activity 误标"本次"
    const rawFromActivityId = options && options.from_activity_id
    const validFromActivityId = (typeof rawFromActivityId === 'string' && /^\d+$/.test(rawFromActivityId))
      ? parseInt(rawFromActivityId, 10)
      : null

    const app = getApp()
    // globalData.userInfo 在登录后才有 / 未登录时是 null
    const userInfo = (app.globalData && app.globalData.userInfo) || null
    const isLoggedIn = !!(app.globalData && app.globalData.token)

    this.setData({
      segmentId,
      fromActivityId: validFromActivityId,
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

    // task-4.4 task 4：我在该赛段的全部成绩（仅登录拉 / 失败静默 / 用来算"本次"+N 项）
    // 失败不显示错误（这部分是锦上添花 / PR/本次 失败时仍走 myEffort 的 PR 那行兜底）
    if (this.data.isLoggedIn) {
      tasks.push(
        api.getMySegmentEfforts(segmentId).catch(() => null),
      )
    } else {
      tasks.push(Promise.resolve(null))
    }

    Promise.all([
      // 仅 segment 走主路径 catch（404 → notFound / 其他错误 → toast）
      tasks[0].catch((err) => {
        if (err && err.code === 404) {
          this.setData({ notFound: true, loading: false })
          throw new Error('__notFound__')
        }
        // Claude 综合审 I2 修：500 / 网络错走独立 segmentLoadFailed 状态 / 不再黑屏
        wx.showToast({ title: '加载失败 请稍后重试', icon: 'none' })
        this.setData({ loading: false, segmentLoadFailed: true })
        throw new Error('__segmentFail__')
      }),
      tasks[1],
      tasks[2],
      tasks[3],
    ])
      .then(([segment, myEffort, leaderboard, myEfforts]) => {
        // applySegment 内部会触发 drawElevationProfile（setTimeout 100ms 兜底）
        this.applySegment(segment)
        this.applyMyEfforts(myEfforts)  // task-4.4：必须在 applyMyEffort 前算 prDate
        this.applyMyEffort(myEffort)
        this.applyLeaderboard(leaderboard)
        this.setData({ loading: false })
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
   *
   * 海拔曲线：调 buildElevationData 把 elevation_profile 转好喂给 drawElevationProfile，
   *   老赛段未生成时 elevationData=[] / hasElevationProfile=false → wxml 显示 placeholder。
   */
  applySegment(segment) {
    if (!segment) return

    const cityLabel = getCityLabel(segment.city)

    // 数字防御：null / undefined → ''（缺失时 wxml 整块隐藏，不显示 - 占位）
    const elevationGainText = (segment.elevation_gain === null || segment.elevation_gain === undefined)
      ? ''
      : Math.round(segment.elevation_gain)
    const avgGradientText = (segment.avg_gradient === null || segment.avg_gradient === undefined)
      ? ''
      : segment.avg_gradient.toFixed(1) + '%'

    // AI 介绍展开收起判断（80 字以上才显示展开按钮）
    const desc = segment.description || ''
    const shouldShowExpand = desc.length > 80

    // 海拔曲线：后端返 elevation_profile（约 80 个海拔数值，老赛段可能为 null）
    // segment.distance 单位是 km（service_query.py:180 已 /1000 转换），
    // 直接喂给 buildElevationData 算 X 轴位置；不要从 DB 直接拿 distance（单位米）
    const elevationData = buildElevationData(segment.elevation_profile, segment.distance)
    const hasElevationProfile = elevationData.length > 0
    // 不放 data 里：原始数组不用渲染到模板，避免 setData 序列化开销（同 detail.js 做法）
    this.elevationData = elevationData

    this.setData({
      segment,
      cityLabel,
      elevationGainText,
      avgGradientText,
      shouldShowExpand,
      hasElevationProfile,
    }, () => {
      // 海拔图绘制：setTimeout 100ms 兜底（CLAUDE.md 陷阱 #17）
      // 极慢机型 setData 回调时 canvas 2d node 仍未 ready，wx.nextTick 不够保险
      if (hasElevationProfile) {
        setTimeout(() => this.drawElevationProfile(), 100)
      }
    })

    // 设置导航栏标题（让用户在小程序最上方就看到赛段名）
    if (segment.name) {
      wx.setNavigationBarTitle({ title: segment.name })
    }
  },

  /**
   * 页面重新显示时重画 canvas
   *
   * 类比：某些低端机型把页面切到后台一会儿再切回来，canvas 节点像被
   *   "擦黑板"了一样，必须重画一遍才能看到图。
   *   弱机型保护性补绘，正常机型每次进页面只画一次。
   *
   * 这里用 wx.nextTick 而非 setTimeout(100ms)：onShow 是"切回前台"重绘场景，
   * canvas 节点早就挂载在 DOM 里，不像首次 setData 后还要等 canvas 2d node 初始化。
   * 跟 detail.js:123 的 onShow 同款做法。
   */
  onShow() {
    if (this.elevationData && this.elevationData.length > 0) {
      wx.nextTick(() => this.drawElevationProfile())
    }
  },

  /**
   * 画海拔曲线（Strava 风格灰色面积图）
   *
   * 整套配方与活动详情页 detail.js:322 drawElevationProfile 完全一致，
   * 让用户在活动详情和赛段详情看到的"地形侧面照"视觉风格统一：
   *   - 半透明灰色填充（地形的"身体"）
   *   - 顶部深灰描边（地形的"轮廓线"）
   *   - 4 档网格 + 左侧海拔刻度 + 底部距离刻度
   *
   * Retina 适配：手机屏幕 dpr=2/3，canvas 实际像素要放大 dpr 倍再 scale 缩回来，
   * 不然图形看起来模糊像素糊一坨。
   *
   * 数据要求：this.elevationData = [{distance: 公里, elevation: 米}]
   *   buildElevationData() 已经处理好，不会在这里再算累计距离。
   */
  drawElevationProfile() {
    const data = this.elevationData
    if (!data || data.length < 2) return

    wx.createSelectorQuery()
      .in(this)
      .select('#elevationCanvas')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0] || !res[0].node) return

        const canvas = res[0].node
        const width = res[0].width
        const height = res[0].height
        const ctx = canvas.getContext('2d')

        const dpr = wx.getSystemInfoSync().pixelRatio
        canvas.width = width * dpr
        canvas.height = height * dpr
        ctx.scale(dpr, dpr)

        ctx.clearRect(0, 0, width, height)

        const pad = { top: 12, right: 16, bottom: 28, left: 44 }
        const chartW = width - pad.left - pad.right
        const chartH = height - pad.top - pad.bottom

        // 数据范围
        let minEle = Infinity
        let maxEle = -Infinity
        const maxDist = data[data.length - 1].distance
        if (maxDist <= 0) return
        for (let i = 0; i < data.length; i++) {
          if (data[i].elevation < minEle) minEle = data[i].elevation
          if (data[i].elevation > maxEle) maxEle = data[i].elevation
        }

        // Y 轴上下各留 10% 余量，至少 20m 范围（防纯平路图形退化）
        let eleRange = maxEle - minEle
        if (eleRange < 20) eleRange = 20
        minEle = Math.floor(minEle - eleRange * 0.1)
        maxEle = Math.ceil(maxEle + eleRange * 0.1)
        eleRange = maxEle - minEle

        const toX = (dist) => pad.left + (dist / maxDist) * chartW
        const toY = (ele) => pad.top + (1 - (ele - minEle) / eleRange) * chartH

        // 1. 网格线（最浅灰）
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.08)'
        ctx.lineWidth = 0.5

        const yTicks = niceScale(minEle, maxEle, 4)
        for (let t = 0; t < yTicks.length; t++) {
          const y = toY(yTicks[t])
          ctx.beginPath()
          ctx.moveTo(pad.left, y)
          ctx.lineTo(width - pad.right, y)
          ctx.stroke()
        }

        const xTicks = niceScale(0, maxDist, 4)
        for (let t = 0; t < xTicks.length; t++) {
          if (xTicks[t] <= 0) continue
          const x = toX(xTicks[t])
          ctx.beginPath()
          ctx.moveTo(x, pad.top)
          ctx.lineTo(x, pad.top + chartH)
          ctx.stroke()
        }

        // 2. 边框
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.12)'
        ctx.lineWidth = 0.5
        ctx.strokeRect(pad.left, pad.top, chartW, chartH)

        // 3. 灰色面积填充
        ctx.beginPath()
        ctx.moveTo(toX(data[0].distance), toY(data[0].elevation))
        for (let i = 1; i < data.length; i++) {
          ctx.lineTo(toX(data[i].distance), toY(data[i].elevation))
        }
        ctx.lineTo(toX(data[data.length - 1].distance), pad.top + chartH)
        ctx.lineTo(toX(data[0].distance), pad.top + chartH)
        ctx.closePath()
        ctx.fillStyle = 'rgba(190, 190, 190, 0.5)'
        ctx.fill()

        // 4. 顶部轮廓描边
        ctx.beginPath()
        ctx.moveTo(toX(data[0].distance), toY(data[0].elevation))
        for (let i = 1; i < data.length; i++) {
          ctx.lineTo(toX(data[i].distance), toY(data[i].elevation))
        }
        ctx.strokeStyle = 'rgba(150, 150, 150, 0.9)'
        ctx.lineWidth = 1.5
        ctx.stroke()

        // 5. 坐标轴标签
        ctx.fillStyle = 'rgba(0, 0, 0, 0.4)'
        ctx.font = '10px -apple-system, sans-serif'

        ctx.textAlign = 'right'
        ctx.textBaseline = 'middle'
        for (let t = 0; t < yTicks.length; t++) {
          const yPos = toY(yTicks[t])
          const label = yTicks[t] >= 1000 ? formatNum(yTicks[t]) : String(yTicks[t])
          ctx.fillText(label, pad.left - 6, yPos)
        }

        ctx.textAlign = 'left'
        ctx.textBaseline = 'top'
        ctx.fillText('m', 4, pad.top + chartH + 4)

        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        for (let t = 0; t < xTicks.length; t++) {
          if (xTicks[t] <= 0) continue
          ctx.fillText(xTicks[t] + ' km', toX(xTicks[t]), pad.top + chartH + 8)
        }
      })
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

    // task-4.4：PR 日期来自 my-efforts 接口（在 applyMyEfforts 里已存到 data.prDateFromEfforts）
    // 兜底：my-efforts 失败时不显示日期（仅显示用时 / 跟 task-4.4 前的体验一致）
    this.setData({
      myEffort,
      myEffortDisplay: {
        prTime: formatTime(pr),
        prDate: this.data.prDateFromEfforts || '',
        progressText,
      },
    })
  },

  /**
   * 应用 my-efforts 数据（task-4.4：算"本次"行 + "你的成绩 N 项"入口 + PR 日期）
   *
   * 三件事：
   *   1. myEffortsCount：N 项入口的数字（点击跳转 task-4.5 才接通）
   *   2. currentAttempt：从骑行详情进入时，找到对应 activity_id 那条 effort 作"本次"行
   *   3. prDateFromEfforts：找到 is_pr=true 那条 effort 的 created_at 给 PR 行做日期标签
   *
   * 必须在 applyMyEffort 之前调用——后者会从 data.prDateFromEfforts 取日期拼到 myEffortDisplay。
   */
  applyMyEfforts(myEfforts) {
    if (!myEfforts || !myEfforts.items || myEfforts.items.length === 0) {
      this.setData({
        myEffortsCount: 0,
        currentAttempt: null,
        prDateFromEfforts: '',
      })
      return
    }

    const items = myEfforts.items
    const fromActivityId = this.data.fromActivityId

    // 本次：仅当从骑行详情带 from_activity_id 进入时才找
    let currentAttempt = null
    if (fromActivityId) {
      const found = items.find((e) => e.activity_id === fromActivityId)
      if (found) {
        currentAttempt = {
          time: formatTime(found.elapsed_time),
          date: formatDate(found.created_at),
        }
      }
    }

    // PR 日期：找 is_pr=true 那条（task-4.3 已保证只有 1 条）
    let prDateFromEfforts = ''
    const prItem = items.find((e) => e.is_pr === true)
    if (prItem) {
      prDateFromEfforts = formatDate(prItem.created_at)
    }

    this.setData({
      myEffortsCount: items.length,
      currentAttempt,
      prDateFromEfforts,
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

    // 我有成绩但不在 top 10 → 显示独立行（D7 hotfix 2026-05-10 后端补真 my_rank）
    // 后端 LeaderboardResponse 现在直接返 my_rank + my_elapsed_time
    // 优先用后端真值 / fallback 到 myEffort.pr_elapsed_time（防 leaderboard 拿到但 my 字段 null）
    let myRankOutOfTop = false
    let myRankRow = null
    if (this.data.isLoggedIn && !meInTop) {
      const myRank = leaderboard.my_rank
      const myTime = leaderboard.my_elapsed_time
      if (myRank !== null && myRank !== undefined && myTime !== null && myTime !== undefined) {
        // 后端真 my_rank：精确显示"#23"等
        myRankOutOfTop = true
        myRankRow = {
          rank: '#' + myRank,
          timeFormatted: formatTime(myTime),
        }
      } else {
        // fallback：myEffort 兜底（后端 my_rank=None 但 myEffort 有 PR 的罕见路径）
        const myEffort = this.data.myEffort
        if (myEffort && myEffort.pr_elapsed_time !== null && myEffort.pr_elapsed_time !== undefined) {
          myRankOutOfTop = true
          myRankRow = {
            rank: '#',  // 后端 my_rank 缺失 / 用 # 占位（罕见路径 / 防误显示具体名次）
            timeFormatted: formatTime(myEffort.pr_elapsed_time),
          }
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

    // task-4.4 B 审 I1：同时重拉 my-efforts，否则首次 my-efforts 失败时 prDateFromEfforts 永远为空
    // → PR 行只显示用时不显示日期（即使重试 myEffort 成功也救不回来）
    Promise.all([
      api.getMySegmentEffort(this.data.segmentId),
      api.getMySegmentEfforts(this.data.segmentId).catch(() => null),  // 静默失败 / 维持现有 prDateFromEfforts
    ])
      .then(([myEffort, myEfforts]) => {
        // 必须 applyMyEfforts 先（写 prDateFromEfforts），再 applyMyEffort（读 prDateFromEfforts 拼 myEffortDisplay）
        if (myEfforts) this.applyMyEfforts(myEfforts)
        this.applyMyEffort(myEffort)
        // Claude 综合审 I3 修：重试 myEffort 成功后必须重算 leaderboard.myRankRow
        // 否则首次 myEffort 失败 + 当时不在 top 10 → 重试成功后独立行永远不出现 → D7 反转失效
        if (this.data.leaderboard) this.applyLeaderboard(this.data.leaderboard)
      })
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
   * 跳转"我的成绩"全屏列表页（task-4.5）
   * 入口：区块 3 底部"你的成绩 N 项 ›"
   */
  goMyEfforts() {
    // 跟 segment-efforts.js onLoad 入口校验风格统一（严格正整数）
    const id = this.data.segmentId
    if (typeof id !== 'number' || !Number.isInteger(id) || id <= 0) return
    wx.navigateTo({ url: '/pages/segment-efforts/segment-efforts?segment_id=' + id })
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
