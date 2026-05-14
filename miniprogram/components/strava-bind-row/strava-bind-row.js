/**
 * Strava 绑定入口 component（自治 / D21 模块化哲学）
 *
 * ─── 这个组件是干什么的 ─────────────────────────────
 * 在"我的"页菜单卡里展示一行"Strava 账号"+ 绑定状态。
 * 用户点击未绑定的行 → 调后端拿授权链接 → 复制到剪贴板 + 弹窗
 * 引导去微信内置浏览器粘贴打开 Strava 授权页 → 授权成功后 Strava
 * 跳回我们后端 /api/strava/callback 显示 HTML 成功页 → 用户回小程序
 * → 本 component 在 page show 时重拉 status → 显示"✓ 已绑定"。
 *
 * 之后用户的新 Strava 活动通过 v4 期已有的 webhook + scheduler
 * 自动同步进 velo（本 component 不管自动同步，只管"开关那一下"）。
 *
 * ─── 为什么自治 ────────────────────────────────
 * 沿用 power-curve-card / heatmap-card 同款 D21 模式：
 * - profile.js 不感知 Strava，只在菜单卡里写 `<strava-bind-row />` 一行
 * - 未来挪位置（移到独立卡 / 设置页 / 其他 tab）只改一行 wxml
 * - status 拉取 / 错误 / loading 全在 component 内部，互不影响
 *
 * ─── 数据流 ─────────────────────────────────────
 *   attached → _fetchStatus()                            // 首次进页
 *   pageLifetimes.show → _fetchStatus()                  // 每次切回"我的"tab 重拉（用户授权完回来生效）
 *     GET /api/strava/status → { connected: bool, athlete_id, ... }
 *
 *   点击未绑定行 → _onTap()
 *     ├ 已绑定 → 静默 return（不弹窗 / 不显示"已绑定，要解绑吗"——未来需求再加）
 *     └ 未绑定 → GET /api/strava/authorize → { authorize_url }
 *                → wx.setClipboardData(authorize_url)
 *                → wx.showModal 引导用户去浏览器粘贴
 *
 * ─── 状态机 ─────────────────────────────────────
 *   loading（初始 true）→ connected=true / connected=false / 静默失败默认 connected=false
 *
 * ─── 注意事项 ────────────────────────────────────
 * 1. status 拉取失败默认按"未绑定"显示——用户最坏体验 = 多走一遍 OAuth，
 *    后端 handle_callback 已经处理"重复绑定同一 athlete_id"返回 200 不会出错（service_oauth 实证）
 * 2. wx.setClipboardData 会自带 toast"内容已复制"——所以 showModal 文案不要重复说"已复制"
 * 3. 小程序 web-view 不能加载 strava.com（非业务域名），所以**只能**走剪贴板 + 浏览器路径
 * 4. v4 期 OAuth scope 已经是 activity:read_all（含私密活动 / CLAUDE.md 陷阱清单 #20）
 */

const api = require('../../utils/api')

Component({
  data: {
    loading: true,
    connected: false,
  },

  lifetimes: {
    attached: function () {
      this._fetchStatus()
    },
  },

  // pageLifetimes：父 page 的生命周期事件，每次切到"我的"tab 都触发
  // 用户在浏览器完成授权回小程序时，profile 的 onShow 触发 → 我们的 show 触发 → 重拉 status
  pageLifetimes: {
    show: function () {
      // attached 已经拉过一次，但 page show 是每次切 tab 都跑——
      // 这是"用户授权完回来生效"的关键钩子
      this._fetchStatus()
    },
  },

  methods: {
    /**
     * 拉绑定状态
     *
     * 类比：进门看一眼门口的"绑定状态牌"——
     * 牌子绿色 = 已绑 / 灰色 = 未绑 / 牌子掉了 = 当未绑处理（让用户重新走一遍流程兜底）
     */
    _fetchStatus: function () {
      const that = this
      api.get('/api/strava/status')
        .then(function (data) {
          that.setData({
            loading: false,
            connected: !!(data && data.connected),
          })
        })
        .catch(function () {
          // 失败默认按未绑定显示（401 / 网络 / 5xx 全归一态）
          // 后端 handle_callback 对重复绑定同一 athlete_id 幂等（200）→ 用户多点一次没事
          that.setData({ loading: false, connected: false })
        })
    },

    /**
     * 点击菜单行
     *
     * 已绑定：静默 return（未来要加"解绑"再扩，现在先不做 / Tim 拍尽量自动化）
     * 未绑定：调 authorize 拿 URL → 剪贴板 + 弹窗引导
     */
    _onTap: function () {
      if (this.data.loading) return       // 状态没拉回来不响应
      if (this.data.connected) return     // 已绑定不弹窗（未来加解绑再扩）

      const that = this
      wx.showLoading({ title: '准备授权链接…' })

      api.get('/api/strava/authorize')
        .then(function (data) {
          wx.hideLoading()
          const url = data && data.authorize_url
          if (!url) {
            wx.showToast({ title: '后端未返链接', icon: 'none' })
            return
          }
          // setClipboardData 自带"内容已复制"toast → showModal 文案不重复说复制
          wx.setClipboardData({
            data: url,
            success: function () {
              wx.showModal({
                title: '前往 Strava 授权',
                content: '授权链接已复制。请打开微信「发现 → 搜一搜」或发给"文件传输助手"，粘贴该链接并点击打开，完成 Strava 登录授权后回到本页。',
                showCancel: false,
                confirmText: '我去授权',
              })
            },
            fail: function () {
              // 极少数机型 setClipboardData 失败 → 把链接直接 modal 展示让用户长按选中
              wx.showModal({
                title: '请复制链接到浏览器',
                content: url,
                showCancel: false,
                confirmText: '知道了',
              })
            },
          })
        })
        .catch(function (err) {
          wx.hideLoading()
          // 401 已被 api.js 统一处理（清 token + 跳登录提示），这里捕获其他错误
          if (err && err.code === 401) return
          wx.showToast({
            title: (err && err.message) || '获取授权链接失败',
            icon: 'none',
          })
        })
        .finally(function () {
          // 兜底：如果 success 路径里 hideLoading 没跑（极端情况），这里再保险一次
          wx.hideLoading()
        })
    },
  },
})
