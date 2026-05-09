/**
 * 用户详情页 — 看骑友主页（4.3 新建 / 不是看自己）
 *
 * 这个文件是干什么的：
 *   骑友 A 在动态里看到骑友 B 上传的活动 → 点击 B 的头像 → 跳到这个页面看 B 的主页。
 *   展示 B 的公开信息（昵称 / city / 累计统计 / 功率曲线 / 热力图），
 *   严格隐藏 B 的敏感字段（FTP / 体重 / 手机号 / 第三方 token）。
 *
 *   类比：就像微信加好友前看对方的"个人名片"——
 *   你能看到对方的昵称、城市、朋友圈封面，
 *   但看不到对方的手机号、QQ 号、银行卡——这些是私密字段不该出现。
 *
 * 操作注意事项：
 *   1. **看自己 → 直接跳个人 tab**（user.js onLoad 里 switchTab）：
 *      - 避免"个人 tab + 用户详情页"双视图同时显示自己的混乱
 *      - 比较字段：app.globalData.userInfo.id（不是 .userId / 起手 grep 实证）
 *   2. **D-P08 隐私白名单**：模板严格不放 FTP / 体重 / W·kg
 *      - 后端 GET /api/user/{user_id}/profile 已严格白名单（不返敏感字段）
 *      - 前端模板也只展示昵称 / city / 累计统计（双重防御）
 *   3. **3 个 fetch 互不影响**：
 *      - profile 失败 → 全页错误（核心信息缺失）
 *      - power-curve / heatmap 失败 → 那个 card 自己 setData(error)（D21 component 自治）
 *      - 本 page 只 fetch profile / 不持有 power-curve + heatmap 数据
 *
 * 输入输出：
 *   输入：query.id（目标用户 ID / parseInt 后必须 > 0）
 *   输出：渲染 4 状态视图（loading / 404 / 数据齐 / 看自己跳走）
 */

const api = require('../../utils/api')
const { getCityLabel } = require('../../utils/city')
const app = getApp()

Page({
  data: {
    // userId：从 query 解析 / 传给 component 做看自己 vs 看他人分流
    userId: 0,
    // 5 状态：loading / notFound / loadFailed / 渲染态（profile 非空）/ 看自己跳走（不渲染）
    loading: true,
    notFound: false,
    // loadFailed：非 404 错误（500 / 网络断 / 后端故障）/ 跟 notFound 分开避免误导
    // ("用户不存在" 文案专给 404 / 网络错应说"加载失败 重试")
    loadFailed: false,
    // 用户公开信息（只含白名单字段 / 后端 D-P08 已严格过滤）
    profile: null,
    // city 中文标签（''时模板 wx:if 不显示 badge）
    cityLabel: '',
    // 累计统计：从 profile 计算（后端 UserProfileResponse 已含
    // total_distance_km / activity_count / total_elevation_m / current_month_summary）
    stats: null,
  },

  /**
   * onLoad 接收 query.id
   *
   * 流程：
   *   1. 解析 query.id → 校验合法（数值 > 0）
   *   2. 看自己 → switchTab 个人 tab（return / 不走 fetch）
   *   3. 看他人 → setData userId + loading → fetchProfile
   */
  onLoad(options) {
    const userId = parseInt(options && options.id, 10)
    if (!userId || isNaN(userId) || userId <= 0) {
      wx.showToast({ title: '无效用户', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 1500)
      return
    }

    // 看自己跳个人 tab（避免双视图混淆 / D-P08 自检三问 #2）
    // 比较字段：app.globalData.userInfo.id（globalData 没有 userId 直字段 / 起手 grep 实证）
    if (this.isMyId(userId)) {
      wx.switchTab({ url: '/pages/profile/profile' })
      return
    }

    this.setData({ userId: userId, loading: true })
    this.fetchProfile(userId)
  },

  /**
   * 判断是不是当前登录用户自己（避免双视图混淆）
   *
   * 注意：globalData.userInfo 在 app.login() / profile.fetchUserData() 后才存在，
   * 未登录时直接 navigateTo /pages/user/user?id=X 也合法（看他人公开信息不需要登录验证）。
   * 未登录 → app.globalData.userInfo 是 null → return false → 正常走 fetch 流程。
   */
  isMyId(targetId) {
    const userInfo = app.globalData && app.globalData.userInfo
    return !!(userInfo && userInfo.id === targetId)
  },

  /**
   * 拉取目标用户的公开 profile
   *
   * 职责单一：本 page 只 fetch profile / 不 fetch power-curve / 不 fetch heatmap。
   * power-curve + heatmap 由对应 component 自治（D21 / 内部基于 props.userId 自动 fetch）。
   * 好处：profile 失败显示全页 404 / power-curve / heatmap 失败只影响自己卡片。
   *
   * @param {number} userId - 目标用户 ID
   */
  fetchProfile(userId) {
    api.getUserProfile(userId)
      .then((data) => {
        // 后端契约（schemas.py L192-220 UserProfileResponse 严格白名单）：
        //   { id, nickname, avatar_url, city, bike_type,
        //     total_distance_km, total_elevation_m, activity_count, current_month_summary }
        // 不含敏感字段（FTP / weight / phone / openid / strava_token）— 后端 endpoint 严格保证
        const cityLabel = getCityLabel(data.city)
        // 累计统计字段映射：后端字段名（total_distance_km / activity_count / total_elevation_m）
        // → 模板字段名（distance / rides / elevation_gain）/ 模板更短更直观
        // 后端 schema 是 NOT NULL / 总是返 / 但仍用 || 0 防御异常 response
        const stats = {
          distance: Math.round((data.total_distance_km || 0) * 10) / 10,  // 保留 1 位小数
          rides: data.activity_count || 0,
          elevation_gain: Math.round(data.total_elevation_m || 0),
        }
        this.setData({
          profile: data,
          cityLabel: cityLabel,
          stats: stats,
          loading: false,
        })
      })
      .catch((err) => {
        // 错误分流（Codex 异源审 Critical-2）：404 → "用户不存在" 文案 / 401 → 跳登录 /
        // 500 / 网络错 → "加载失败" 文案。**严格不让非 404 落到"用户不存在"分支**——
        // 否则后端故障 / 无网会让用户误以为对方注销了。
        const code = err && err.code
        if (code === 404) {
          this.setData({ notFound: true, loading: false })
        } else if (code === 401) {
          // token 失效 / 未登录 → 提示后跳个人 tab 触发重新登录流程
          wx.showToast({ title: '请先登录', icon: 'none' })
          setTimeout(() => wx.switchTab({ url: '/pages/profile/profile' }), 1500)
          this.setData({ loading: false })
        } else {
          // 500 / 网络断 / 其他后端故障 → 走独立 loadFailed 状态（不复用 404 文案）
          wx.showToast({
            title: (err && err.message) || '加载失败',
            icon: 'none',
          })
          this.setData({ loading: false, loadFailed: true })
        }
      })
  },

  /**
   * 404 / 错误状态点击"返回"按钮
   */
  goBack() {
    wx.navigateBack({
      fail: () => {
        // 没有上一页（直接打开 user/user?id=X 的场景）→ 跳首页
        wx.switchTab({ url: '/pages/home/home' })
      },
    })
  },
})
