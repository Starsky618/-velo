/**
 * 设置页 — 用户的"控制台"（Sprint 6 task-5 大幅扩写）
 *
 * 干啥用：
 *   把用户每天不点 / 但关键时刻一定要能点到的事集中管理：
 *   1. 改 FTP（账号资料 / 后续可扩 weight / 车辆等）
 *   2. 退出登录 / 注销账号（清 token 或彻底删除个人数据）
 *
 * 类比：
 *   手机系统设置——平时不进，要换号/退账/改重要参数时第一时间能找到入口。
 *
 * 数据流：
 *   - onShow：拉 GET /api/user/profile（FTP / 体重 / 车型 / 设置项）
 *   - 改 FTP：wx.showModal editable → PUT /api/user/profile { ftp }
 *   - 退出：wx.showModal confirm → app.logout() + wx.reLaunch /profile（清页面栈重建，profile 必重判登录态显示一键登录）
 *
 * 红线（v0.2/v0.3 task 卡 / 永久规则）：
 *   - 退出 / 注销**强制二次确认**（wx.showModal confirm）
 *   - FTP 范围 50-500 前后双重校验（前端拒收 + 后端 422）
 *   - "-" 占位符永久规则：FTP 未设时显示 "未设置"（不是 "-"）
 *
 * 注意事项：
 *   - 进入设置页前已要求登录态（"我的"页设置 icon 仅登录后显示 / task-4）
 *     兜底仍判 app.globalData.token —— 防 deep link 或缓存异常情况
 *   - 二次确认按钮颜色：confirmColor #e64340 (system red) 高对比 / 防误点
 *   - Strava 提审前暂时隐藏，避免 web-view 业务域名未配置导致审核员点进失败
 */

const api = require('../../utils/api')
const app = getApp()

// 车型选项（后端 BikeType 枚举 road/gravel/mtb，传别的 422）
const BIKE_TYPES = [
  { value: 'road', label: '公路车' },
  { value: 'gravel', label: '砾石车' },
  { value: 'mtb', label: '山地车' },
]

Page({
  data: {
    // —— 个人资料组（2026-06-12 重构新增）——
    bio: '',                       // 骑行宣言（≤30 字单行 / 编辑入口从 profile 页移来）
    weeklyGoal: null,              // 每周目标（km / 10-2000）
    bikeType: null,                // 车型枚举值 road/gravel/mtb
    bikeTypeLabel: '',             // 车型中文展示
    bikeTypeIndex: 0,              // picker 当前下标
    bikeTypeOptions: BIKE_TYPES,
    // —— 通用组 ——
    cacheSizeText: '',             // 本地缓存占用展示（如 "1.2 MB"）
    versionText: '',               // 小程序版本（线上版本号 / 开发版显示环境名）
    ftp: null,
    weight: null,                  // Sprint 9 task-6：体重（kg）/ 可选 / 算 W/kg 用
    birthYear: null,               // Sprint 10：出生年份 / 后端不存 age / 用来兜底估算最大心率
    displayAge: null,              // Sprint 10：前端展示年龄 / 不回写后端
    birthYearOptions: [],          // 出生年份滚轮选项：今年 → 1900
    birthYearIndex: 0,             // 当前出生年份在滚轮里的位置
    maxHr: null,                   // Sprint 10：最大心率 / FTP 自动估算的心率门槛
    // Sprint 9 task-6：FTP 估算弹窗状态
    ftpEstimateModal: false,       // 弹窗显隐
    estimateResult: null,          // EstimationResultResponse / { ftp, confidence, method, r2 }
    // Sprint 9 task-8：FTP Breakthrough 弹窗状态（worker 自动检测出的突破事件）
    breakthroughModal: false,      // 弹窗显隐
    breakthroughEvent: null,       // BreakthroughEventResponse / { id, old_ftp, suggested_ftp, ... }
  },

  /**
   * onShow 而不是 onLoad：从资料编辑、系统弹窗等子流程返回时也能拉到最新状态。
   */
  onShow() {
    // 兜底：未登录直接跳回 profile（理论上"我的"页设置入口已挡 / 双保险）
    if (!app.globalData.token) {
      wx.reLaunch({ url: '/pages/profile/profile' })
      return
    }
    this._ensureBirthYearOptions()
    this._fetchProfile()
    this._initVersion()
    // Sprint 9 task-8：每次进 settings 时拉 pending breakthrough / 有则弹窗
    this._checkPendingBreakthroughs()
  },

  /**
   * 版本号展示：wx.getAccountInfoSync 拿线上版本（开发/体验版 version 为空，
   * 显示环境名兜底）。小程序自动热更新，没有"检查更新"这回事。
   */
  _initVersion() {
    if (this.data.versionText) return
    try {
      const info = wx.getAccountInfoSync()
      const mp = (info && info.miniProgram) || {}
      const envName = { develop: '开发版', trial: '体验版', release: '' }[mp.envVersion] || ''
      const text = mp.version ? 'v' + mp.version + (envName ? ' ' + envName : '') : envName
      this.setData({ versionText: text })
    } catch (e) {
      // 拿不到就不显示版本（行右侧留空，不显示占位）
    }
  },

  /**
   * 骑行宣言编辑（2026-06-12 从 profile 页移来——我的页只展示，设置页才能改）。
   * 走 PATCH /api/user/me（bio 专属端点，≤30 字单行，后端 422 兜底）。
   */
  onEditBio() {
    const that = this
    wx.showModal({
      title: '编辑骑行宣言',
      editable: true,
      placeholderText: '不超过 30 字',
      content: this.data.bio || '',
      success: (res) => {
        if (!res.confirm) return
        const newBio = (res.content || '').trim()
        if (newBio.length > 30) {
          wx.showToast({ title: '不能超过 30 字', icon: 'none' })
          return
        }
        api.patch('/api/user/me', { bio: newBio })
          .then(() => {
            that.setData({ bio: newBio })
            wx.showToast({ title: '已保存', icon: 'success' })
          })
          .catch((err) => {
            wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
          })
      },
    })
  },

  /**
   * 每周目标编辑（km / 10-2000，影响"我的"页本周进度条）。
   * 走 PUT /api/user/profile（主资料端点，后端 schema ge=10 le=2000 兜底）。
   */
  onEditWeeklyGoal() {
    const that = this
    wx.showModal({
      title: '每周目标',
      editable: true,
      placeholderText: '每周想骑多少公里（10-2000）',
      content: this.data.weeklyGoal ? String(this.data.weeklyGoal) : '',
      success: (res) => {
        if (!res.confirm) return
        const raw = (res.content || '').trim()
        if (!raw) return
        const goal = parseFloat(raw)
        if (isNaN(goal) || goal < 10 || goal > 2000) {
          wx.showToast({ title: '范围 10-2000 km', icon: 'none' })
          return
        }
        api.put('/api/user/profile', { weekly_goal: goal })
          .then(() => {
            that.setData({ weeklyGoal: goal })
            wx.showToast({ title: '目标已更新', icon: 'success' })
          })
          .catch((err) => {
            wx.showToast({ title: (err && err.message) || '更新失败', icon: 'none' })
          })
      },
    })
  },

  /**
   * 车型滚轮选择（road/gravel/mtb，后端枚举白名单 422 兜底）
   */
  onBikeTypeChange(e) {
    const that = this
    const index = Number(e.detail.value)
    const option = BIKE_TYPES[index]
    if (!option) return
    api.put('/api/user/profile', { bike_type: option.value })
      .then(() => {
        that.setData({
          bikeType: option.value,
          bikeTypeLabel: option.label,
          bikeTypeIndex: index,
        })
        wx.showToast({ title: '车型已更新', icon: 'success' })
      })
      .catch((err) => {
        wx.showToast({ title: (err && err.message) || '更新失败', icon: 'none' })
      })
  },

  /**
   * 关于 VELO：版本信息弹窗（小程序热更新，无"检查更新"概念）
   */
  onAbout() {
    wx.showModal({
      title: 'VELO',
      content: '公路骑行 · 成绩与约骑\n' + (this.data.versionText || '开发版'),
      showCancel: false,
      confirmText: '好',
    })
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
        // 车型：后端枚举值映射中文展示 + picker 下标
        let bikeTypeLabel = ''
        let bikeTypeIndex = 0
        BIKE_TYPES.forEach((opt, i) => {
          if (opt.value === p.bike_type) {
            bikeTypeLabel = opt.label
            bikeTypeIndex = i
          }
        })
        this.setData({
          ftp: p.ftp != null ? p.ftp : null,
          weight: p.weight != null ? p.weight : null,
          birthYear: birthYear,
          displayAge: this._ageFromBirthYear(birthYear),
          birthYearIndex: birthYearIndex,
          maxHr: p.max_hr != null ? p.max_hr : null,
          bio: p.bio || '',
          weeklyGoal: p.weekly_goal != null ? p.weekly_goal : null,
          bikeType: p.bike_type || null,
          bikeTypeLabel: bikeTypeLabel,
          bikeTypeIndex: bikeTypeIndex,
        })
      })
      .catch((err) => {
        if (err && err.code === 401) {
          // token 已被 api.js 清掉 / 跳回 profile
          wx.reLaunch({ url: '/pages/profile/profile' })
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
   * 退出登录——强制二次确认（红线）
   *
   * 流程：
   *   1. wx.showModal confirm（confirmColor 红色 / 提示后果）
   *   2. 用户确认 → app.logout()（清 token / userId / userInfo）
   *   3. wx.reLaunch 跳回 profile 页（清栈重建，profile onShow 必重判登录态）
   *
   * 注意：必须用 switchTab 或 reLaunch，不能用 navigateTo / redirectTo：
   *   - profile 在 tabBar 里，微信硬规则——navigateTo/redirectTo 跳 tabBar 页直接 fail、
   *     页面纹丝不动（2026-06-13 全模块走查实证）；switchTab/reLaunch 跳 tabBar 都合法
   *   - 退出登录这里选 reLaunch（不是 switchTab）：清掉整个页面栈重建，回退按钮回不到
   *     已退出的 settings，且 profile 全新初始化必重判登录态显示"微信登录"（2026-06-13
   *     实证：switchTab 回 profile 时 onShow 刷登录态偶尔不生效、停在旧态没登录按钮）
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
        wx.reLaunch({ url: '/pages/profile/profile' })
      },
    })
  },

  /**
   * 注销账号——彻底删除全部个人数据（不可逆 / 比退出登录更严重 / 两步确认）。
   *
   * 流程：
   *   1. 第一道 modal：警告删光所有数据 + 不可恢复 → 用户点"继续"
   *   2. 第二道 modal：最终确认"无法撤销" → 用户点"确认注销"（多一道闸防手滑误触）
   *   3. 调 api.deleteAccount()（DELETE /api/user/me）→ 成功后 app.logout() 清 token + 跳回 profile
   *   4. 失败 toast 提示、不清本地状态（账号还在 / 可重试）
   */
  onDeleteAccount() {
    wx.showModal({
      title: '注销账号',
      content: '注销会彻底删除你的全部数据（骑行记录、赛段成绩、功率与训练数据），且无法恢复。确定继续吗？',
      confirmText: '继续',
      confirmColor: '#e64340',
      cancelText: '取消',
      success: function (res) {
        if (!res.confirm) return
        wx.showModal({
          title: '最后确认',
          content: '确认彻底注销账号？此操作无法撤销。',
          confirmText: '确认注销',
          confirmColor: '#e64340',
          cancelText: '再想想',
          success: function (res2) {
            if (!res2.confirm) return
            wx.showLoading({ title: '注销中', mask: true })
            api.deleteAccount()
              .then(function () {
                wx.hideLoading()
                // 复用退出登录的清理（清 token / userId / userInfo + storage），兜底手动清防 app.logout 缺失
                if (app && typeof app.logout === 'function') {
                  app.logout()
                } else {
                  wx.removeStorageSync('token')
                  wx.removeStorageSync('userId')
                  if (app) {
                    app.globalData.token = null
                    app.globalData.userId = 0
                    app.globalData.userInfo = null
                  }
                }
                wx.showToast({ title: '账号已注销', icon: 'success' })
                // 稍等让 toast 可见，再跳回 profile（未登录态显示"微信一键登录"）
                setTimeout(function () {
                  wx.reLaunch({ url: '/pages/profile/profile' })
                }, 800)
              })
              .catch(function (err) {
                wx.hideLoading()
                wx.showToast({ title: (err && err.message) || '注销失败，请重试', icon: 'none' })
              })
          },
        })
      },
    })
  },
})
