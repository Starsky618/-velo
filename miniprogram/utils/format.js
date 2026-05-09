/**
 * 通用格式化工具 — 多页面共用的"显示翻译器"
 *
 * 这个文件是干什么的：
 *   后端返回的原始数据（秒数 / ISO 时间戳）不适合直接给用户看，
 *   小程序模板（WXML）也不擅长做格式转换，所以在 JS 层把原始数据
 *   翻译成"人话"（"1:23:45" / "2026-04-30"），再传给模板显示。
 *
 *   类比：就像电视机里的字幕组——
 *   后端讲日语（原始秒数 5025），字幕组翻译成中文"1 小时 23 分 45 秒"，
 *   观众一看就懂，不用自己心算。
 *
 * 操作注意事项：
 *   1. 输入做防御（null / undefined / NaN 都返回 '-' 而不是抛错），
 *      防止 wxml 渲染时炸页面。
 *   2. 时间戳一律按本地时区显示（小程序 new Date 默认本地时区），
 *      跟全局 CLAUDE.md "时区按北京时间 UTC+8" 一致。
 *   3. 不要在这里加业务格式（"PB" / "进步 5 秒"等），
 *      这只是基础格式化工具，业务文案放调用方页面里。
 *
 * 输入输出：
 *   formatTime(seconds: number) → '1:23:45' 或 '23:45' 或 '-'
 *   formatDate(isoString: string) → '2026-04-30' 或 '-'
 *
 * 使用方式：
 *   const { formatTime, formatDate } = require('../../utils/format')
 *   const display = formatTime(effort.elapsed_time)  // 5025 → '1:23:45'
 */

/**
 * 秒数 → "时:分:秒" 字符串
 *
 * 设计说明：
 *   - 不到 1 小时 → "M:SS"（如 "23:45"，简洁省空间）
 *   - 超过 1 小时 → "H:MM:SS"（如 "1:23:45"，保留小时位）
 *   - 输入非法（null / undefined / NaN / 负数）→ '-'
 *
 *   为什么这么设计：赛段成绩 80% 在 1 小时内（公路赛段平均 5-30 分钟），
 *   "23:45" 比 "0:23:45" 更直观，省一个像素位让数字更突出。
 *
 * @param {number} seconds - 用时秒数
 * @returns {string} 格式化字符串
 */
function formatTime(seconds) {
  if (seconds === null || seconds === undefined || isNaN(seconds) || seconds < 0) {
    return '-'
  }
  var s = Math.floor(seconds)
  var h = Math.floor(s / 3600)
  var m = Math.floor((s % 3600) / 60)
  var sec = s % 60
  // 补零（"5" → "05" / 让 "12:05" 不变成 "12:5"）
  var mm = m < 10 ? '0' + m : '' + m
  var ss = sec < 10 ? '0' + sec : '' + sec
  if (h > 0) {
    // 小时位不补零（"1:23:45" 比 "01:23:45" 更自然）
    return h + ':' + mm + ':' + ss
  }
  return m + ':' + ss
}

/**
 * ISO 时间戳 → "YYYY-MM-DD" 字符串
 *
 * 设计说明：
 *   - 输入 ISO 字符串（"2026-04-30T12:00:00+00:00"）或 Date 对象
 *   - 输出本地时区日期（小程序 new Date 自动按设备本地时区解析，UTC+8 即北京时间）
 *   - 输入非法（null / undefined / 解析失败）→ '-'
 *
 *   为什么不显示时分：赛段成绩"创下于 2026-04-30 14:23"对用户没用，
 *   日期足够（用户记得"上周日骑的"，不记得"下午两点几分"）。
 *
 * @param {string|Date} iso - ISO 时间戳字符串 或 Date 对象
 * @returns {string} 'YYYY-MM-DD' 或 '-'
 */
function formatDate(iso) {
  if (!iso) return '-'
  var d = (iso instanceof Date) ? iso : new Date(iso)
  // Invalid Date 的 getTime() 返回 NaN
  if (isNaN(d.getTime())) return '-'
  var y = d.getFullYear()
  var mo = d.getMonth() + 1  // getMonth 从 0 开始
  var day = d.getDate()
  var mm = mo < 10 ? '0' + mo : '' + mo
  var dd = day < 10 ? '0' + day : '' + day
  return y + '-' + mm + '-' + dd
}

module.exports = {
  formatTime: formatTime,
  formatDate: formatDate,
}
