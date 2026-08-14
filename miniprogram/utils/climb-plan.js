function normalizeClimbPlan(value) {
  if (!value || typeof value !== 'object') return null
  var composition = value.composition
  var climbs = Array.isArray(value.climbs) ? value.climbs.filter(function (climb) {
    return climb && Number.isFinite(Number(climb.start_distance_m)) && Number.isFinite(Number(climb.end_distance_m))
  }) : []
  if (!composition || typeof composition !== 'object') return null
  return {
    algorithm_version: String(value.algorithm_version || ''),
    source: value.source || {},
    composition: composition,
    climbs: climbs,
  }
}

function categoryLabel(category) {
  return category === 'uncategorized' ? '未分级' : 'Cat ' + category
}

function categoryColor(category) {
  return {
    HC: '#7A3E9D',
    '1': '#D93025',
    '2': '#F57C00',
    '3': '#F9A825',
    '4': '#43A047',
    uncategorized: '#5C7AEA',
  }[String(category)] || '#5C7AEA'
}

function buildView(planValue, riderValue) {
  var plan = normalizeClimbPlan(planValue)
  if (!plan) return { ready: false, sequence: '待计算', climbs: [], riderLine: '', riderContextLine: '', riderScenarios: [] }
  var climbs = plan.climbs.map(function (climb) {
    var max500 = climb.max_sustained_grade_pct && Number(climb.max_sustained_grade_pct['500m'])
    return {
      order: Number(climb.order),
      category: categoryLabel(climb.category),
      categoryRaw: String(climb.category),
      color: categoryColor(climb.category),
      shape: String(climb.shape_label || '坡型待定'),
      shapeLabels: Array.isArray(climb.shape_labels) ? climb.shape_labels.join(' + ') : String(climb.shape_label || ''),
      distance: (Number(climb.length_m) / 1000).toFixed(1) + 'km',
      grade: Number(climb.average_grade_pct).toFixed(1) + '%',
      gain: Math.round(Number(climb.elevation_gain_m)) + 'm',
      max500: Number.isFinite(max500) ? '最陡500m ' + max500.toFixed(1) + '%' : '',
      startKm: (Number(climb.start_distance_m) / 1000).toFixed(1),
      endKm: (Number(climb.end_distance_m) / 1000).toFixed(1),
      candidate: climb.category_status === 'candidate',
    }
  })
  var riderLine = ''
  var riderContextLine = ''
  var riderScenarios = []
  if (riderValue && riderValue.status === 'estimated' && Array.isArray(riderValue.scenarios)) {
    riderScenarios = riderValue.scenarios.map(function (item) {
      var range = item.estimated_climbing_time_range_min
      var powerRange = item.target_power_range_w
      var wkgRange = item.target_w_per_kg_range
      var low = Array.isArray(range) ? Number(range[0]) : NaN
      var high = Array.isArray(range) ? Number(range[1]) : NaN
      var powerLow = Array.isArray(powerRange) ? Number(powerRange[0]) : Number(item.target_power_w)
      var powerHigh = Array.isArray(powerRange) ? Number(powerRange[1]) : Number(item.target_power_w)
      var wkgLow = Array.isArray(wkgRange) ? Number(wkgRange[0]) : Number(item.target_w_per_kg)
      var wkgHigh = Array.isArray(wkgRange) ? Number(wkgRange[1]) : Number(item.target_w_per_kg)
      var climbTargets = Array.isArray(item.climbs) ? item.climbs.map(function (climb) {
        var order = Number(climb.order)
        var watts = Number(climb.target_power_w)
        return Number.isFinite(order) && Number.isFinite(watts)
          ? '第' + order + '坡 ' + Math.round(watts) + 'W'
          : ''
      }).filter(Boolean).join(' · ') : ''
      return {
        key: String(item.key || ''),
        label: String(item.label || ''),
        power: Math.round(powerLow) === Math.round(powerHigh)
          ? Math.round(powerLow) + 'W'
          : Math.round(powerLow) + '–' + Math.round(powerHigh) + 'W',
        powerPerKg: wkgLow.toFixed(2) === wkgHigh.toFixed(2)
          ? wkgLow.toFixed(2) + 'W/kg'
          : wkgLow.toFixed(2) + '–' + wkgHigh.toFixed(2) + 'W/kg',
        time: Number(item.estimated_climbing_time_min).toFixed(0) + '分钟',
        timeRange: Number.isFinite(low) && Number.isFinite(high)
          ? low.toFixed(0) + '–' + high.toFixed(0) + '分钟'
          : '',
        climbTargets: climbTargets,
      }
    })
    var steady = riderValue.scenarios.filter(function (item) { return item.key === 'steady' })[0]
    if (steady) {
      riderLine = steady.label + '：爬坡约' +
        Number(steady.estimated_climbing_time_min).toFixed(0) + '分钟，逐坡目标见上方'
    }
    var multi = riderValue.multi_climb_context || {}
    if (multi.status === 'pdc_cumulative_duration_no_recovery_credit') {
      riderContextLine = '多坡已按累计爬坡时长保守限功；没有 CP/W′，未把下坡恢复当成可用体能。'
    } else if (multi.status === 'pending_without_cp_wprime') {
      riderContextLine = '多坡疲劳与坡间恢复待补 CP/W′；当前各坡按 FTP 独立估算。'
    }
  } else if (riderValue && riderValue.status === 'needs_profile') {
    riderLine = '填写 FTP 和体重后，可估算你的爬坡时间与目标功率'
  }
  return {
    ready: true,
    sequence: String(plan.composition.sequence_label || '无显著爬坡'),
    climbs: climbs,
    riderLine: riderLine,
    riderContextLine: riderContextLine,
    riderScenarios: riderScenarios,
    boundaryStatus: String(plan.composition.boundary_status || ''),
  }
}

module.exports = {
  normalizeClimbPlan: normalizeClimbPlan,
  categoryLabel: categoryLabel,
  categoryColor: categoryColor,
  buildView: buildView,
}
