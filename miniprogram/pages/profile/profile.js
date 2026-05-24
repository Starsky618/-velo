// profile 页 —— 骑手身份名片
//
// 设计思路：
//   - onShow 并发拉 4 个接口（profile / stats / heatmap / city-medals），
//     不串行等待 / 否则首屏白屏时间 = 4 个接口耗时之和
//   - 活动列表独立拉取 + 分页（不阻塞前 4 个 / 走 /api/activities）
//   - 编辑入口拆 3 个：bio（PATCH /api/user/me）/ nickname（PUT /api/user/profile）/ avatar
//   - 未登录直接跳过数据拉取 / 显示登录提示
//
// 模块边界：
//   - 本页只读 + 编辑用户自己的资料
//   - 看他人 profile 走单独路由（不在 task-4 范围）
//   - 编辑用 wx.showModal 不弹页面（简单字段不开新页）
//
// endpoint 路径（全部 /api 前缀 / grep 实证 app/user/router.py + app/strava/router.py）：
//   - GET  /api/user/profile          → UserProfile（self / 含 bio / badges[]）
//   - PUT  /api/user/profile          → 改主资料（nickname / avatar_url / ftp / ...）
//   - PATCH /api/user/me              → 改 settings 类（bio / city）
//   - GET  /api/user/stats?period=week → StatsResponse
//   - GET  /api/user/me/heatmap        → HeatmapResponse
//   - GET  /api/user/me/city-medals    → CityMedalsResponse
//   - GET  /api/activities?page=N&page_size=N → ActivityListResponse
//
// 字段口径（与 wxml + ride-card 组件契约）：
//   - StatsResponse.distance 是公里（service 已转）/ rides / elevation_gain 米 int /
//     duration 秒 / goal_percent —— **不返** avg_power_w（tech-debt P3 / self 视图不渲染）
//   - ActivitySummary.distance 是公里（service 已转）/ duration 秒 / elevation_gain 米

const api = require('../../utils/api');
// 模块级 app 实例（v5 期老版本有 / 续工 subagent 漏写 → onLogin 调 app.login() ReferenceError
// Tim 2026-05-16 Console 实证：app is not defined at ii.onLogin profile.js:367）
// 这里 getApp() 是安全的：profile.js 是 page 文件 / Page() 注册时 App 已 onLaunch 完成
const app = getApp();

// 判断登录态 —— 与 utils/api.js 同口径（依赖 getApp().globalData.token）
function isLoggedIn() {
  try {
    const app = getApp();
    return !!(app && app.globalData && app.globalData.token);
  } catch (e) {
    return false;
  }
}

// 时间格式化：把 ISO datetime 转 "今天 09:30" / "昨天 18:20" / "MM-DD HH:mm"
// 类比 home.js fmtDate（同款逻辑 / profile 独立一份避免跨页耦合）
function fmtStartedAt(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const hour = pad(d.getHours());
  const min = pad(d.getMinutes());
  if (d.toDateString() === now.toDateString()) {
    return `今天 ${hour}:${min}`;
  }
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) {
    return `昨天 ${hour}:${min}`;
  }
  // 跨年加年份避免歧义（2023-04-12 和 2026-04-12 看起来一样）
  const month = pad(d.getMonth() + 1);
  const day = pad(d.getDate());
  if (d.getFullYear() !== now.getFullYear()) {
    return `${d.getFullYear()}-${month}-${day} ${hour}:${min}`;
  }
  return `${month}-${day} ${hour}:${min}`;
}

Page({
  data: {
    isLoggedIn: false,
    profile: null,
    // cityLabel 已删（Tim 2026-05-17 user.city 改任意中文 / hero 直接显示 profile.city）
    regionArr: ['', '', ''],  // picker mode="region" 初始值 / 三级 [省 市 区]
    stats: null,
    // heatmap / cityMedals 字段已删（heatmap 改用组件 / 城市勋章砍）

    // 活动列表（分页）
    rides: [],
    ridesPage: 1,
    ridesPageSize: 10,
    hasMoreRides: true,
    ridesLoading: false,
    totalRides: 0,
  },

  onShow() {
    // 切回页面时刷新数据（避免 settings 改完看到旧值）
    this.refreshLoginState();
    if (this.data.isLoggedIn) {
      this.fetchAllData();
    }
  },

  onPullDownRefresh() {
    if (this.data.isLoggedIn) {
      this.fetchAllData(true).finally(() => {
        wx.stopPullDownRefresh();
      });
    } else {
      wx.stopPullDownRefresh();
    }
  },

  refreshLoginState() {
    this.setData({ isLoggedIn: isLoggedIn() });
  },

  // 4 接口并发 + 活动列表独立拉取
  // 返回 Promise 便于 pullDownRefresh 等待
  fetchAllData(reset) {
    if (reset) {
      this.setData({ rides: [], ridesPage: 1, hasMoreRides: true });
    }

    // 并发拉 2 个 —— Promise.allSettled 让单个失败不影响其它块
    // Tim 2026-05-16 真用拍：
    //   - 热图改用 heatmap-card 组件 / 组件自己 fetch / 不再走 fetchHeatmap
    //   - 城市勋章砍掉 / 不再走 fetchCityMedals
    const tasks = [
      this.fetchProfile(),
      this.fetchStats(),
    ];

    // 活动列表独立 / 不参与 allSettled（避免分页失败影响顶部 2 块）
    this.fetchRides(true);

    return Promise.allSettled(tasks);
  },

  fetchProfile() {
    // GET /api/user/profile → UserProfile（含 bio / badges[]）
    // badges 字段保留 / 但 wxml 不渲染（Tim 2026-05-16 真用拍砍）
    // city 改任意中文（Tim 2026-05-17 picker mode="region"）/ 不再做 6 城 code→label 映射
    return api.get('/api/user/profile')
      .then((res) => {
        this.setData({ profile: res || null });
      })
      .catch((err) => {
        console.error('[profile] fetchProfile failed', err);
      });
  },

  fetchStats() {
    // GET /api/user/stats?period=week → StatsResponse
    // 注意：self stats 不返 avg_power_w / 见 tech-debt P3
    return api.get('/api/user/stats', { period: 'week' })
      .then((res) => {
        this.setData({ stats: res || null });
      })
      .catch((err) => {
        console.error('[profile] fetchStats failed', err);
      });
  },

  // Tim 2026-05-16 真用拍：
  //   - fetchHeatmap 删除 / 改用 <heatmap-card /> 组件自己 fetch + <map> 渲染
  //   - fetchCityMedals 删除 / 城市勋章前端砍 / 后端 endpoint 保留以备恢复

  // 活动列表分页
  // GET /api/activities?page=N&page_size=N → ActivityListResponse
  fetchRides(reset) {
    if (this.data.ridesLoading) return;
    const page = reset ? 1 : this.data.ridesPage;
    this.setData({ ridesLoading: true });

    return api.get('/api/activities', {
      page,
      page_size: this.data.ridesPageSize,
    })
      .then((res) => {
        // 后端真返字段 = items[] / total / page / page_size
        const rawItems = (res && res.items) || [];
        const total = (res && res.total) || 0;
        // 补充 startedAtDisplay 字段供 ride-card subtitle 槽位用
        // 其他字段（id / title / distance / duration / elevation_gain / avg_speed）直接透传
        //
        // 业务时间用 started_at 不用 created_at（memory feedback_time_field_use_business_not_db_writetime.md
        // Tim 2026-05-15 拍永久规则 / 踩过 2 次坑）：
        // Strava 批量同步会把所有 effort.created_at squash 成同步那一刻 / 整页活动显示同一时间
        // started_at 为空时返空字符串 / wxml 用 wx:if 整块隐藏 / 不显示错误时间
        const items = rawItems.map((it) => Object.assign({}, it, {
          startedAtDisplay: it.started_at ? fmtStartedAt(it.started_at) : '',
        }));
        const newRides = reset ? items : this.data.rides.concat(items);
        this.setData({
          rides: newRides,
          totalRides: total,
          ridesPage: page + 1,
          hasMoreRides: newRides.length < total,
          ridesLoading: false,
        });
      })
      .catch((err) => {
        console.error('[profile] fetchRides failed', err);
        this.setData({ ridesLoading: false });
      });
  },

  onLoadMoreRides() {
    if (this.data.hasMoreRides && !this.data.ridesLoading) {
      this.fetchRides(false);
    }
  },

  // 点击骑行卡片 → 跳详情
  // ride-card 组件 triggerEvent('tap-ride', { activity_id }) → 这里接 e.detail
  onRideTap(e) {
    const id = e.detail && e.detail.activity_id;
    if (!id) return;
    wx.navigateTo({ url: `/pages/detail/detail?id=${id}` });
  },

  // 编辑 bio —— wx.showModal editable + PATCH /api/user/me
  // PATCH /me 是 settings 类小修（接 city / bio）/ 不与 PUT /profile 主资料字段耦合
  onEditBio() {
    const current = (this.data.profile && this.data.profile.bio) || '';
    wx.showModal({
      title: '编辑骑行宣言',
      editable: true,
      placeholderText: '不超过 30 字',
      content: current,
      success: (res) => {
        if (!res.confirm) return;
        const newBio = (res.content || '').trim();
        if (newBio.length > 30) {
          wx.showToast({ title: '不能超过 30 字', icon: 'none' });
          return;
        }
        api.patch('/api/user/me', { bio: newBio })
          .then(() => {
            wx.showToast({ title: '已保存', icon: 'success' });
            // 乐观更新：本地直接改 / 避免再次拉
            this.setData({
              'profile.bio': newBio,
            });
          })
          .catch((err) => {
            wx.showToast({ title: '保存失败', icon: 'none' });
            console.error('[profile] update bio failed', err);
          });
      },
    });
  },

  // 编辑昵称 —— wx.showModal editable + PUT /api/user/profile
  // PUT /profile 用于改主资料字段（nickname / avatar_url / ftp / weight / bike_type / weekly_goal）
  onEditNickname() {
    const current = (this.data.profile && this.data.profile.nickname) || '';
    wx.showModal({
      title: '编辑昵称',
      editable: true,
      placeholderText: '请输入昵称',
      content: current,
      success: (res) => {
        if (!res.confirm) return;
        const newName = (res.content || '').trim();
        if (!newName) {
          wx.showToast({ title: '昵称不能为空', icon: 'none' });
          return;
        }
        api.put('/api/user/profile', { nickname: newName })
          .then(() => {
            wx.showToast({ title: '已保存', icon: 'success' });
            this.setData({
              'profile.nickname': newName,
            });
          })
          .catch((err) => {
            wx.showToast({ title: '保存失败', icon: 'none' });
            console.error('[profile] update nickname failed', err);
          });
      },
    });
  },

  // 编辑头像 —— Tim 2026-05-16 二次真用拍：退回 wx.chooseMedia 拍照/相册（牺牲微信一键导入）
  // 前一版 <button open-type="chooseAvatar"> 在 hero-top flex 行内拦截 hero-info 区点击事件
  // 导致 city 不可点击 / 退回 image bindtap 模式 / 微信一键导入留 tech-debt 后续找方案
  onEditAvatar() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        const tempFile = res.tempFiles && res.tempFiles[0];
        if (!tempFile) return;
        // 小程序临时文件路径 / 当前直接存为 avatar_url（后端不做上传 OSS / 100 用户量级先这样）
        // 注：tempFilePath 是本地 wxfile:// / 重启 app 可能失效 / 真正持久化需后端上传接口
        api.put('/api/user/profile', { avatar_url: tempFile.tempFilePath })
          .then(() => {
            const profile = Object.assign({}, this.data.profile || {}, {
              avatar_url: tempFile.tempFilePath,
            });
            this.setData({ profile });
            wx.showToast({ title: '头像已更新', icon: 'success' });
          })
          .catch((err) => {
            console.error('[profile] update avatar failed', err);
            wx.showToast({ title: '头像更新失败', icon: 'none' });
          });
      },
    });
  },

  // 家乡 picker 选完触发（Tim 2026-05-17 真用拍：放宽到全国省+市 / 用 picker mode="region"）
  // e.detail.value = [省 市 区] 三级数组 / 我们取省+市拼接 "山西-太原"
  // 直辖市 / 特别行政区时市可能为空 / 兜底用省名
  onRegionChange(e) {
    const region = e && e.detail && e.detail.value;
    if (!region || region.length < 2) {
      console.warn('[city] onRegionChange got empty region', region);
      return;
    }
    const [province, city] = region;
    // 拼接规则：有市拼 "省-市"（如"山西-太原"）/ 没市只用省（如"北京"直辖市）
    // 注意：picker 返"北京市"含"市"后缀 / 去掉让标签更简短
    const stripSuffix = (s) => (s || '').replace(/市$|省$|自治区$|特别行政区$/, '');
    const provinceShort = stripSuffix(province);
    const cityShort = stripSuffix(city);
    const cityLabel = cityShort && cityShort !== provinceShort
      ? `${provinceShort}-${cityShort}`
      : provinceShort;

    console.log('[city] picker selected:', region, '→ label:', cityLabel);
    if (cityLabel.length > 32) {
      wx.showToast({ title: '家乡标签太长', icon: 'none' });
      return;
    }

    api.patch('/api/user/me', { city: cityLabel })
      .then(() => {
        console.log('[city] PATCH /api/user/me success / city=', cityLabel);
        const profile = Object.assign({}, this.data.profile || {}, { city: cityLabel });
        this.setData({ profile, regionArr: region });
        wx.showToast({ title: '家乡已更新', icon: 'success' });
      })
      .catch((err) => {
        console.error('[city] PATCH /api/user/me failed', err);
        wx.showToast({ title: '更新失败 / 看 console', icon: 'none', duration: 3000 });
      });
  },

  // 跳到设置页（bio / 隐私 / Strava 绑定 / 退出登录）
  onTapSettings() {
    wx.navigateTo({ url: '/pages/settings/settings' });
  },

  onTapHonor() {
    wx.navigateTo({ url: '/pages/honor/honor' });
  },

  onTapTrainingAnalysis() {
    wx.navigateTo({ url: '/pages/training-calendar/training-calendar' });
  },

  // 未登录态点击登录（Tim 2026-05-16 三次真用：仍卡 loading / app.login 既不 resolve 也不 reject）
  // 修法：加 5s 兜底 timeout + 全程 console.log / 下次卡能从 console 看到卡哪步 + toast 必出错
  onLogin() {
    if (this.data.loginLoading) return; // 防重复点击
    this.setData({ loginLoading: true });
    wx.showLoading({ title: '登录中...', mask: true });

    console.log('[login] step 1: showLoading + app.login() called');

    // 兜底 5s timeout：即使 promise 永远 pending 也强制结束 loading + toast
    const timeoutHide = setTimeout(() => {
      console.error('[login] TIMEOUT after 5s / app.login never resolved or rejected');
      wx.hideLoading();
      this.setData({ loginLoading: false });
      wx.showToast({ title: '登录超时 / 检查网络或服务器', icon: 'none', duration: 3000 });
    }, 5000);

    app.login()
      .then((data) => {
        console.log('[login] step 2: app.login resolved', data);
        clearTimeout(timeoutHide);
        wx.hideLoading();
        this.setData({ isLoggedIn: true, loginLoading: false });
        wx.showToast({ title: '登录成功', icon: 'success' });
        // 数据后台拉 / 失败也不影响登录态展示
        this.fetchAllData(true);
      })
      .catch((err) => {
        console.error('[login] step 2 FAIL: app.login rejected', err);
        clearTimeout(timeoutHide);
        wx.hideLoading();
        this.setData({ loginLoading: false });
        wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none', duration: 3000 });
      });
  },
});
