/**
 * 约骑模块共用格式化工具 — 约骑列表 / 详情 / "我的约骑"三页的"显示翻译器"。
 *
 * 这个文件是干什么的：
 *   约骑的列表页、详情页、个人页都要把后端原始数据（米 / ISO 时间戳 / 英文枚举）翻译成
 *   用户能看懂的中文。原本三页各抄了一份一模一样的函数，改一处要改三处、容易漏改不一致。
 *   抽到这里当"单一真相源"，三页都 require 同一份。
 *
 *   ⚠ 注意和通用的 utils/format.js 区分：那个的 formatTime 是"秒数→时长"（赛段成绩 5025→"1:23:45"），
 *   这里的 formatTime 是"时间戳→6月2日 14:30"（约骑出发时间）。同名不同义，绝不能互相替代——
 *   这正是当初不能直接复用 format.js 的原因。
 *
 * 操作注意事项：
 *   - 缺失值一律返回空串（''），让 wxml 用 wx:if 整块隐藏，不显示 "-" 占位符（项目硬规则）。
 *   - 时间按设备本地时区显示（小程序 new Date 默认本地时区 = 北京 UTC+8）。
 *
 * 输入/输出：
 *   formatDistance(米数值) → '12.3 km' | ''        formatClimb(米数值) → '456 m' | ''
 *   formatTime(ISO 字符串) → '6月2日 14:30' | '待定'   paceText(枚举) → '巡航'
 *   statusText(枚举) → '开放中' | '已取消' ...
 */

// 距离：后端返 km 数值 → "12.3 km"。缺失返回空串。
function formatDistance(value) {
  if (value === undefined || value === null) return ''
  return Number(value).toFixed(1) + ' km'
}

// 爬升：米数值 → "456 m"。缺失返回空串。
function formatClimb(value) {
  if (value === undefined || value === null) return ''
  return Math.round(Number(value)) + ' m'
}

// 约骑出发时间：ISO → "6月2日 14:30"。无值返回"待定"，非法时间原样返回（不炸页面）。
function formatTime(value) {
  if (!value) return '待定'
  var date = new Date(value)
  if (isNaN(date.getTime())) return value
  var month = date.getMonth() + 1
  var day = date.getDate()
  var hour = String(date.getHours()).padStart(2, '0')
  var minute = String(date.getMinutes()).padStart(2, '0')
  return month + '月' + day + '日 ' + hour + ':' + minute
}

// 节奏等级枚举 → 中文
function paceText(value) {
  var map = { relaxed: '休闲', cruise: '巡航', training: '训练', race: '强度' }
  return map[value] || value || ''
}

// 约骑状态枚举 → 中文（"我发起的"含草稿/已取消，需要在卡片上标状态）
function statusText(value) {
  var map = { DRAFT: '草稿', OPEN: '开放中', CANCELLED: '已取消', COMPLETED: '已完成' }
  return map[value] || value || ''
}

module.exports = {
  formatDistance: formatDistance,
  formatClimb: formatClimb,
  formatTime: formatTime,
  paceText: paceText,
  statusText: statusText,
}
