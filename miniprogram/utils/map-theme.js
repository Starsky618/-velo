/**
 * 小程序地图配色 — 给所有"画路线"的地方统一一支橙色笔。
 *
 * 这个文件像一盒彩铅：路线该用什么颜色、多粗的线、什么描边，都从这里拿，
 * 业务页面不许自己配色（改主色只改这一个文件）。
 *
 * ⚠ 历史教训（2026-06-12 地图事故，改这个文件前必读）：
 * 这里曾经放过腾讯个性化底图的 subkey + layerStyle，想给所有 <map> 换浅色纸面皮肤。
 * 微信官方文档：自 2023-06-29 起，小程序个性化地图是"先购买再使用"的付费能力，
 * 入口在微信公众平台-付费管理——只在腾讯位置服务控制台建 key/调样式/授权 AppID 是不够的。
 * velo 没有购买该能力 → subkey 一挂到 <map> 上，真机鉴权必失败、地图直接卡死，
 * 改任何代码都救不回来（codex 多轮代码层修复全部无效，根因在商务层不在代码层）。
 *
 * 现行架构（替代方案，免费且已验证）：
 * 1. 装饰性展示（路线缩略图 / 热力图卡）→ utils/route-thumb.js canvas 自绘纸面 + 橙色轨迹；
 * 2. 交互性地图（route-map 全屏查看）→ 不带 subkey 的默认底图（免费）；
 * 3. 全工程任何 <map> 禁止再传 subkey / layer-style（有静态测试守卫这条红线）。
 * 未来真要复活纸面底图：先在微信公众平台-付费管理购买个性化地图，再从腾讯控制台
 * weilu-mini key 取回 subkey 填上——顺序不能反。
 */

const PAPER_MAP_CONFIG = {
  // 路线主色 = 系统橙（MASTER v0.4 唯一强调色）；旧 #F04452 属已废弃四色系
  routeColor: '#FF9500',
  routeBorderColor: '#FFFFFF',
}

// 把一串 GCJ-02 点变成 <map> polyline 数组——route-map 全屏页画橙色路线用。
// 展示型缩略图不走这里（那是 route-thumb.js canvas 的事），所以全工程只有"真地图"页消费它。
function buildRoutePreviewPolylines(points) {
  if (!Array.isArray(points) || points.length < 2) return []
  return [{
    points: points,
    color: PAPER_MAP_CONFIG.routeColor,
    width: 8,
    borderColor: PAPER_MAP_CONFIG.routeBorderColor,
    borderWidth: 3,
    arrowLine: false,
    level: 'abovelabels',
  }]
}

module.exports = {
  PAPER_MAP_CONFIG,
  buildRoutePreviewPolylines,
}
