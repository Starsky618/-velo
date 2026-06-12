const api = require('../../utils/api')
const { wgs84ToGcj02 } = require('../../utils/coords')
const DEFAULT_CENTER = { latitude: 37.8706, longitude: 112.5489 }

function normalizeKind(kind) {
  if (kind === 'meeting') return 'meeting'
  return kind === 'end' ? 'end' : 'start'
}

function finiteNumber(value, fallback) {
  var n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function safeDecode(value) {
  if (!value) return ''
  try {
    return decodeURIComponent(value)
  } catch (err) {
    return ''
  }
}

function mapPointFromSearchPlace(place, fallbackLat, fallbackLon) {
  // 腾讯地点搜索在后端返回 WGS-84；微信地图显示前要换成 GCJ-02，
  // 否则用户会看到集合点偏到旁边街区。
  var sourceLat = finiteNumber(place.latitude, fallbackLat)
  var sourceLon = finiteNumber(place.longitude, fallbackLon)
  var gcj = wgs84ToGcj02(sourceLat, sourceLon)
  return Object.assign({}, place, {
    latitude: gcj[0],
    longitude: gcj[1],
    sourceLatitude: sourceLat,
    sourceLongitude: sourceLon,
    coordinate_system: 'wgs84',
  })
}

Page({
  data: {
    kind: 'start',
    title: '选择起点',
    confirmText: '确认起点',
    name: '',
    searchKeyword: '',
    selectedSearchPlace: null,
    placeSearchResults: [],
    latitude: DEFAULT_CENTER.latitude,
    longitude: DEFAULT_CENTER.longitude,
  },

  onLoad: function (options) {
    var kind = normalizeKind(options && options.kind)
    var title = kind === 'meeting' ? '选择集合点' : (kind === 'start' ? '选择起点' : '选择终点')
    var confirmText = kind === 'meeting' ? '确认集合点' : (kind === 'start' ? '确认起点' : '确认终点')
    var rawLat = finiteNumber(options && options.latitude, DEFAULT_CENTER.latitude)
    var rawLon = finiteNumber(options && options.longitude, DEFAULT_CENTER.longitude)
    var coordinateSystem = options && options.coordinate_system === 'wgs84' ? 'wgs84' : 'gcj02'
    var display = kind === 'meeting' && coordinateSystem === 'wgs84' ? wgs84ToGcj02(rawLat, rawLon) : [rawLat, rawLon]
    this.setData({
      kind: kind,
      title: title,
      confirmText: confirmText,
      name: safeDecode(options && options.name),
      // 回显已选地点时搜索框同步显示名字（输入框是页面上唯一的文字位）
      searchKeyword: safeDecode(options && options.name),
      selectedSearchPlace: kind === 'meeting' && coordinateSystem === 'wgs84' ? {
        title: safeDecode(options && options.name),
        address: safeDecode(options && options.address),
        latitude: display[0],
        longitude: display[1],
        sourceLatitude: rawLat,
        sourceLongitude: rawLon,
        coordinate_system: 'wgs84',
      } : null,
      latitude: display[0],
      longitude: display[1],
    })
    wx.setNavigationBarTitle({ title: title })
  },

  onReady: function () {
    this.mapContext = wx.createMapContext('picker-map')
  },

  onRegionChange: function (event) {
    if (!event || event.type !== 'end') return
    // 用户拖动地图 = 放弃刚才点选的搜索结果（确认时以地图中心针尖为准）。
    // ⚠ 不许在这里读中心 / setData 坐标——把中心写回 <map> 会形成
    // "拖动 → 回写 → 地图再动"的反馈循环，正是真机拖图卡顿的根源；
    // 地图中心只在用户点"确认"那一刻读一次（selectMapPoint → refreshCenter）。
    if (event.causedBy !== 'update' && this.data.selectedSearchPlace) {
      this.setData({ selectedSearchPlace: null })
    }
  },

  // 实时联想：边输边搜（350ms 防抖 + 至少 2 个字 + 过期响应丢弃），像高德那样出一列候选
  onSearchKeywordInput: function (event) {
    var that = this
    var keyword = event.detail.value
    // 每次输入先作废所有在途请求（含"清空输入"场景——否则旧响应回来会把候选塞回去）
    this._suggestSeq = (this._suggestSeq || 0) + 1
    this.setData({ searchKeyword: keyword, selectedSearchPlace: null })
    if (this._suggestTimer) clearTimeout(this._suggestTimer)
    var trimmed = String(keyword || '').trim()
    if (trimmed.length < 2) {
      if (this.data.placeSearchResults.length) this.setData({ placeSearchResults: [] })
      return
    }
    this._suggestTimer = setTimeout(function () { that.fetchSuggestions(trimmed) }, 350)
  },

  fetchSuggestions: function (keyword) {
    var that = this
    // 序号守卫：发出时记下当前序号，响应回来只认"还是最新一发"的结果
    var seq = this._suggestSeq || 0
    api.getMeetupPlaceSuggestions(keyword, '太原').then(function (places) {
      if (seq !== that._suggestSeq) return
      that.setData({ placeSearchResults: places || [] })
    }).catch(function () {
      if (seq !== that._suggestSeq) return
      that.setData({ placeSearchResults: [] })
    })
  },

  onHide: function () {
    // 离页（含前进到别的页）作废在途联想，回来不会闪旧候选
    this._suggestSeq = (this._suggestSeq || 0) + 1
  },

  onUnload: function () {
    if (this._suggestTimer) clearTimeout(this._suggestTimer)
    this._suggestSeq = (this._suggestSeq || 0) + 1
  },

  onTapSearchResult: function (event) {
    var index = Number(event.currentTarget.dataset.index)
    var place = this.data.placeSearchResults[index]
    if (!place) return
    var mapPlace = mapPointFromSearchPlace(place, this.data.latitude, this.data.longitude)
    this.setData({
      name: mapPlace.title || mapPlace.keyword || this.data.name,
      searchKeyword: mapPlace.title || this.data.searchKeyword,
      selectedSearchPlace: mapPlace,
      latitude: mapPlace.latitude,
      longitude: mapPlace.longitude,
      placeSearchResults: [],
    })
  },

  refreshCenter: function (done) {
    var that = this
    var context = this.mapContext || wx.createMapContext('picker-map')
    context.getCenterLocation({
      success: function (res) {
        var point = {
          latitude: finiteNumber(res.latitude, that.data.latitude),
          longitude: finiteNumber(res.longitude, that.data.longitude),
        }
        that.setData(point)
        if (done) done(point)
      },
      fail: function () {
        var fallback = {
          latitude: that.data.latitude,
          longitude: that.data.longitude,
        }
        if (done) done(fallback)
      },
    })
  },

  selectMapPoint: function () {
    var that = this
    this.refreshCenter(function (center) {
      var searchPlace = that.data.selectedSearchPlace
      var picked
      if (searchPlace && that.data.kind === 'meeting') {
        // 集合点入库链路吃 WGS-84 源坐标（后端按 coordinate_system 字段识别）
        picked = {
          latitude: finiteNumber(searchPlace.sourceLatitude, center.latitude),
          longitude: finiteNumber(searchPlace.sourceLongitude, center.longitude),
          address: searchPlace.address || '',
          coordinate_system: 'wgs84',
        }
      } else if (searchPlace) {
        // ⚠ 起点/终点喂给腾讯路线规划，它只吃 GCJ-02——必须用展示坐标，
        // 传 WGS 源坐标会让整条生成路线整体偏移一两百米（Codex 异源审抓的 Critical）
        picked = {
          latitude: finiteNumber(searchPlace.latitude, center.latitude),
          longitude: finiteNumber(searchPlace.longitude, center.longitude),
          address: searchPlace.address || '',
          coordinate_system: 'gcj02',
        }
      } else {
        picked = {
          latitude: center.latitude,
          longitude: center.longitude,
          address: '',
          coordinate_system: 'gcj02',
        }
      }
      var app = getApp()
      if (app && app.globalData) {
        app.globalData.pendingMapPoint = {
          kind: that.data.kind,
          latitude: picked.latitude,
          longitude: picked.longitude,
          address: picked.address,
          coordinate_system: picked.coordinate_system,
          name: that.data.name || (that.data.kind === 'meeting' ? '集合点' : (that.data.kind === 'start' ? '路线起点' : '路线终点')),
        }
      }
      wx.navigateBack()
    })
  },

  onTapCancel: function () {
    wx.navigateBack()
  },
})
