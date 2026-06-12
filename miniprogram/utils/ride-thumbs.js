/**
 * 活动轨迹缩略点的批量获取与缓存 —— "活动列表加路线小图"的数据搬运工。
 *
 * 干啥用：活动列表接口刻意不带轨迹（响应体轻量），这个模块拿一页活动的 id
 * 去 GET /api/activities/track-thumbs 批量换抽稀轨迹点（[[lon, lat], ...]），
 * 并按 activity_id 缓存——翻页回来、切页面回来都不重复请求。
 *
 * 注意事项：
 * 1. 后端只返回"本人 + 有轨迹"的活动，缺席是正常情况（无轨迹的老活动），
 *    调用方按"拿到才显示"处理，不要把缺席当错误。
 * 2. 后端单次最多处理 20 个 id，这里按 20 切片分批请求。
 *
 * 输入/输出：fetchTrackPoints(rides) → Promise<cache>（{activity_id: points}）；
 * 失败静默返回现有缓存，列表主流程不受影响。
 */

var api = require('./api')

// 模块级缓存：同一活动的轨迹点跨页面、跨翻页共享
var cache = {}

function fetchTrackPoints(rides) {
  var need = []
  ;(rides || []).forEach(function (r) {
    if (r && r.id && !cache[r.id]) need.push(r.id)
  })
  if (need.length === 0) return Promise.resolve(cache)

  // 后端单次 cap 20：按 20 切片并行请求
  var batches = []
  for (var i = 0; i < need.length; i += 20) {
    batches.push(need.slice(i, i + 20))
  }
  var tasks = batches.map(function (ids) {
    return api.get('/api/activities/track-thumbs?ids=' + ids.join(','))
      .then(function (res) {
        ;((res && res.items) || []).forEach(function (item) {
          cache[item.activity_id] = item.points
        })
      })
      .catch(function () {
        // 静默：缩略图是锦上添花，拉不到不影响列表主流程
      })
  })
  return Promise.all(tasks).then(function () { return cache })
}

module.exports = {
  fetchTrackPoints: fetchTrackPoints,
}
