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
var BASE_URL = 'http://114.132.190.245'

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
          // 透传后端的真实错误信息，方便调试
          var detail = (res.data && res.data.detail) || '登录已过期，请重新登录'
          reject({ code: 401, message: detail })
          return
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          reject({
            code: res.statusCode,
            message: (res.data && res.data.detail) || '请求失败',
          })
        }
      },
      fail: function () {
        reject({ code: -1, message: '网络连接失败，请检查网络' })
      },
    })
  })
}

// 快捷方法：api.get('/path')、api.post('/path', data)
module.exports = {
  get: function (url) { return request(url, 'GET') },
  post: function (url, data) { return request(url, 'POST', data) },
  put: function (url, data) { return request(url, 'PUT', data) },
  del: function (url) { return request(url, 'DELETE') },

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
          if (res.statusCode >= 200 && res.statusCode < 300) {
            // wx.uploadFile 返回的 data 是字符串，需要手动解析
            resolve(JSON.parse(res.data))
          } else {
            var errData = JSON.parse(res.data || '{}')
            reject({
              code: res.statusCode,
              message: errData.detail || '上传失败',
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
