/**
 * API 通信层 — 小程序和后端之间的"电话线"
 *
 * 所有和服务器的通信都走这一个文件，页面不直接发请求。
 * 好处：如果后端接口地址变了，只改这一个文件，所有页面自动生效。
 *
 * 类比：这就像公司的总机号码——外面打电话进来统一转接，
 * 不需要知道每个部门的分机号。
 *
 * 使用方式：
 *   const api = require('../../utils/api')
 *   api.get('/api/activities').then(res => { ... })
 *
 * 注意：不能在模块顶层调用 getApp()！
 * 因为 app.js 在初始化时就 require 了这个文件，
 * 此时 App 还没创建完，getApp() 会返回 undefined。
 * 所以每次请求时才通过 getApp() 获取全局实例。
 */

// 后端 API 地址（硬编码在这里作为兜底，正常走 app.globalData.baseUrl）
// 2026-06-12 切回 https 域名（与 app.js baseUrl 同步，两处一起改）；
// 前置 = 腾讯云安全组放行 443（详 app.js 同位置注释）
var BASE_URL = 'https://api.weiluai.top'

/**
 * 获取全局 App 实例（延迟获取，避免初始化时序问题）
 */
function getAppSafe() {
  return getApp()
}

/**
 * 封装 wx.request，统一处理 token、错误、loading
 *
 * @param {string} url - 接口路径，如 '/api/activities'
 * @param {string} method - HTTP 方法：GET / POST / PUT / DELETE
 * @param {object} data - 请求体数据
 * @returns {Promise} 后端返回的 JSON 数据
 */
function request(url, method, data) {
  // 每次请求时获取 app 实例（此时 App 一定已经初始化完成）
  var app = getAppSafe()
  var baseUrl = (app && app.globalData.baseUrl) || BASE_URL
  var token = app && app.globalData.token

  if (method === undefined) method = 'GET'
  if (data === undefined) data = {}

  return new Promise(function (resolve, reject) {
    wx.request({
      url: baseUrl + url,
      method: method,
      data: data,
      header: {
        'Content-Type': 'application/json',
        // 如果有 token，自动带上（证明"我是谁"）
        'Authorization': token ? 'Bearer ' + token : '',
      },
      success: function (res) {
        if (res.statusCode === 401) {
          // 清除本地 token（可能已过期）
          if (app) {
            app.globalData.token = null
          }
          wx.removeStorageSync('token')
          var detail = (res.data && res.data.detail) || '登录已过期，请重新登录'
          reject({ code: 401, message: detail })
          return
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          // 5xx 用通用兜底 / 4xx 透传后端 detail（按状态码分流 / 防 catch-all 误导）
          var defaultMsg = '请求失败'
          if (res.statusCode >= 500) defaultMsg = '服务器开小差了，请稍后重试'
          reject({
            code: res.statusCode,
            message: (res.data && res.data.detail) || defaultMsg,
          })
        }
      },
      fail: function () {
        reject({ code: -1, message: '网络连接失败，请检查网络' })
      },
    })
  })
}

/**
 * 表单请求专用：路书从已有骑行生成时，后端按 multipart/form 表单收字段。
 *
 * 类比：普通 request 像寄一个 JSON 文件；这里像在柜台填纸质表格，
 * 每个格子单独交给后端，避免把表单接口误塞成 JSON。
 */
function requestForm(url, method, data) {
  var app = getAppSafe()
  var baseUrl = (app && app.globalData.baseUrl) || BASE_URL
  var token = app && app.globalData.token

  if (method === undefined) method = 'POST'
  if (data === undefined) data = {}

  return new Promise(function (resolve, reject) {
    wx.request({
      url: baseUrl + url,
      method: method,
      data: data,
      header: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': token ? 'Bearer ' + token : '',
      },
      success: function (res) {
        if (res.statusCode === 401) {
          if (app) {
            app.globalData.token = null
          }
          wx.removeStorageSync('token')
          var detail = (res.data && res.data.detail) || '登录已过期，请重新登录'
          reject({ code: 401, message: detail })
          return
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          var defaultMsg = res.statusCode >= 500 ? '服务器开小差了，请稍后重试' : '请求失败'
          reject({
            code: res.statusCode,
            message: (res.data && res.data.detail) || defaultMsg,
          })
        }
      },
      fail: function () {
        reject({ code: -1, message: '网络连接失败，请检查网络' })
      },
    })
  })
}

/**
 * 把 params 对象拼成 URL query 字符串。
 *
 * 设计说明：
 * - 跳过 undefined / null（不该出现在 URL 上）
 * - 保留 false / 0 / ""（它们都是合法值，如 page_size=0 无意义但 page=0 可能有意义）
 * - 用 encodeURIComponent 保证中文和特殊字符能安全传输
 *
 * 类比：就像寄快递时的收件地址——
 * 对象的 key 是"省/市/街道"的标签，value 是具体内容，
 * 最后拼成"?省=山西&市=太原"这种一条线写完的格式。
 *
 * @param {object} params 例如 { unread_only: true, page: 1 }
 * @returns {string} 例如 "?unread_only=true&page=1"；无参数返回空串
 */
function buildQuery(params) {
  if (!params) return ''
  var parts = []
  for (var k in params) {
    if (!params.hasOwnProperty(k)) continue
    var v = params[k]
    if (v === undefined || v === null) continue
    parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v))
  }
  return parts.length > 0 ? '?' + parts.join('&') : ''
}

function absoluteUrl(url) {
  if (/^https?:\/\//.test(url)) return url
  var app = getAppSafe()
  var baseUrl = (app && app.globalData.baseUrl) || BASE_URL
  return baseUrl + url
}

function safeLocalFileName(fileName) {
  var raw = String(fileName || ('route-' + Date.now() + '.gpx')).trim()
  var cleaned = raw.replace(/[\\/:*?"<>|]/g, '-').replace(/\s+/g, '-')
  if (!cleaned) cleaned = 'route-' + Date.now() + '.gpx'
  return cleaned.slice(0, 80)
}

function saveDownloadedFile(tempFilePath, fileName) {
  if (!tempFilePath || !fileName || !wx.env || !wx.env.USER_DATA_PATH || typeof wx.getFileSystemManager !== 'function') {
    return Promise.resolve(tempFilePath)
  }
  var localPath = wx.env.USER_DATA_PATH + '/' + Date.now() + '-' + safeLocalFileName(fileName)
  var fs = wx.getFileSystemManager()
  return new Promise(function (resolve) {
    fs.saveFile({
      tempFilePath: tempFilePath,
      filePath: localPath,
      success: function (res) {
        resolve(res.savedFilePath || localPath)
      },
      fail: function (err) {
        console.warn('route export save file failed:', err && err.errMsg)
        resolve(tempFilePath)
      },
    })
  })
}

function downloadFile(url, fileName) {
  var app = getAppSafe()
  var token = app && app.globalData.token
  return new Promise(function (resolve, reject) {
    var options = {
      url: absoluteUrl(url),
      header: {
        'Authorization': token ? 'Bearer ' + token : '',
      },
      success: function (res) {
        if (res.statusCode >= 200 && res.statusCode < 300 && res.tempFilePath) {
          var tempFilePath = res.tempFilePath
          saveDownloadedFile(tempFilePath, fileName).then(function (savedFilePath) {
            resolve({
              tempFilePath: tempFilePath,
              savedFilePath: savedFilePath,
              filePath: savedFilePath || tempFilePath,
            })
          })
          return
        }
        var message = '文件下载失败'
        if (res.statusCode === 403) message = '你没有权限下载这条路线'
        if (res.statusCode === 404) message = '下载文件不存在'
        if (res.statusCode >= 500) message = '服务器开小差了，请稍后重试'
        reject({ code: res.statusCode || -1, message: message })
      },
      fail: function (err) {
        reject({
          code: -1,
          message: '网络连接失败，请检查网络',
          rawMessage: err && err.errMsg,
        })
      },
    }
    wx.downloadFile(options)
  })
}

function copyText(text) {
  return new Promise(function (resolve, reject) {
    wx.setClipboardData({
      data: text,
      success: resolve,
      fail: function (err) {
        reject({
          code: -1,
          message: '复制失败，请稍后再试',
          rawMessage: err && err.errMsg,
        })
      },
    })
  })
}

function shareFile(filePath, fileName) {
  return new Promise(function (resolve, reject) {
    if (typeof wx.shareFileMessage !== 'function') {
      reject({ code: -2, message: '当前微信版本不支持发送文件' })
      return
    }
    wx.shareFileMessage({
      filePath: filePath,
      fileName: fileName,
      success: function (res) {
        resolve(res)
      },
      fail: function (err) {
        var rawMessage = err && err.errMsg
        var message = '微信没有打开发送面板'
        if (rawMessage && rawMessage.indexOf('开发者工具暂时不支持') >= 0) {
          message = '开发者工具不支持发送文件，请用真机测试'
        }
        reject({
          code: -1,
          message: message,
          rawMessage: rawMessage,
        })
      },
    })
  })
}

// 快捷方法：api.get('/path')、api.post('/path', data)
module.exports = {
  // v4 扩展：get 支持可选 params 对象（不传则等同旧行为，向后兼容）
  //   老用法：api.get('/api/activities')
  //   新用法：api.get('/api/notifications', { unread_only: true, page: 1 })
  get: function (url, params) { return request(url + buildQuery(params), 'GET') },
  post: function (url, data) { return request(url, 'POST', data) },
  put: function (url, data) { return request(url, 'PUT', data) },
  // Sprint 6 task-4：profile 编辑 bio / city 走 PATCH /api/user/me（settings 类小修改）
  // 与 put 同形：URL + body / 后端 PATCH endpoint 自带"未传字段不改"语义（Optional 字段）
  patch: function (url, data) { return request(url, 'PATCH', data) },
  del: function (url) { return request(url, 'DELETE') },

  /**
   * 看他人 profile（task-4.3 用户详情页 / D-P08 严格白名单）
   *
   * 后端契约（GET /api/user/{user_id}/profile）：
   *   - 只返公开字段：id / nickname / city / 累计统计
   *   - 不返敏感字段：phone / openid / strava_token / ftp / weight
   *   - user 不存在 → 404 → reject({ code: 404, ... })
   *
   * 注意：getUserPowerCurve / getUserHeatmap 不在这里加 — component 内部直接调
   * （详 components/power-curve-card/power-curve-card.js _fetchAndRender / heatmap-card 同）
   *
   * @param {number} userId - 目标用户 ID
   * @returns {Promise<object>} { id, nickname, city, ... 累计统计 }
   */
  getUserProfile: function (userId) { return request('/api/user/' + userId + '/profile', 'GET') },

  /**
   * 注销账号：彻底删除当前用户及全部个人数据（骑行/赛段成绩/功率/Strava/约骑草稿）。
   * 不可逆。后端 DELETE /api/user/me，鉴权用 JWT 锁定本人。成功后调用方须清 token 退出登录。
   * @returns {Promise}
   */
  deleteAccount: function () { return request('/api/user/me', 'DELETE') },

  /**
   * 拉取赛段列表（task-4.4 explore tab 瀑布流用）
   *
   * 类比：就像翻一本"全国赛段大全目录"——
   * 每页 20 条 / 可按城市筛选 / 默认按"上架时间"倒序（新赛段优先）。
   *
   * 后端契约（GET /api/segments）：
   *   - city：6 城枚举（beijing/shanghai/hangzhou/shenzhen/chengdu/taiyuan）+ unknown / 不传则不筛
   *   - page：从 1 起 / page_size：默认 20 / 上限 100
   *   - 后端默认按 created_at desc 排序（新赛段在前）
   *   - 真返字段（SegmentListItem schema 实证 / commit 9250106 加 created_at）：
   *       id / name / distance / elevation_gain / avg_gradient / max_gradient
   *       difficulty / city / start_lat / start_lon / end_lat / end_lon / entries / created_at
   *   - NEW 标签：前端 30 天判断（30 天内 created_at → true）
   *
   * @param {object} params - { city?: string, page?: number, page_size?: number }
   * @returns {Promise<object>} { items: SegmentListItem[], total, page, page_size }
   */
  getSegmentsList: function (params) {
    if (!params) params = {}
    var city = params.city || ''
    var search = params.search || ''
    var page = params.page || 1
    var pageSize = params.page_size || 20
    var query = []
    if (city) query.push('city=' + encodeURIComponent(city))
    // Sprint 5 task-3 真用回归 / codex 抓 Critical 修：search 参数之前漏拼 / 搜赛段形同虚设
    if (search) query.push('search=' + encodeURIComponent(search))
    query.push('page=' + page, 'page_size=' + pageSize)
    return request('/api/segments?' + query.join('&'), 'GET')
  },

  /**
   * 拉取赛段详情（task-4.5 第一屏 + AI 介绍区块用）
   *
   * 类比：就像翻"赛道说明书"——
   * 这条赛段叫什么、几公里、爬升多少、admin 写过啥介绍。
   *
   * 后端契约（GET /api/segments/{id} / 不需登录）：
   *   - 真返字段（SegmentDetailResponse schema 实证 app/segment/schemas.py:159）：
   *       id / name / description（即"AI 介绍"落地字段，admin/service.py:222 写入） /
   *       distance（公里 / service 已转换） / elevation_gain（米） /
   *       avg_gradient / max_gradient（%） / difficulty（4 档枚举） /
   *       city（6 城 + unknown） / start_lat/lon / end_lat/lon /
   *       match_tolerance / min_match_ratio / created_at /
   *       elevation_profile（list[float] | null）—— 约 80 个海拔采样（米），
   *         前端 buildElevationData 拿来画曲线；老赛段未生成时为 null /
   *         hasElevationProfile=false 走 placeholder 降级 /
   *       leaderboard（数组 / 含 rank/user_id/nickname/elapsed_time 等 / 前 20 名）
   *   - 404 segment 不存在 → reject({ code: 404, ... })
   *
   * @param {number} segmentId - 赛段 ID
   * @returns {Promise<object>} 赛段详情对象
   */
  getSegmentDetail: function (segmentId) {
    return request('/api/segments/' + segmentId, 'GET')
  },

  /**
   * 拉取我在某赛段的"骑完看进步"对比（task-4.5 我的记录区块用）
   *
   * 类比：就像看自己的"成绩进步表"——
   * 这次 26 分钟、上次 28 分钟、个人最好 25 分钟，让你直观感受进步。
   *
   * 后端契约（GET /api/segments/{id}/efforts/me / 需登录）：
   *   - 真返 6 字段（EffortCompareResponse schema 实证 app/segment/schemas.py:169）：
   *       current_attempt_elapsed_time / last_attempt_elapsed_time /
   *       pr_elapsed_time / current_attempt_diff_to_last（正数=变快） /
   *       current_attempt_is_pr / is_first_attempt（首次访问 = 6 字段全 None/False/True 兜底）
   *   - 排序按 Activity.started_at desc（实际骑行时间，不是入库时间）
   *   - 401 未登录 → reject / 404 segment 不存在 → reject
   *   - 没骑过该赛段（is_first_attempt=true）也 200 返兜底，前端按 pr_elapsed_time 是否 null 分三态
   *
   * @param {number} segmentId - 赛段 ID
   * @returns {Promise<object>} 6 字段对比对象
   */
  getMySegmentEffort: function (segmentId) {
    return request('/api/segments/' + segmentId + '/efforts/me', 'GET')
  },

  /**
   * 拉取赛段全网排行榜（task-4.5 全网排行榜区块用）
   *
   * 类比：就像马拉松成绩榜单——
   * 第 1 名到第 N 名按用时排序、谁创下最快、我在第几。
   *
   * 后端契约（GET /api/segments/{id}/leaderboard / 不需登录）：
   *   - query 参数：page（默认 1）/ page_size（默认 20，上限 100）/ bike_type（可选过滤）
   *   - 真返字段（LeaderboardResponse schema 实证 app/segment/schemas.py:133）：
   *       items（数组）/ total（总人数 / 即"共 N 人骑过"） / page / page_size
   *   - items[i] 含：rank / user_id / nickname / avatar_url / elapsed_time / avg_speed / avg_power / bike_type / created_at
   *   - **注意**：响应**不含** my_rank / my_elapsed_time —— 前端找 user_id == myUserId 的行即可
   *     （我的排名 + 我的用时通过 getMySegmentEffort 的 pr_elapsed_time + 在 items 里 filter 算 rank 兜底）
   *   - 404 segment 不存在 → reject
   *
   * @param {number} segmentId - 赛段 ID
   * @param {number} pageSize - 拉前 N 名（默认 10 / 上限 100）
   * @returns {Promise<object>} { items: [...], total, page, page_size }
   */
  getSegmentLeaderboard: function (segmentId, pageSize) {
    var size = pageSize || 10
    return request('/api/segments/' + segmentId + '/leaderboard?page=1&page_size=' + size, 'GET')
  },

  /**
   * 拉取我在某赛段的全部成绩（task-4.3 新接口 / task-4.4 用来算"本次"+N 项）
   *
   * 类比：像翻开自己的"赛段成绩薄"——
   * 这条赛段我骑了 5 次都长啥样、最快是哪次、每次跳到哪条骑行详情。
   *
   * 后端契约（GET /api/segments/{id}/my-efforts / 需登录）：
   *   - 真返 items 数组（MySegmentEffortItem schema 实证 app/segment/schemas.py:262）：
   *       activity_id / elapsed_time / avg_speed / avg_power / created_at / is_pr
   *   - 按 created_at 倒序（最新在前）/ 同时间 id 兜底
   *   - is_pr 只标最快那条（同秒并列时取 id 最小那条 / 跟主榜 tiebreaker 一致）
   *   - 401 未登录 → reject / 404 segment 不存在 → reject
   *
   * @param {number} segmentId - 赛段 ID
   * @returns {Promise<object>} { items: [...] }
   */
  getMySegmentEfforts: function (segmentId) {
    return request('/api/segments/' + segmentId + '/my-efforts', 'GET')
  },

  /**
   * 更新某条骑行的隐私设置（task-4.6）
   *
   * 类比：给骑行的"门禁卡"换设置——
   * 公开/私密、是否隐藏功率、是否隐藏心率。
   *
   * 后端契约（PATCH /api/activities/{id}/privacy / 需登录）：
   *   - body：{ visibility?, hide_power?, hide_heartrate? } 三字段都可选 / 不传不改
   *   - extra="forbid"：传未知字段 → 422（防 admin 越权改 distance 等）
   *   - 仅 owner 可改自己的活动（其他人 → 403）
   *   - 返回更新后的 3 字段
   *
   * @param {number} activityId
   * @param {object} partial - { visibility?, hide_power?, hide_heartrate? }
   * @returns {Promise<object>} { visibility, hide_power, hide_heartrate }
   */
  updateActivityPrivacy: function (activityId, partial) {
    return request('/api/activities/' + activityId + '/privacy', 'PATCH', partial)
  },

  /**
   * 拉取开放约骑列表。
   *
   * 后端已经统一返回人数和首图，这里只负责把筛选条件送过去。
   */
  getMeetupsList: function (params) {
    return request('/api/meetups' + buildQuery(params || {}), 'GET')
  },

  // 个人页"我的约骑"：role='created' 我发起的 / 'joined' 我加入的
  getMyMeetups: function (role, params) {
    return request('/api/meetups/mine' + buildQuery(Object.assign({ role: role }, params || {})), 'GET')
  },

  // 详情：invite_only 私圈约骑需带 token（朋友从分享链接进来才拿得到）。
  // source 是五环节埋点的来路标记（share_card/report_card）：不透传它，
  // 后端 SENSOR 行永远记 direct，上线回看"多少人从卡进来"会恒为 0（S13 集成审 Critical）。
  getMeetupDetail: function (meetupId, token, source) {
    var params = {}
    if (token) params.token = token
    if (source) params.source = source
    return request('/api/meetups/' + meetupId + buildQuery(params), 'GET')
  },

  // 已加入骑友列表（私圈约骑需带 token / 登录）
  getMeetupParticipants: function (meetupId, token) {
    return request('/api/meetups/' + meetupId + '/participants' + buildQuery(token ? { token: token } : {}), 'GET')
  },

  // 约骑照片墙：列表（public 直接看 / invite_only 需 token）/ 上传（creator multipart）/ 删除（creator 或上传者）
  getMeetupMedia: function (meetupId, token) {
    return request('/api/meetups/' + meetupId + '/media' + buildQuery(token ? { token: token } : {}), 'GET')
  },

  uploadMeetupMedia: function (meetupId, filePath) {
    return this.upload('/api/meetups/' + meetupId + '/media', filePath, 'file')
  },

  deleteMeetupMedia: function (meetupId, mediaId) {
    return request('/api/meetups/' + meetupId + '/media/' + mediaId, 'DELETE')
  },

  getMyMeetupDraft: function () {
    return request('/api/meetups/my-draft', 'GET')
  },

  createMeetup: function (data) {
    return request('/api/meetups', 'POST', data)
  },

  updateMeetup: function (meetupId, data) {
    return request('/api/meetups/' + meetupId, 'PATCH', data)
  },

  publishMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId + '/publish', 'POST', {})
  },

  cancelMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId + '/cancel', 'POST', {})
  },

  deleteMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId, 'DELETE')
  },

  getMeetupFavoritePlaces: function () {
    return request('/api/meetups/favorite-places', 'GET')
  },

  saveMeetupFavoritePlace: function (data) {
    return request('/api/meetups/favorite-places', 'POST', data)
  },

  deleteMeetupFavoritePlace: function (placeId) {
    return request('/api/meetups/favorite-places/' + placeId, 'DELETE')
  },

  // 集合点实时联想：边输边搜返回最多 8 条候选（替代旧单结果 place-search）
  getMeetupPlaceSuggestions: function (keyword, region) {
    return request('/api/meetups/place-suggestions' + buildQuery({
      keyword: keyword,
      region: region || '太原',
    }), 'GET')
  },

  joinMeetup: function (meetupId, token) {
    return request('/api/meetups/' + meetupId + '/join' + buildQuery(token ? { token: token } : {}), 'POST', {})
  },

  leaveMeetup: function (meetupId) {
    return request('/api/meetups/' + meetupId + '/leave', 'DELETE')
  },

  getRouteBooksList: function (params) {
    return request('/api/route-books' + buildQuery(params || {}), 'GET')
  },

  // 单条路书详情（草稿恢复时按 route_book_id 重画地图预览）
  getRouteBookDetail: function (routeBookId) {
    return request('/api/route-books/' + routeBookId, 'GET')
  },

  getRouteBookActivityCandidates: function () {
    return request('/api/route-books/activity-candidates', 'GET')
  },

  createRouteBookFromActivity: function (name, activityId) {
    return requestForm('/api/route-books', 'POST', {
      name: name,
      source: 'activity_derived',
      source_activity_id: activityId,
    })
  },

  createRouteBookFromTencentDirection: function (payload) {
    return request('/api/route-books/tencent-direction', 'POST', payload)
  },

  createRouteBookFromManualDrawn: function (payload) {
    return request('/api/route-books/manual-drawn', 'POST', payload)
  },

  createRouteExport: function (routeBookId, format, targetPlatform) {
    return request('/api/route-books/' + routeBookId + '/exports', 'POST', {
      format: format,
      target_platform: targetPlatform || 'generic',
    })
  },

  downloadRouteExport: function (downloadUrl, fileName) {
    return downloadFile(downloadUrl, fileName)
  },

  shareRouteExportFile: function (filePath, fileName) {
    return shareFile(filePath, fileName)
  },

  resolveUrl: function (url) {
    return absoluteUrl(url)
  },

  copyText: function (text) {
    return copyText(text)
  },

  /**
   * 上传文件专用（GPX 上传走这个，不走普通 JSON 请求）
   *
   * @param {string} url - 上传接口路径
   * @param {string} filePath - 本地文件临时路径
   * @param {string} name - 后端接收的字段名
   * @returns {Promise}
   */
  upload: function (url, filePath, name) {
    var app = getAppSafe()
    var baseUrl = (app && app.globalData.baseUrl) || BASE_URL
    var token = app && app.globalData.token
    if (name === undefined) name = 'file'

    return new Promise(function (resolve, reject) {
      wx.uploadFile({
        url: baseUrl + url,
        filePath: filePath,
        name: name,
        header: {
          'Authorization': token ? 'Bearer ' + token : '',
        },
        success: function (res) {
          // wx.uploadFile 返回的 data 是字符串，需手动 JSON.parse。但响应可能不是 JSON
          // （反代返回 HTML 错误页 / 502 / 空 body）。裸 parse 抛错会让这个 Promise 既不 resolve
          // 也不 reject → 永远 pending → 外层 Promise.all 卡死 → 上传 loading 永不关闭。必须包 try/catch
          // 兜底，保证 Promise 一定 settle。
          var data = null
          try {
            data = JSON.parse(res.data)
          } catch (e) {
            data = null
          }
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(data)
          } else {
            reject({
              code: res.statusCode,
              message: (data && data.detail) || '上传失败',
            })
          }
        },
        fail: function () {
          reject({ code: -1, message: '上传失败，请检查网络' })
        },
      })
    })
  },
}
