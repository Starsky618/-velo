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
  // 2026-06-11 暂时清空：填入企业 key 后真机弹"鉴权失败,请传入正确的key"——该 key 在腾讯
  // 位置服务控制台尚未给小程序授权（启用"微信小程序"产品 + 绑定小程序 AppID）。空 subkey 时
  // 所有地图回落默认底图、无弹窗。控制台配好后把 key 填回（值在 git 历史 999ed55），
  // 浅色样式即对全部地图生效。
  subkey: '',
  // 样式编号：取控制台"个性化地图-样式管理"里绑定的编号，先按 1；真机若底图仍是默认色，
  // 说明编号不是 1，查控制台后只改这一个数字。
  layerStyle: 1,
  // 高速、主干路、水系、绿地这些底图颜色必须在腾讯个性化地图后台调浅。
  // 小程序代码只保存公开 subkey 和样式编号，业务页面不能自己调底图颜色。
  routeColor: '#F04452',
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
