// PERSONA_START
/**
 * 静态 NPC 文案表（错误页 / 空状态 / 加载等中间态用）。
 *
 * 这些场景不调 endpoint / 直接前端写死（宪法 §2.6 拍定 ground truth）。
 * 理由：网络断 / 服务器 5xx 时调 endpoint 本身可能失败 / 不能让"显示文案"还依赖后端。
 *
 * 类比：消防演习用的预录广播 / 不依赖任何外部系统 / 断电也能播。
 *
 * 文案来源：docs/agent-rules/persona-constitution.md §2.6（v0.2 拍定 6 条中间态）。
 * **v0.2 过拟合裁定（2026-05-18 Tim 拍）**：uploading + delete_confirm 是关键操作场景 /
 * 必须用系统标准客服文案 / 不入 NPC 库 / 故本表不含这两 key（用 wx.showToast 系统默认即可）。
 */

const PERSONA_STATIC_TEXTS = {
  empty: '还没数据。先去蹬两圈。',
  upload_failed: '今天轨迹丢了。下次记得开 GPS。',
  network_down: '连不上。WiFi 切流量试试。',
  server_5xx: '服务器在打盹儿。',
  loading: '算你的高光中…',
  unauth_401: '要重新登录一下了。',
  // uploading / delete_confirm 不入 NPC 库（宪法 §2.6 v0.2 / 用系统标准 toast / 标准客服文案）
}

/**
 * 拿静态 NPC 文案。
 * @param {string} key 6 类中间态之一（empty / upload_failed / network_down / server_5xx / loading / unauth_401）
 * @returns {string} 文案字面 / 未命中返空串
 */
function getPersonaStatic(key) {
  return PERSONA_STATIC_TEXTS[key] || ''
}

module.exports = { getPersonaStatic, PERSONA_STATIC_TEXTS }
// PERSONA_END
