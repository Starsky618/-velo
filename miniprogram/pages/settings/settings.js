/**
 * 设置页 — 用户的"控制台"（Sprint 6 task-5 大幅扩写）
 *
 * 干啥用：
 *   把三件用户每天不点 / 但关键时刻一定要能点到的事集中管理：
 *   1. 改 FTP（账号资料 / 后续可扩 weight / 车辆等）
 *   2. 解绑 Strava（第三方账号 / 不删历史活动 / 仅停止后续同步）
 *   3. 退出登录（清 token + 跳回 profile）
 *
 * 类比：
 *   手机系统设置——平时不进，要换号/退账/改重要参数时第一时间能找到入口。
 *
 * 数据流：
 *   - onShow：拉 GET /api/user/profile（FTP）+ GET /api/strava/status（bound）
 *   - 改 FTP：wx.showModal editable → PUT /api/user/profile { ftp }
 *   - 解绑 Strava：wx.showModal confirm → POST /api/strava/unbind（204）
 *   - 退出：wx.showModal confirm → app.logout() + wx.redirectTo /profile
 *
 * 红线（v0.2/v0.3 task 卡 / 永久规则）：
 *   - 解绑 / 退出**强制二次确认**（wx.showModal confirm）
 *   - FTP 范围 50-500 前后双重校验（前端拒收 + 后端 422）
 *   - bound 状态走 GET /api/strava/status 的 bound 字段（不从 profile 拉 strava_athlete_id）
 *   - "-" 占位符永久规则：FTP 未设时显示 "未设置"（不是 "-"）
 *
 * 注意事项：
 *   - 进入设置页前已要求登录态（"我的"页设置 icon 仅登录后显示 / task-4）
 *     兜底仍判 app.globalData.token —— 防 deep link 或缓存异常情况
 *   - 二次确认按钮颜色：confirmColor #e64340 (system red) 高对比 / 防误点
 *   - 函数名 onUnbindStrava / onBindStrava 与 wxml bindtap 严格对齐（前端协议自校验 / Sprint 5 task-3 教训）
 */

const api = require('../../utils/api')
const app = getApp()

Page({
  data: {
    ftp: null,
    weight: null,                  // Sprint 9 task-6：体重（kg）/ 可选 / 算 W/kg 用
    birthYear: null,               // Sprint 10：出生年份 / 后端不存 age / 用来兜底估算最大心率
    displayAge: null,              // Sprint 10：前端展示年龄 / 不回写后端
    birthYearOptions: [],          // 出生年份滚轮选项：今年 → 1900
    birthYearIndex: 0,             // 当前出生年份在滚轮里的位置
    maxHr: null,                   // Sprint 10：最大心率 / FTP 自动估算的心率门槛
    stravaBound: false,
    // Sprint 9 task-6：FTP 估算弹窗状态
    ftpEstimateModal: false,       // 弹窗显隐
    estimateResult: null,          // EstimationResultResponse / { ftp, confidence, method, r2 }
    // Sprint 9 task-8：FTP Breakthrough 弹窗状态（worker 自动检测出的突破事件）
    breakthroughModal: false,      // 弹窗显隐
    breakthroughEvent: null,       // BreakthroughEventResponse / { id, old_ftp, suggested_ftp, ... }
  },

  /**
   * onShow 而不是 onLoad：从子流程（如 Strava 授权回浏览器再回小程序）返回时
   * 也能拉到最新状态。
   */
  onShow() {
    // 兜底：未登录直接跳回 profile（理论上"我的"页设置入口已挡 / 双保险）
    if (!app.globalData.token) {
      wx.redirectTo({ url: '/pages/profile/profile' })
      return
    }
    this._ensureBirthYearOptions()
    this._fetchProfile()
    this._fetchStravaStatus()
    // Sprint 9 task-8：每次进 settings 时拉 pending breakthrough / 有则弹窗
    this._checkPendingBreakthroughs()
  },

  /**
   * 拉当前用户 profile（取 FTP 字段）
   * 失败静默处理：进入设置页不应因网络问题阻断主流程 / FTP 显示"未设置"即可
   */
  _fetchProfile() {
    api.get('/api/user/profile')
      .then((p) => {
        const birthYear = p.birth_year != null ? p.birth_year : null
        const birthYearIndex = this._birthYearIndex(birthYear)
        // 三审 Important 修：用 != null 不用 ||（防 truthiness 陷阱 / 即使 ftp=0 也不会被当 null）
        // FTP schema 范围 50-500 / 实际 0 不会出现 / 但防御性写法
        // Sprint 9 task-6：同步拉 weight / 一起 setData（避免两次渲染闪烁）
        this.setData({
          ftp: p.ftp != null ? p.ftp : null,
          weight: p.weight != null ? p.weight : null,
          birthYear: birthYear,
          displayAge: this._ageFromBirthYear(birthYear),
          birthYearIndex: birthYearIndex,
          maxHr: p.max_hr != null ? p.max_hr : null,
        })
      })
      .catch((err) => {
        if (err && err.code === 401) {
          // token 已被 api.js 清掉 / 跳回 profile
          wx.redirectTo({ url: '/pages/profile/profile' })
        }
      })
  },

  /**
   * 用出生年份现算展示年龄。
   *
   * 类比：后端保存“出生年份”这张出生证明；前端每次打开设置页时，
   * 再用今年减一下，得到不会过期的年龄展示。
   */
  _ageFromBirthYear(birthYear) {
    if (!birthYear) return null
    const age = new Date().getFullYear() - birthYear
    if (age <= 0 || age > 100) return null
    return age
  },

  /**
   * 初始化出生年份滚轮选项。
   *
   * 类比：把 1900 年到今年做成一排刻度，picker 滚轮只负责选刻度；
   * 真正存库的还是 birth_year，不存会过期的 age。
   */
  _ensureBirthYearOptions() {
    if (this.data.birthYearOptions.length > 0) return
    const currentYear = new Date().getFullYear()
    const options = []
    for (let year = currentYear; year >= 1900; year--) {
      options.push(year)
    }
    this.setData({ birthYearOptions: options })
  },

  /**
   * 找出生年份在滚轮里的位置；没设置时默认落在约 30 岁，少滚一点。
   */
  _birthYearIndex(birthYear) {
    this._ensureBirthYearOptions()
    const currentYear = new Date().getFullYear()
    if (!birthYear) {
      const defaultIndex = this.data.birthYearOptions.indexOf(currentYear - 30)
      return defaultIndex >= 0 ? defaultIndex : 0
    }
    const index = this.data.birthYearOptions.indexOf(birthYear)
    return index >= 0 ? index : 0
  },

  /**
   * 拉 Strava 绑定状态
   * 实证字段：app/strava/service_token.py:71 返字段 = "bound" (boolean / "connected" 别名同义)
   */
  _fetchStravaStatus() {
    api.get('/api/strava/status')
      .then((s) => {
        this.setData({ stravaBound: !!s.bound })
      })
      .catch(() => {
        // 静默：拉不到默认显示"未绑定"，点"绑定"按钮可触发完整 OAuth 流程
      })
  },

  onEditFtp() {
    const that = this
    wx.showActionSheet({
      itemList: [
        this.data.ftp ? '手动修改 FTP' : '手动填写 FTP',
        this.data.ftp ? '重新估算 FTP' : '让系统估算',
      ],
      success: function (res) {
        if (res.tapIndex === 0) {
          that._showEditFtpModal()
          return
        }
        if (res.tapIndex === 1) {
          that.onEstimateFtp()
        }
      },
    })
  },

  /**
   * 手动编辑 FTP——wx.showModal editable 唤起原生输入框
   *
   * 校验顺序：
   *   1. 用户取消 → 直接 return（不弹 toast）
   *   2. 解析整数 + 边界 50-500 → 不通过 toast 提示用户
   *   3. PUT 后端 → 后端再次 422 兜底（schema Field ge=50 le=500）
   */
  _showEditFtpModal() {
    const that = this
    wx.showModal({
      title: '编辑 FTP',
      content: '',
      editable: true,
      placeholderText: '请输入 50-500 之间的整数',
      success: function (res) {
        if (!res.confirm) return                 // 用户点取消
        const raw = (res.content || '').trim()
        if (!raw) return                          // 空输入静默忽略
        const ftp = parseInt(raw, 10)
        if (isNaN(ftp) || ftp < 50 || ftp > 500) {
          wx.showToast({ title: 'FTP 范围 50-500', icon: 'none' })
          return
        }
        api.put('/api/user/profile', { ftp: ftp })
          .then(function () {
            that.setData({ ftp: ftp })
            wx.showToast({ title: 'FTP 已更新', icon: 'success' })
          })
          .catch(function (err) {
            wx.showToast({
              title: (err && err.message) || '更新失败',
              icon: 'none',
            })
          })
      },
    })
  },

  /**
   * 编辑体重（Sprint 9 task-6）——wx.showModal editable 唤起原生输入框
   *
   * 干啥用：可选填字段 / 用于算 W/kg（功重比）/ 影响详情页 power_per_kg 展示
   *
   * 校验：
   *   1. 用户取消 → 直接 return
   *   2. 空输入 → 静默忽略（不强制必填）
   *   3. 解析浮点数 + 范围 30.0-200.0 → 不通过 toast
   *   4. PUT /api/user/profile { weight } → 后端 schema Field ge=30.0 le=200.0 兜底
   */
  onEditWeight() {
    const that = this
    const current = this.data.weight ? String(this.data.weight) : ''
    wx.showModal({
      title: '编辑体重',
      content: '',
      editable: true,
      placeholderText: current || '请输入 30-200 之间的体重（kg）',
      success: function (res) {
        if (!res.confirm) return
        const raw = (res.content || '').trim()
        if (!raw) return
        const weight = parseFloat(raw)
        if (isNaN(weight) || weight < 30 || weight > 200) {
          wx.showToast({ title: '体重范围 30-200 kg', icon: 'none' })
          return
        }
        api.put('/api/user/profile', { weight: weight })
          .then(function () {
            that.setData({ weight: weight })
            wx.showToast({ title: '体重已更新', icon: 'success' })
          })
          .catch(function (err) {
            wx.showToast({
              title: (err && err.message) || '更新失败',
              icon: 'none',
            })
          })
      },
    })
  },

  /**
   * 滚轮选择出生年份——只存年份，不存动态 age。
   *
   * 类比：身份证上写的是出生年份；年龄每天都会变，后端按当前年份临时算。
   * 这个字段只在用户没填最大心率时兜底，估算置信度最多 low。
   */
  onBirthYearPickerChange(e) {
    const that = this
    const index = Number(e.detail.value)
    const birthYear = this.data.birthYearOptions[index]
    if (!birthYear) return

    api.put('/api/user/profile', { birth_year: birthYear })
      .then(function () {
        that.setData({
          birthYear: birthYear,
          displayAge: that._ageFromBirthYear(birthYear),
          birthYearIndex: index,
        })
        wx.showToast({ title: '出生年份已更新', icon: 'success' })
      })
      .catch(function (err) {
        wx.showToast({
          title: (err && err.message) || '更新失败',
          icon: 'none',
        })
      })
  },

  /**
   * 编辑最大心率——优先用于 FTP 估算的心率门槛。
   *
   * 类比：最大心率像门锁的钥匙；没有钥匙只能用年龄公式估一把备用钥匙，
   * 所以后端会把这种估算的置信度压低。
   */
  onEditMaxHr() {
    const that = this
    const current = this.data.maxHr ? String(this.data.maxHr) : ''
    wx.showModal({
      title: '编辑最大心率',
      content: '',
      editable: true,
      placeholderText: current || '请输入 120-220 之间的整数',
      success: function (res) {
        if (!res.confirm) return
        const raw = (res.content || '').trim()
        if (!raw) return
        const maxHr = parseInt(raw, 10)
        if (isNaN(maxHr) || maxHr < 120 || maxHr > 220) {
          wx.showToast({ title: '最大心率范围 120-220', icon: 'none' })
          return
        }
        api.put('/api/user/profile', { max_hr: maxHr })
          .then(function () {
            that.setData({ maxHr: maxHr })
            wx.showToast({ title: '最大心率已更新', icon: 'success' })
          })
          .catch(function (err) {
            wx.showToast({
              title: (err && err.message) || '更新失败',
              icon: 'none',
            })
          })
      },
    })
  },

  /**
   * Sprint 9 task-6：让系统估算 FTP
   *
   * 干啥用：不知道自己 FTP 时 / 一键跑 CP 3-param 模型从历史活动算 FTP
   *
   * 流程：
   *   1. showLoading "估算中"（最长 3 秒 / 后端跑 scipy curve_fit 一般 < 1 秒）
   *   2. GET /api/user/me/ftp-estimate → EstimationResultResponse
   *   3. 弹自定义 modal 显示结果 / 用户点"用这个" → onAcceptEstimate / 点"手动填" → 打开手动输入
   *
   * 失败兜底：estimator 抛异常 → 500 → catch toast "估算失败 请手动填"
   * insufficient 兜底：返 ftp=null → modal 显示"历史活动数据不足"引导手动填
   */
  onEstimateFtp() {
    const that = this
    wx.showLoading({ title: '估算中…', mask: true })
    api.get('/api/user/me/ftp-estimate')
      .then(function (result) {
        wx.hideLoading()
        that.setData({
          ftpEstimateModal: true,
          estimateResult: result,
        })
      })
      .catch(function (err) {
        wx.hideLoading()
        wx.showToast({
          title: (err && err.message) || '估算失败 / 请手动填',
          icon: 'none',
          duration: 2500,
        })
      })
  },

  /**
   * Sprint 9 task-6：接受估算结果 / 写入 FTP
   *
   * 点"用这个值" → PUT /api/user/profile { ftp } → 触发 task-4 首次填 ftp 回填
   * （RQ worker 异步把该用户所有 snapshot_ftp=NULL 的历史活动补登 + 重算 IF/TSS）
   *
   * 乐观更新：本地直接刷 ftp + 关弹窗 / 不等后端响应（失败时 toast 提示）
   */
  onAcceptEstimate() {
    const that = this
    const ftp = this.data.estimateResult && this.data.estimateResult.ftp
    if (!ftp) {
      // 防御：理论上 ftp=null 时按钮 wx:if 不显示 / 这里兜底
      this.setData({ ftpEstimateModal: false })
      return
    }
    // task-6 Important fix (2026-05-21 quality reviewer)：toast 文案条件化
    // task-4 backfill 仅"首次填 ftp（user.ftp NULL → 非 NULL）"触发
    // 若用户已有 ftp 现在改值 = 不触发回填 / 不该误导"正在算历史活动"
    const isFirstTimeFill = this.data.ftp == null
    api.put('/api/user/profile', { ftp: ftp })
      .then(function () {
        that.setData({
          ftp: ftp,
          ftpEstimateModal: false,
          estimateResult: null,
        })
        wx.showToast({
          title: isFirstTimeFill ? 'FTP 已保存 / 正在算历史活动' : 'FTP 已更新',
          icon: 'success',
          duration: 2500,
        })
      })
      .catch(function (err) {
        wx.showToast({
          title: (err && err.message) || 'FTP 保存失败',
          icon: 'none',
        })
      })
  },

  /**
   * Sprint 9 task-6：关闭估算弹窗（点遮罩 / 点取消都走这里）
   */
  onCloseEstimateModal() {
    this.setData({
      ftpEstimateModal: false,
      estimateResult: null,
    })
  },

  /**
   * 系统估算不可用时，直接接到手动 FTP 输入框。
   *
   * 类比：先把当前弹窗这扇门关上，再打开手动填写的小窗口；
   * setTimeout 让小程序先完成遮罩关闭，避免两个弹窗挤在同一帧。
   */
  onManualFillFromEstimate() {
    const that = this
    this.setData({
      ftpEstimateModal: false,
      estimateResult: null,
    })
    setTimeout(function () {
      that._showEditFtpModal()
    }, 0)
  },

  /**
   * Sprint 9 task-6：modal-content 上的 catchtap 占位（防点击穿透到 mask 触发关闭）
   * catchtap="noop" 只需一个空方法即可 / 不做任何事
   */
  noop() {},

  /**
   * Sprint 9 task-8：拉 pending breakthrough / 有则弹窗
   *
   * 调用时机：onShow（每次进 settings 页都拉一次 / 用户处理后不再有 pending 不会再弹）
   *
   * 失败兜底：静默 catch / 不打扰用户（网络抖动 / 后端 5xx 都不显示报错）
   */
  _checkPendingBreakthroughs() {
    const that = this
    api.get('/api/user/me/breakthroughs')
      .then(function (events) {
        if (events && events.length > 0) {
          // 取最新一条（后端 order_by detected_at.desc / 第一条即最新）
          // 防抖逻辑保证大多数情况只会有 1 条 pending
          that.setData({
            breakthroughModal: true,
            breakthroughEvent: events[0],
          })
        }
      })
      .catch(function () {
        // 静默失败：进 settings 不应因 breakthrough 拉取失败弹错误 toast
      })
  },

  /**
   * Sprint 9 task-8：用户点"更新 FTP" → PATCH accepted → 同事务改 user.ftp
   *
   * 乐观更新：本地直接刷 ftp / 关弹窗 / 不等后端响应（提高反应速度）
   * 失败兜底：toast 提示 / 不回滚本地状态（再次 onShow 时会重新拉取真实状态）
   */
  onAcceptBreakthrough() {
    const that = this
    const event = this.data.breakthroughEvent
    if (!event || !event.id) {
      this.setData({ breakthroughModal: false, breakthroughEvent: null })
      return
    }
    api.patch('/api/user/me/breakthroughs/' + event.id, { status: 'accepted' })
      .then(function () {
        that.setData({
          breakthroughModal: false,
          breakthroughEvent: null,
          ftp: event.suggested_ftp,           // 同步本地 ftp 显示
        })
        wx.showToast({
          title: 'FTP 已更新到 ' + event.suggested_ftp + ' W',
          icon: 'success',
          duration: 2000,
        })
      })
      .catch(function (err) {
        wx.showToast({
          title: (err && err.message) || '更新失败 / 请重试',
          icon: 'none',
        })
      })
  },

  /**
   * Sprint 9 task-8：用户点"暂不更新" → PATCH rejected → 不动 user.ftp
   *
   * 关弹窗即可 / 不需要 toast（用户主动忽略 / 静默处理）
   * fire-and-forget 调 PATCH（不阻塞 UI 关闭）
   */
  onRejectBreakthrough() {
    const event = this.data.breakthroughEvent
    if (event && event.id) {
      api.patch('/api/user/me/breakthroughs/' + event.id, { status: 'rejected' })
        .catch(function () {
          // 静默：用户已经"暂不"了 / 网络失败重要性低 / 下次 onShow 会再拉
        })
    }
    this.setData({ breakthroughModal: false, breakthroughEvent: null })
  },

  /**
   * 关弹窗 / 不调 PATCH（task-8 quality reviewer Minor 修 / 防误触 mask 永久 reject）
   * 用户下次 onShow 仍能弹（pending 还在 / 7 天后才 expired）
   */
  onCloseBreakthrough() {
    this.setData({ breakthroughModal: false, breakthroughEvent: null })
  },

  /**
   * 解绑 Strava——强制二次确认（红线）
   *
   * 后端契约：POST /api/strava/unbind → 204 No Content（同事务清 4 字段 + active import → paused）
   * 历史 activities 保留 / 不会被删
   */
  onUnbindStrava() {
    const that = this
    wx.showModal({
      title: '解绑 Strava',
      content: '解绑后历史活动保留，但不再自动同步新活动。如需重新同步，可再次绑定。',
      confirmText: '解绑',
      confirmColor: '#e64340',           // system red / 提示危险操作
      cancelText: '取消',
      success: function (res) {
        if (!res.confirm) return          // 用户点取消 / 不执行
        api.post('/api/strava/unbind', {})
          .then(function () {
            that.setData({ stravaBound: false })
            wx.showToast({ title: '已解绑', icon: 'success' })
          })
          .catch(function (err) {
            wx.showToast({
              title: (err && err.message) || '解绑失败，请重试',
              icon: 'none',
            })
          })
      },
    })
  },

  /**
   * 绑定 Strava——Sprint 6 task-4 三次 hotfix / Tim 2026-05-16 真用拍
   *
   * 旧流程：复制 URL → 切微信传输助手 → 粘贴 → 浏览器打开（用户嫌麻烦）
   * 新流程：拿 authorize_url → 跳本地 web-view 页直接打开 Strava 授权
   *        用户在小程序内授权完 → 后端 callback 返成功 HTML → 用户左上返回 settings
   *        settings.onShow 自动拉新 bound 状态
   *
   * 前置：小程序公众平台业务域名加 https://www.strava.com + https://114.132.190.245
   *      开发版可工具勾选"不校验合法域名"临时跳过
   */
  onBindStrava() {
    wx.showLoading({ title: '准备授权链接…' })
    api.get('/api/strava/authorize')
      .then((data) => {
        wx.hideLoading()
        const url = data && data.authorize_url
        if (!url) {
          wx.showToast({ title: '后端未返链接', icon: 'none' })
          return
        }
        // 跳 web-view 页 / 用户在小程序内完成 Strava OAuth
        wx.navigateTo({
          url: '/pages/strava-auth/strava-auth?url=' + encodeURIComponent(url),
          fail: (err) => {
            console.error('[settings] navigate strava-auth failed', err)
            // 兜底：navigate 失败仍走旧复制流程
            wx.setClipboardData({
              data: url,
              success: () => {
                wx.showModal({
                  title: '请复制链接到浏览器',
                  content: '链接已复制 / 跳转 web-view 失败 / 请手动粘贴打开授权',
                  showCancel: false,
                })
              },
            })
          },
        })
      })
      .catch(function (err) {
        wx.hideLoading()
        if (err && err.code === 401) return
        wx.showToast({
          title: (err && err.message) || '获取授权链接失败',
          icon: 'none',
        })
      })
  },

  /**
   * 退出登录——强制二次确认（红线）
   *
   * 流程：
   *   1. wx.showModal confirm（confirmColor 红色 / 提示后果）
   *   2. 用户确认 → app.logout()（清 token / userId / userInfo）
   *   3. wx.redirectTo 跳回 profile 页（"我的"页未登录态显示"微信一键登录"）
   *
   * 注意：用 redirectTo 不用 navigateTo / switchTab：
   *   - settings 不在 tabBar 里 / navigateBack 不合适（栈里上一页就是 profile）
   *   - redirectTo 关闭当前页 + 跳新页 / 防止用户回退按钮回到已退出状态的 settings
   */
  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需要重新登录才能查看个人数据。',
      confirmText: '退出',
      confirmColor: '#e64340',
      cancelText: '取消',
      success: function (res) {
        if (!res.confirm) return
        if (app && typeof app.logout === 'function') {
          app.logout()                    // 清 globalData.token / userId / userInfo + storage
        } else {
          // 兜底：app.logout 不存在时手动清（防 app.js 未来重构丢失方法）
          wx.removeStorageSync('token')
          wx.removeStorageSync('userId')
          if (app) {
            app.globalData.token = null
            app.globalData.userId = 0
            app.globalData.userInfo = null
          }
        }
        wx.redirectTo({ url: '/pages/profile/profile' })
      },
    })
  },
})
