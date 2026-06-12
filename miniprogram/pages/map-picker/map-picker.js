const api = require('../../utils/api')
const { wgs84ToGcj02 } = require('../../utils/coords')
const mapTheme = require('../../utils/map-theme')

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
  data: Object.assign({}, mapTheme.getPaperMapData(), {
    kind: 'start',
    title: '选择起点',
    confirmText: '确认起点',
    name: '',
    searchKeyword: '',
    searchingPlace: false,
    selectedSearchPlace: null,
    placeSearchResults: [],
    latitude: DEFAULT_CENTER.latitude,
    longitude: DEFAULT_CENTER.longitude,
  }),

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
    if (event.causedBy !== 'update') {
      this.setData({ selectedSearchPlace: null })
    }
    this.refreshCenter()
  },

  onNameInput: function (event) {
    this.setData({ name: event.detail.value })
  },

  onSearchKeywordInput: function (event) {
    this.setData({ searchKeyword: event.detail.value, selectedSearchPlace: null })
  },

  onTapSearchPlace: function () {
    if (this.data.kind !== 'meeting') return
    var that = this
    var keyword = String(this.data.searchKeyword || this.data.name || '').trim()
    if (!keyword) {
      wx.showToast({ title: '输入地点关键词', icon: 'none' })
      return
    }
    if (this.data.searchingPlace) return
    this.setData({ searchingPlace: true, selectedSearchPlace: null })
    api.searchMeetupPlace(keyword, '太原').then(function (place) {
      if (!place) {
        that.setData({ placeSearchResults: [] })
        wx.showToast({ title: '没有找到地点', icon: 'none' })
        return
      }
      that.setData({ placeSearchResults: [place] })
    }).catch(function (err) {
      wx.showToast({ title: (err && err.message) || '搜索失败', icon: 'none' })
    }).finally(function () {
      that.setData({ searchingPlace: false })
    })
  },

  onTapSearchResult: function (event) {
    var index = Number(event.currentTarget.dataset.index)
    var place = this.data.placeSearchResults[index]
    if (!place) return
    var mapPlace = mapPointFromSearchPlace(place, this.data.latitude, this.data.longitude)
    this.setData({
      name: mapPlace.title || mapPlace.keyword || this.data.name,
      selectedSearchPlace: mapPlace,
      latitude: mapPlace.latitude,
      longitude: mapPlace.longitude,
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
      var picked = searchPlace ? {
        latitude: finiteNumber(searchPlace.sourceLatitude, center.latitude),
        longitude: finiteNumber(searchPlace.sourceLongitude, center.longitude),
        address: searchPlace.address || '',
        coordinate_system: 'wgs84',
      } : {
        latitude: center.latitude,
        longitude: center.longitude,
        address: '',
        coordinate_system: 'gcj02',
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
