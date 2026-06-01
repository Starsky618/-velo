const api = require('../../utils/api')

// 以下格式化函数和 meetups-list 保持一致：缺失返回空串（不显示 "-" 占位符）
function formatDistance(value) {
  if (value === undefined || value === null) return ''
  return Number(value).toFixed(1) + ' km'
}

function formatClimb(value) {
  if (value === undefined || value === null) return ''
  return Math.round(Number(value)) + ' m'
}

function formatTime(value) {
  if (!value) return '待定'
  var date = new Date(value)
  if (isNaN(date.getTime())) return value
  var month = date.getMonth() + 1
  var day = date.getDate()
  var hour = String(date.getHours()).padStart(2, '0')
  var minute = String(date.getMinutes()).padStart(2, '0')
  return month + '月' + day + '日 ' + hour + ':' + minute
}

function paceText(value) {
  var map = { relaxed: '休闲', cruise: '巡航', training: '训练', race: '强度' }
  return map[value] || value || ''
}

// "我发起的"含草稿/已取消，需要在卡片上标出状态；"我加入的"基本是 OPEN/COMPLETED
function statusText(value) {
  var map = { DRAFT: '草稿', OPEN: '开放中', CANCELLED: '已取消', COMPLETED: '已完成' }
  return map[value] || value || ''
}

function decorate(meetup) {
  var count = meetup.participants_count || 0
  var max = meetup.max_participants || 0
  return Object.assign({}, meetup, {
    timeText: formatTime(meetup.start_time),
    distanceText: formatDistance(meetup.snapshot_distance),
    climbText: formatClimb(meetup.snapshot_climb),
    paceText: paceText(meetup.pace_level),
    seatsText: count + '/' + max,
    statusText: statusText(meetup.status),
  })
}

Page({
  data: {
    role: 'created', // created=我发起的 / joined=我加入的
    meetups: [],
    loading: false,
  },

  onShow: function () {
    // 每次进页面/切回都刷新（取消、加入等操作后回来能看到最新状态）
    this.load(this.data.role)
  },

  onPullDownRefresh: function () {
    var that = this
    this.load(this.data.role, function () {
      wx.stopPullDownRefresh()
    })
  },

  onTapTab: function (event) {
    var role = event.currentTarget.dataset.role
    if (role === this.data.role) return
    this.setData({ role: role, meetups: [] })
    this.load(role)
  },

  load: function (role, done) {
    var that = this
    // 不加 loading 守卫拦请求：否则请求未回时切 tab，新 tab 的请求会被吞掉 →
    // 旧请求回来又因 role 不匹配被丢弃 → 新 tab 永久空白且无法自恢复（下拉刷新同理被吞）。
    // 正确姿势是"总是发请求 + then 里用 role 检查丢弃过期结果"。
    this.setData({ loading: true })
    api.getMyMeetups(role, { page: 1, page_size: 50 })
      .then(function (res) {
        // 防竞态：tab 在请求期间被切走时丢弃过期结果
        if (that.data.role !== role) return
        that.setData({ meetups: (res.items || []).map(decorate) })
      })
      .catch(function (err) {
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
      })
      .finally(function () {
        // done()（停下拉刷新圈）必须无条件先调：否则下拉刷新期间切 tab，过期请求被下面的 guard
        // 提前 return，stopPullDownRefresh 永不执行 → 刷新圈一直转（Codex 复查抓的回归）。
        if (done) done()
        // loading 才是只有"当前 role"才该动的状态：过期请求别把新 tab 的 loading 提前置 false 闪空态。
        if (that.data.role !== role) return
        that.setData({ loading: false })
      })
  },

  onTapMeetup: function (event) {
    wx.navigateTo({ url: '/pages/meetup-detail/meetup-detail?id=' + event.currentTarget.dataset.id })
  },
})
