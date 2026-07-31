/**
 * 个人热图瓦片的应用会话缓存。
 *
 * 微信下载得到的临时文件在当前小程序会话内有效。把文件表放在共享模块里，个人页卡片、
 * 全屏页以及页面重建后都能复用同一份文件；key 必须包含用户、数据 generation、年份、
 * 配色和 z/x/y，数据变化时自然切到新版本，不需要冒险清理仍在显示的旧文件。
 */

const MAX_FILES = 128
const files = {}
const inflight = {}
let accessSeed = 0

function prune() {
  var keys = Object.keys(files)
  if (keys.length <= MAX_FILES) return
  keys.sort(function (left, right) {
    return files[left].access - files[right].access
  })
  keys.slice(0, keys.length - MAX_FILES).forEach(function (key) {
    delete files[key]
  })
}

function load(key, loader) {
  var cached = files[key]
  if (cached && cached.path) {
    cached.access = ++accessSeed
    return Promise.resolve(cached.path)
  }
  if (inflight[key]) return inflight[key]

  var pending
  try {
    pending = loader()
  } catch (error) {
    return Promise.reject(error)
  }
  var request = Promise.resolve(pending)
    .then(function (file) {
      var path = file && (file.filePath || file.tempFilePath)
      if (!path) {
        delete inflight[key]
        throw new Error('heatmap tile has no local path')
      }
      files[key] = { path: path, access: ++accessSeed }
      delete inflight[key]
      prune()
      return path
    }, function (error) {
      delete inflight[key]
      throw error
    })
  inflight[key] = request
  return request
}

function remove(key) {
  delete files[key]
}

function appIdentity() {
  if (typeof getApp !== 'function') return { userId: 0, token: '' }
  try {
    var app = getApp()
    return {
      userId: Number(app && app.globalData && app.globalData.userId) || 0,
      token: String(app && app.globalData && app.globalData.token || ''),
    }
  } catch (error) {
    return { userId: 0, token: '' }
  }
}

function tokenHash(token) {
  // 只用于内存 key 分区，不输出也不持久化 token；FNV-1a 足够区分本机会话。
  var hash = 2166136261
  for (var index = 0; index < token.length; index++) {
    hash ^= token.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

function viewerScope() {
  var identity = appIdentity()
  if (identity.userId > 0) return 'viewer-' + identity.userId
  if (identity.token) return 'viewer-token-' + tokenHash(identity.token)
  return 'viewer-anonymous'
}

function userScope(explicitUserId) {
  var userId = Number(explicitUserId) || 0
  if (!userId) userId = appIdentity().userId
  return userId > 0 ? 'user-' + userId : 'me'
}

function audienceScope(explicitUserId) {
  var targetUserId = Number(explicitUserId) || 0
  var viewerUserId = appIdentity().userId
  if (!targetUserId || (viewerUserId > 0 && viewerUserId === targetUserId)) {
    return 'audience-owner'
  }
  return 'audience-public'
}

function clearAll() {
  Object.keys(files).forEach(function (key) { delete files[key] })
  Object.keys(inflight).forEach(function (key) { delete inflight[key] })
}

module.exports = {
  load: load,
  remove: remove,
  userScope: userScope,
  viewerScope: viewerScope,
  audienceScope: audienceScope,
  clearAll: clearAll,
}
