/**
 * 轻量产品埋点工具（演示版）
 *
 * 当前阶段不发后端，只做三件事：
 * 1. 统一事件结构，避免页面散落自定义字段。
 * 2. console.log 方便微信开发者工具即时观察。
 * 3. 写入本地 storage 最近 100 条，方便调试回看。
 *
 * 后续接后端时，只需要在 track() 里追加 api.post('/api/analytics/events', event)，
 * 页面侧调用保持不变。
 */

var STORAGE_KEY = 'analytics_events_demo'
var SESSION_KEY = 'analytics_session_id'
var MAX_EVENTS = 100

var EVENT_NAMES = [
  'app_open',
  'page_view',
  'home_action_click',
  'upload_start',
  'upload_success',
  'parse_failed',
  'activity_completed_view',
  'segment_detail_view',
  'leaderboard_view',
  'my_effort_compare_view',
  'notification_click',
  'other_user_profile_view',
]

function getAppSafe() {
  try {
    return getApp()
  } catch (e) {
    return null
  }
}

function getSessionId() {
  var sessionId = wx.getStorageSync(SESSION_KEY)
  if (!sessionId) {
    sessionId = Date.now() + '_' + Math.random().toString(36).slice(2)
    wx.setStorageSync(SESSION_KEY, sessionId)
  }
  return sessionId
}

function getUserId() {
  var app = getAppSafe()
  var gd = app && app.globalData
  return (gd && (gd.userId || (gd.userInfo && gd.userInfo.id))) || null
}

function normalizeProperties(properties) {
  var props = properties || {}
  return {
    page: props.page || '',
    source: props.source || '',
    target_type: props.target_type || '',
    target_id: props.target_id || '',
    properties: props,
  }
}

function track(eventName, properties) {
  var normalized = normalizeProperties(properties)
  var event = {
    event_name: eventName,
    user_id: getUserId(),
    session_id: getSessionId(),
    page: normalized.page,
    source: normalized.source,
    target_type: normalized.target_type,
    target_id: normalized.target_id,
    properties: normalized.properties,
    created_at: new Date().toISOString(),
  }

  console.log('[analytics]', event)

  var events = wx.getStorageSync(STORAGE_KEY) || []
  events.push(event)
  if (events.length > MAX_EVENTS) {
    events = events.slice(events.length - MAX_EVENTS)
  }
  wx.setStorageSync(STORAGE_KEY, events)

  return event
}

function trackPageView(page, properties) {
  var props = Object.assign({}, properties || {}, { page: page })
  return track('page_view', props)
}

module.exports = {
  EVENT_NAMES: EVENT_NAMES,
  track: track,
  trackPageView: trackPageView,
}
