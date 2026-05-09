/**
 * 城市常量公共模块 — 多个页面共用的"城市翻译卡片"
 *
 * 这个文件是干什么的：
 *   后端 User.city / Segment.city 字段存的是英文枚举（'beijing' / 'shanghai' / ...），
 *   小程序模板（WXML）不会做枚举映射，所以在 JS 层把英文翻译成中文，
 *   再传给模板直接显示中文。这个翻译表多个页面都要用（个人页 + 用户详情页 + 未来探索页），
 *   所以抽出来放在 utils 下，避免每个页面各自写一份"北京 / 上海 / 杭州"重复代码。
 *
 *   类比：就像公司前台的"中英对照名牌"——
 *   后端系统记录员工编号"E001"，前台把它翻译成"张三 / Zhang San"贴在工位牌上，
 *   每个会议室、每个楼层都贴同一张表，就不会出现"3 楼写张三、5 楼写 Zhang San"的混乱。
 *
 * 操作注意事项：
 *   1. 城市枚举跟后端 spec §3.1.3 严格对齐（6 城枚举 + 'unknown'），
 *      新增城市必须先后端加枚举 + Alembic 迁移再来这里加。
 *   2. 'unknown' 在表里不映射 — fallback 逻辑由调用方处理（一般是不显示 city badge），
 *      防御写法：getCityLabel(city) 返回 '' 时模板用 wx:if 隐藏。
 *   3. 不要在这里加业务判断（如"北京就显示首都标签"），
 *      这只是翻译表，业务逻辑放调用方页面里。
 *
 * 输入输出：
 *   输入：英文城市枚举字符串（'beijing' / 'shanghai' / ...）或 null / undefined / 'unknown'
 *   输出：中文标签字符串 或 空串 ''（让模板 wx:if 不显示 badge）
 *
 * 使用方式：
 *   const { CITY_LABELS, getCityLabel } = require('../../utils/city')
 *   const label = getCityLabel(profile.city)  // 'beijing' → '北京' / 'unknown' → ''
 */

/**
 * 6 城枚举 → 中文标签映射
 * 跟后端 schemas.py UserCity / SegmentCity 严格对齐（spec §3.1.3）
 */
const CITY_LABELS = {
  beijing: '北京',
  shanghai: '上海',
  hangzhou: '杭州',
  shenzhen: '深圳',
  chengdu: '成都',
  taiyuan: '太原',
}

/**
 * 取城市中文标签（含 'unknown' / null / undefined fallback）
 *
 * 设计说明：
 *   - city 为 null / undefined / '' / 'unknown' 都返回 ''（让模板 wx:if 隐藏 badge）
 *   - city 为 6 城枚举返回中文
 *   - city 为意外值（脏数据）也返回 ''（防御写法）
 *
 * @param {string|null|undefined} city - 城市英文枚举
 * @returns {string} 中文标签 或 ''
 */
function getCityLabel(city) {
  if (!city || city === 'unknown') return ''
  return CITY_LABELS[city] || ''
}

module.exports = {
  CITY_LABELS,
  getCityLabel,
}
