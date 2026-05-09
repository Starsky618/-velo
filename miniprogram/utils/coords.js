/**
 * 坐标系转换工具 — WGS-84 → GCJ-02
 *
 * ─── 这个文件是干什么的 ──────────────────────────
 * 中国大陆 GPS 设备（手机 / 码表）记录的是 WGS-84 国际标准坐标，
 * 但腾讯、高德、百度地图引擎在中国大陆境内必须用 GCJ-02"加密坐标"才能正确显示。
 * 直接把 WGS-84 经纬度丢给小程序 <map> 组件，会偏移 100~700 米
 * （表现：用户的骑行轨迹明明走的大马路，地图上却画到了小区里）。
 *
 * 类比：就像两套门牌号系统——同一栋楼，国际地图叫"幸福街 12 号"，
 * 中国地图叫"和谐路 8 号"。把国际门牌念给中国出租车司机听，
 * 他会把你拉到错误的地方。这个工具就是帮你换号牌的"翻译官"。
 *
 * ─── 操作注意事项 ──────────────────────────────
 * 1. 只在前端展示前转换 / 后端永远存原始 WGS-84（数据真相源不动）
 * 2. 国外坐标自动跳过转换（_outOfChina 兜底）
 * 3. 算法是公开的标准 GCJ-02 加密公式 / 不要改里面任何魔法数字
 *
 * ─── 输入 / 输出 ────────────────────────────────
 * 输入：WGS-84 lat / lng（数字 / 度）
 * 输出：[gcjLat, gcjLng] 二元数组（数字 / 度）
 *
 * 算法来源：标准 GCJ-02 加密公式（公开算法）
 * https://en.wikipedia.org/wiki/Restrictions_on_geographic_data_in_China
 */

const PI = 3.141592653589793
const A = 6378245.0                  // 克拉索夫斯基椭球长半轴（米）
const EE = 0.00669342162296594323    // 第一偏心率平方

/**
 * 判断坐标是否在中国大陆境外
 *
 * 用一个粗略矩形框（经度 72~138 / 纬度 0.83~55.83）覆盖中国大陆，
 * 框外的坐标不做加密——这是 GCJ-02 的标准做法。
 *
 * @param {number} lat - WGS-84 纬度
 * @param {number} lng - WGS-84 经度
 * @returns {boolean} true = 国外（跳过转换）/ false = 国内（要转换）
 */
function _outOfChina(lat, lng) {
  if (lng < 72.004 || lng > 137.8347) return true
  if (lat < 0.8293 || lat > 55.8271) return true
  return false
}

/**
 * 纬度方向偏移量计算（GCJ-02 标准公式）
 * 这堆魔法数字来自公开算法，不要改
 */
function _transformLat(x, y) {
  let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  ret += (20.0 * Math.sin(6.0 * x * PI) + 20.0 * Math.sin(2.0 * x * PI)) * 2.0 / 3.0
  ret += (20.0 * Math.sin(y * PI) + 40.0 * Math.sin(y / 3.0 * PI)) * 2.0 / 3.0
  ret += (160.0 * Math.sin(y / 12.0 * PI) + 320 * Math.sin(y * PI / 30.0)) * 2.0 / 3.0
  return ret
}

/**
 * 经度方向偏移量计算（GCJ-02 标准公式）
 */
function _transformLng(x, y) {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  ret += (20.0 * Math.sin(6.0 * x * PI) + 20.0 * Math.sin(2.0 * x * PI)) * 2.0 / 3.0
  ret += (20.0 * Math.sin(x * PI) + 40.0 * Math.sin(x / 3.0 * PI)) * 2.0 / 3.0
  ret += (150.0 * Math.sin(x / 12.0 * PI) + 300.0 * Math.sin(x / 30.0 * PI)) * 2.0 / 3.0
  return ret
}

/**
 * WGS-84 → GCJ-02
 *
 * 国外坐标直接返回（不转）/ 国内坐标按标准公式加密后返回。
 *
 * @param {number} wgsLat - WGS-84 纬度
 * @param {number} wgsLng - WGS-84 经度
 * @returns {[number, number]} [gcjLat, gcjLng]
 */
function wgs84ToGcj02(wgsLat, wgsLng) {
  if (_outOfChina(wgsLat, wgsLng)) {
    return [wgsLat, wgsLng]
  }
  let dLat = _transformLat(wgsLng - 105.0, wgsLat - 35.0)
  let dLng = _transformLng(wgsLng - 105.0, wgsLat - 35.0)
  const radLat = wgsLat / 180.0 * PI
  let magic = Math.sin(radLat)
  magic = 1 - EE * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  dLat = (dLat * 180.0) / ((A * (1 - EE)) / (magic * sqrtMagic) * PI)
  dLng = (dLng * 180.0) / (A / sqrtMagic * Math.cos(radLat) * PI)
  return [wgsLat + dLat, wgsLng + dLng]
}

module.exports = { wgs84ToGcj02 }
