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
    cityLabel: '',  // 6 城英文 code → 中文 label / hero 区显示用
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
    return api.get('/api/user/profile')
      .then((res) => {
        const profile = res || null;
        // 计算 cityLabel（英文 code → 中文 label / 让 hero 区直接显示"北京"而不是"beijing"）
        // 6 城映射与后端 app/user/cities.py CITY_LABELS 保持一致 / 前端独立维护一份小映射
        // 避免每次拉 city-medals 才拿到 label（task-4 后已不调 city-medals）
        const CITY_LABEL_MAP = {
          beijing: '北京', shanghai: '上海', hangzhou: '杭州',
          shenzhen: '深圳', chengdu: '成都', taiyuan: '太原',
        };
        const cityLabel = (profile && profile.city) ? (CITY_LABEL_MAP[profile.city] || '') : '';
        this.setData({ profile, cityLabel });
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

  // 编辑主城（Tim 2026-05-16 真用拍：之前 city 默认值无法改 / 加 picker 入口）
  // wx.showActionSheet 6 城 + "清空"选项 / 选完调 PATCH /api/user/me
  onEditCity() {
    const cities = [
      { code: 'beijing', label: '北京' },
      { code: 'shanghai', label: '上海' },
      { code: 'hangzhou', label: '杭州' },
      { code: 'shenzhen', label: '深圳' },
      { code: 'chengdu', label: '成都' },
      { code: 'taiyuan', label: '太原' },
    ];
    wx.showActionSheet({
      itemList: cities.map((c) => c.label).concat(['清空主城']),
      success: (res) => {
        const idx = res.tapIndex;
        // 最后一项是"清空主城" → body.city = null
        const cityCode = idx < cities.length ? cities[idx].code : null;
        api.patch('/api/user/me', { city: cityCode })
          .then(() => {
            // 乐观更新 UI
            const profile = Object.assign({}, this.data.profile || {}, { city: cityCode });
            const cityLabel = cityCode ? cities.find((c) => c.code === cityCode).label : '';
            this.setData({ profile, cityLabel });
            wx.showToast({ title: '主城已更新', icon: 'success' });
          })
          .catch((err) => {
            console.error('[profile] update city failed', err);
            wx.showToast({ title: '更新失败', icon: 'none' });
          });
      },
    });
  },

  // 跳到设置页（bio / 隐私 / Strava 绑定 / 退出登录）
  onTapSettings() {
    wx.navigateTo({ url: '/pages/settings/settings' });
  },

  // 未登录态点击登录（Tim 2026-05-16 二次真用：卡在"登录中..."loading 不消失）
  // 根因：原写法等 fetchAllData 全 settle 才 hideLoading / fetchAllData 内含 setData isLoggedIn=true
  // 触发 wx:if 块渲染 + <heatmap-card /> 组件自 fetch / 渲染链路可能延迟 hideLoading 到达
  //
  // 修法：先 hideLoading + toast 给用户即时反馈 / 再后台跑 fetchAllData（不阻塞 loading）
  // 即使 fetchAllData 失败 toast 也已经"登录成功" / 数据稍后刷出来 / 体验更鲁棒
  onLogin() {
    if (this.data.loginLoading) return; // 防重复点击
    this.setData({ loginLoading: true });
    wx.showLoading({ title: '登录中...', mask: true });
    app.login()
      .then(() => {
        // 第一时间结束 loading + 切登录态 / 不等数据
        wx.hideLoading();
        this.setData({ isLoggedIn: true, loginLoading: false });
        wx.showToast({ title: '登录成功', icon: 'success' });
        // 数据后台拉 / 失败也不影响登录态展示
        this.fetchAllData(true);
      })
      .catch((err) => {
        wx.hideLoading();
        this.setData({ loginLoading: false });
        wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none' });
      });
  },
});
