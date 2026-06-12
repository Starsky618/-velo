/**
 * 小程序地图外衣 — 给所有页面内地图统一一张很浅的纸面底图。
 *
 * 这个文件像一盒彩铅：地图本身只负责把路、点、城市画出来；
 * 哪些颜色应该淡下去，哪些路线应该跳出来，都从这里拿。
 *
 * 操作注意事项：
 * 1. 这里只能放前端可公开的 Tencent 地图 subkey 和 layer-style。
 * 2. 不能放服务端 SK；服务端 SK 像后厨钥匙，只能留在后端环境变量里。
 * 3. 如果腾讯控制台换了浅色样式，只改 PAPER_MAP_CONFIG，不要逐页改。
 */

const PAPER_MAP_CONFIG = {
  // 腾讯控制台里的 weilu-mini（小程序浅色底图）key：客户端公开类 subkey，安全靠 APPID 白名单，
  // 不靠保密；不要填 weilu-dev（路线规划）key。个性化样式已在腾讯控制台调好：高速等道路调浅。
  subkey: 'GIHBZ-V6YWL-5TYPD-EXDCJ-6WCUT-TFBLI',
  // 样式编号：取腾讯控制台"个性化地图-样式应用"里已绑定样式的编号。
  // 这里绑定的是“我的自定义样式1”（控制台值 20568），不是腾讯内置模板 1。
  layerStyle: 20568,
  // 高速、主干路、水系、绿地这些底图颜色必须在腾讯个性化地图后台调浅。
  // 小程序代码只保存公开 subkey 和样式编号，业务页面不能自己调底图颜色。
  // 路线主色 = 系统橙（MASTER v0.4 唯一强调色）；旧 #F04452 属已废弃四色系
  routeColor: '#FF9500',
  routeBorderColor: '#FFFFFF',
  heatColor: '#FFB020CC',
}

function normalizePaperMapConfig(config) {
  var source = config || PAPER_MAP_CONFIG
  var subkey = String(source.subkey || '').trim()
  var layerStyle = Number(source.layerStyle)
  if (!Number.isFinite(layerStyle)) layerStyle = 1
  return {
    subkey: subkey,
    layerStyle: layerStyle,
    hasCustomStyle: Boolean(subkey),
  }
}

function getPaperMapData(config) {
  var normalized = normalizePaperMapConfig(config)
  return {
    paperMapSubkey: normalized.subkey,
    paperMapLayerStyle: normalized.layerStyle,
    paperMapHasCustomStyle: normalized.hasCustomStyle,
  }
}

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

function buildHeatmapPolyline(points, dottedLine) {
  return {
    points: points,
    color: PAPER_MAP_CONFIG.heatColor,
    width: 4,
    arrowLine: false,
    dottedLine: Boolean(dottedLine),
  }
}

module.exports = {
  PAPER_MAP_CONFIG,
  normalizePaperMapConfig,
  getPaperMapData,
  buildRoutePreviewPolylines,
  buildHeatmapPolyline,
}
