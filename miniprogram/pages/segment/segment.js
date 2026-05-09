/**
 * 赛段详情页 — 看某条赛段的全貌（task-4.5 / 现为占位空架子）
 *
 * 这个文件干什么的：
 *   接收 query.id（segment_id）/ 暂时只展示 ID / 后续 step 2-7 实现 4 区块完整逻辑。
 *
 *   类比：现在像一张"暂未开张"的店面招牌——
 *   告诉路过的人这里是什么店（赛段 #X）/ 但还没开门营业（详情功能开发中）。
 *
 * 操作注意事项：
 *   1. 本页 NOT 在 tabBar / 通过 navigateTo 进入
 *   2. 完整实施在 task-4.5 step 2-7（API 调用 / 4 区块 wxml / canvas 海拔图 / 三 fetch 并行）
 *   3. 当前仅注册路由 + 接收 query — 让 task-4.4 explore tab 跳转有目标，不死链接
 *
 * 输入输出：
 *   输入：query.id（赛段 ID / parseInt 后必须 > 0）
 *   输出：占位 view（开发中提示）
 */

Page({
  data: {
    segmentId: 0,
  },

  onLoad(options) {
    const segmentId = parseInt(options && options.id, 10)
    if (!segmentId || isNaN(segmentId) || segmentId <= 0) {
      wx.showToast({ title: '无效赛段', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 1500)
      return
    }
    this.setData({ segmentId })
  },
})
