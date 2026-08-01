/**
 * 热图协议能力只在当前小程序运行会话内记忆。
 *
 * 新前端首次尝试 meta 协议；旧后端返回 422 后，卡片与全屏页共享这一结论，
 * 后续直接走 card/full + viewport，避免每次进页面都制造一次无效请求和错误日志。
 */

var metaUnsupported = false

function shouldTryMeta() {
  return !metaUnsupported
}

function markMetaUnsupported() {
  metaUnsupported = true
}

module.exports = {
  shouldTryMeta: shouldTryMeta,
  markMetaUnsupported: markMetaUnsupported,
}
