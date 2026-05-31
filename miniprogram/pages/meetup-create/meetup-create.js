const api = require('../../utils/api')

function formatDistance(value) {
  if (value === undefined || value === null) return '--'
  return Number(value).toFixed(1) + ' km'
}

function nowIsoOffset(hours) {
  var date = new Date(Date.now() + hours * 60 * 60 * 1000)
  return date.toISOString()
}

Page({
  data: {
    steps: ['route', 'details', 'publish'],
    currentStep: 'route',
    selectedSegmentId: null,
    selectedRouteBookId: null,
    selectedActivityId: null,
    selectedRouteName: '',
    segments: [],
    routeBooks: [],
    activities: [],
    form: {
      start_time: nowIsoOffset(24),
      estimated_end_time: nowIsoOffset(27),
      meeting_point: '',
      pace_level: 'cruise',
      max_participants: 6,
      description: '',
    },
    paceOptions: [
      { value: 'relaxed', label: '休闲' },
      { value: 'cruise', label: '巡航' },
      { value: 'training', label: '训练' },
      { value: 'race', label: '强度' },
    ],
    submitting: false,
  },

  onLoad: function () {
    this.loadRoutes()
  },

  loadRoutes: function () {
    var that = this
    Promise.all([
      api.getSegmentsList({ page: 1, page_size: 20 }),
      api.getRouteBooksList({ mine: 1 }),
      api.getRouteBookActivityCandidates(),
    ])
      .then(function (results) {
        that.setData({
          segments: that.decorateItems(results[0].items || [], 'segment'),
          routeBooks: that.decorateItems(results[1].items || [], 'route_book'),
          activities: that.decorateItems(results[2].items || [], 'activity'),
        })
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '路线加载失败', icon: 'none' })
      })
  },

  decorateItems: function (items, type) {
    return items.map(function (item) {
      var name = item.name || item.title || '未命名路线'
      var climb = item.climb !== undefined ? item.climb : item.elevation_gain
      return Object.assign({}, item, {
        type: type,
        displayName: name,
        displayMeta: formatDistance(item.distance) + ' · 爬升 ' + (climb === undefined || climb === null ? '--' : Math.round(Number(climb)) + ' m'),
      })
    })
  },

  selectRoute: function (event) {
    var type = event.currentTarget.dataset.type
    var id = Number(event.currentTarget.dataset.id)
    var name = event.currentTarget.dataset.name
    this.setData({
      selectedSegmentId: type === 'segment' ? id : null,
      selectedRouteBookId: type === 'route_book' ? id : null,
      selectedActivityId: type === 'activity' ? id : null,
      selectedRouteName: name,
    })
  },

  nextStep: function () {
    if (this.data.currentStep === 'route') {
      if (!this.data.selectedSegmentId && !this.data.selectedRouteBookId && !this.data.selectedActivityId) {
        wx.showToast({ title: '先选路线', icon: 'none' })
        return
      }
      this.setData({ currentStep: 'details' })
      return
    }
    if (this.data.currentStep === 'details') {
      if (!this.data.form.meeting_point) {
        wx.showToast({ title: '填写集合点', icon: 'none' })
        return
      }
      this.setData({ currentStep: 'publish' })
    }
  },

  prevStep: function () {
    if (this.data.currentStep === 'publish') {
      this.setData({ currentStep: 'details' })
    } else if (this.data.currentStep === 'details') {
      this.setData({ currentStep: 'route' })
    }
  },

  updateField: function (event) {
    var field = event.currentTarget.dataset.field
    var value = event.detail.value
    var key = 'form.' + field
    this.setData({ [key]: value })
  },

  onPaceChange: function (event) {
    var index = Number(event.detail.value)
    this.setData({ 'form.pace_level': this.data.paceOptions[index].value })
  },

  createOrUpdateDraft: function (payload) {
    return api.createMeetup(payload)
      .catch(function (err) {
        var detail = err && err.message
        if (err && err.code === 409 && detail && detail.code === 'draft_exists' && detail.existing_draft_id) {
          return api.updateMeetup(detail.existing_draft_id, payload)
        }
        return Promise.reject(err)
      })
  },

  onPublish: function () {
    var that = this
    if (this.data.submitting) return
    this.setData({ submitting: true })

    this.resolveRouteBookId()
      .then(function (routeBookId) {
        var payload = Object.assign({}, that.data.form, {
          segment_id: that.data.selectedSegmentId || null,
          route_book_id: routeBookId || that.data.selectedRouteBookId || null,
          max_participants: Number(that.data.form.max_participants),
        })
        return that.createOrUpdateDraft(payload)
      })
      .then(function (draft) {
        return api.publishMeetup(draft.id)
      })
      .then(function (meetup) {
        wx.redirectTo({ url: '/pages/meetup-detail/meetup-detail?id=' + meetup.id })
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '发布失败', icon: 'none' })
      })
      .finally(function () {
        that.setData({ submitting: false })
      })
  },

  resolveRouteBookId: function () {
    if (!this.data.selectedActivityId) {
      return Promise.resolve(null)
    }
    var name = this.data.selectedRouteName || '我的路线'
    return api.createRouteBookFromActivity(name, this.data.selectedActivityId)
      .then(function (routeBook) {
        return routeBook.id
      })
  },
})
