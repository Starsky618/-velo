/**
 * 功率区间展示工具 —— 小程序里专门负责把 Z1-Z6 翻译成可看的页面行。
 *
 * 这里不请求接口、不改数据库，只处理后端已经给到前端的 power_zones。
 * 可以把它想成"账单打印员"：原始账本还在后端和数据库里，这里只决定
 * 用户拿到手上的账单怎么显示。
 */

function toSafeSeconds(value) {
  var seconds = Number(value)
  if (!isFinite(seconds) || seconds <= 0) return 0
  return Math.round(seconds)
}

function normalizeZoneLabel(zone) {
  if (zone === undefined || zone === null || zone === '') return ''
  var text = String(zone)
  return text.indexOf('Z') === 0 ? text : 'Z' + text
}

function isZ1(item) {
  return normalizeZoneLabel(item && item.zone) === 'Z1'
}

function percent(seconds, totalSeconds) {
  if (totalSeconds <= 0) return 0
  return Math.round(seconds / totalSeconds * 100)
}

function formatPowerSeconds(seconds) {
  var safeSeconds = toSafeSeconds(seconds)
  if (safeSeconds >= 3600) {
    return (Math.round(safeSeconds / 360) / 10).toFixed(1) + 'h'
  }
  if (safeSeconds >= 60) {
    return Math.round(safeSeconds / 60) + '分'
  }
  return safeSeconds + '秒'
}

function cloneZoneRow(item, seconds, zonePercent) {
  var row = {}
  for (var key in item) {
    if (Object.prototype.hasOwnProperty.call(item, key)) {
      row[key] = item[key]
    }
  }
  row.zoneLabel = normalizeZoneLabel(row.zone)
  row.seconds = seconds
  row.percent = zonePercent
  row.timeText = formatPowerSeconds(seconds)
  return row
}

function formatPowerZoneRows(powerZones) {
  if (!Array.isArray(powerZones)) return []
  return powerZones.map(function (item) {
    var seconds = toSafeSeconds(item && item.seconds)
    var zonePercent = Math.round(Number(item && item.percent) || 0)
    return cloneZoneRow(item || {}, seconds, zonePercent)
  })
}

function buildPedalingPowerZones(powerZones) {
  if (!Array.isArray(powerZones)) return []

  var prepared = []
  var displayTotalSeconds = 0

  for (var i = 0; i < powerZones.length; i++) {
    var item = powerZones[i] || {}
    var seconds = toSafeSeconds(item.seconds)
    if (isZ1(item)) {
      // 0W 是"车还在记录，但人没有蹬"的时间。活动详情默认展示真实蹬踏时间，
      // 所以只从 Z1 里扣掉 zero_seconds；Z2-Z6 本来就不可能是 0W。
      var zeroSeconds = Math.min(seconds, toSafeSeconds(item.zero_seconds))
      seconds = Math.max(0, seconds - zeroSeconds)
    }
    prepared.push({ item: item, seconds: seconds })
    displayTotalSeconds += seconds
  }

  return prepared.map(function (entry) {
    return cloneZoneRow(entry.item, entry.seconds, percent(entry.seconds, displayTotalSeconds))
  })
}

module.exports = {
  buildPedalingPowerZones: buildPedalingPowerZones,
  formatPowerZoneRows: formatPowerZoneRows,
  formatPowerSeconds: formatPowerSeconds,
}
