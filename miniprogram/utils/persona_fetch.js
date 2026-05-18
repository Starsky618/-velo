// PERSONA_START
/**
 * NPC 文案 endpoint 调用层（Persona Engine task-5）。
 *
 * 干啥：profile / user / detail / upload 4 个 page 调这里拿当前场景 NPC 文案。
 * 失败兜底：API 返 null / 报错 → 静默返 {template_text: null} / 不让 UI 崩。
 *
 * 类比：前端跟后端要老登一句话——后端没在家不报错 / 静默返"老登没说"。
 *
 * 接口契约对照 task-4 endpoint：
 *   GET /api/persona/output?scene_type=X[&activity_id=Y][&target_user_id=Z]
 *   GET /api/persona/recent?limit=10
 */

const api = require('./api')

/**
 * 调 /api/persona/output 拿当前场景 NPC 文案。
 *
 * @param {string} sceneType    场景标签（profile_open / user_page_open / activity_upload
 *                              / pr / segment_distance / silence / 等宪法 7 场景）
 * @param {number=} activityId  可选 / detail 页 / upload toast 传入精准定位
 * @param {number=} targetUserId 可选 / 看他人页传被看者 user_id / 未传 = 看自己
 * @returns {Promise<{template_text: string|null, scene_type: string, created_at: string|null}>}
 */
function fetchPersonaOutput(sceneType, activityId, targetUserId) {
  var params = { scene_type: sceneType }
  if (activityId) params.activity_id = activityId
  if (targetUserId) params.target_user_id = targetUserId
  return api.get('/api/persona/output', params)
    .catch(function (err) {
      console.warn('persona fetch failed (silently ignored):', err)
      return { template_text: null, scene_type: sceneType, created_at: null }
    })
}

/**
 * 拿用户最近 N 条 NPC 历史。
 * @param {number=} limit 1-50 / 默认 10
 */
function fetchRecentPersona(limit) {
  return api.get('/api/persona/recent', { limit: limit || 10 })
    .catch(function () { return { items: [] } })
}

module.exports = { fetchPersonaOutput, fetchRecentPersona }
// PERSONA_END
