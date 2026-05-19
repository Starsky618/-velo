const assert = require('assert')

let storage = {}

global.wx = {
  getStorageSync(key) {
    return storage[key]
  },
  setStorageSync(key, value) {
    storage[key] = value
  },
}

global.getApp = function () {
  return {
    globalData: {
      userId: 42,
    },
  }
}

console.log = function () {}

const analytics = require('../../miniprogram/utils/analytics')

storage = {}
const first = analytics.track('home_action_click', {
  page: 'home',
  target_type: 'tab',
  target_id: 'upload',
})

assert.strictEqual(first.event_name, 'home_action_click')
assert.strictEqual(first.user_id, 42)
assert.strictEqual(first.page, 'home')
assert.strictEqual(first.target_type, 'tab')
assert.strictEqual(first.target_id, 'upload')
assert.ok(first.session_id)
assert.ok(first.created_at)
assert.strictEqual(storage.analytics_events_demo.length, 1)

for (let i = 0; i < 105; i++) {
  analytics.track('page_view', { page: 'home', index: i })
}

assert.strictEqual(storage.analytics_events_demo.length, 100)
assert.strictEqual(storage.analytics_events_demo[0].properties.index, 5)

const names = analytics.EVENT_NAMES
assert.strictEqual(names.length, 12)
assert.ok(names.indexOf('app_open') !== -1)
assert.ok(names.indexOf('other_user_profile_view') !== -1)
