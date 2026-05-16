// Strava 授权 web-view 页 — Sprint 6 task-4 三次 hotfix / Tim 2026-05-16 真用拍
//
// 设计思路：
//   settings.onBindStrava 调 GET /api/strava/authorize 拿 authorize_url →
//   wx.navigateTo 跳本页 query.url=encodeURIComponent(authorize_url) →
//   本页 onLoad 解码 url → setData authorizeUrl → web-view 自动加载 Strava 授权页 →
//   用户授权完 Strava 重定向到后端 /api/strava/callback →
//   后端处理 + 返成功 HTML → 用户看到成功页点左上返回 → settings.onShow 拉新 bound 状态
//
// 替代旧流程：复制 URL → 切微信传输助手 → 粘贴 → 浏览器打开（用户嫌麻烦）
//
// 限制：业务域名（strava.com + 后端 IP）需小程序公众平台后台配置 / 开发版可工具勾选跳过
Page({
  data: {
    authorizeUrl: '',
  },

  onLoad(query) {
    const url = query && query.url ? decodeURIComponent(query.url) : '';
    if (!url) {
      wx.showToast({ title: '授权链接缺失', icon: 'none' });
      setTimeout(() => wx.navigateBack(), 1500);
      return;
    }
    this.setData({ authorizeUrl: url });
  },
});
