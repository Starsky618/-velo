(function () {
  'use strict'

  const rideCount = document.getElementById('ride-count')
  const layerButton = document.getElementById('layer-button')
  const layerPanel = document.getElementById('layer-panel')
  const layerDone = document.getElementById('layer-done')
  const yearOptions = document.getElementById('year-options')
  const fitLocal = document.getElementById('fit-local')
  const fitAll = document.getElementById('fit-all')
  const pageState = document.getElementById('page-state')

  let map = null
  let fallbackLayer = null
  let detailLayer = null
  let manifest = null
  let selectedYear = null
  let occupied = new Map()
  let requestSerial = 0

  function yearQuery(year) {
    return year === null ? '' : '?year=' + encodeURIComponent(year)
  }

  function key(x, y) {
    return x + ':' + y
  }

  function buildOccupied(source) {
    const result = new Map()
    Object.keys(source.tiles || {}).forEach(function (zoom) {
      result.set(Number(zoom), new Set(source.tiles[zoom].map(function (tile) {
        return key(tile[0], tile[1])
      })))
    })
    return result
  }

  function hasTile(sourceManifest, coverage, zoom, x, y) {
    const tiles = coverage.get(Number(zoom))
    if (tiles && tiles.has(key(x, y))) return true
    const parentZoom = Number(sourceManifest.coverage_max_zoom)
    if (
      sourceManifest.coverage_mode !== 'parent' ||
      !Number.isFinite(parentZoom) ||
      zoom <= parentZoom
    ) return false
    const parents = coverage.get(parentZoom)
    if (!parents) return false
    const scale = Math.pow(2, zoom - parentZoom)
    return parents.has(key(Math.floor(x / scale), Math.floor(y / scale)))
  }

  function tileUrl(layer, x, y, zoom, sourceManifest, sourceYear, coverage) {
    const path = !hasTile(sourceManifest, coverage, zoom, x, y)
      ? '/heatmap/blank.png'
      : '/heatmap/' + layer + '-tiles/' + encodeURIComponent(sourceManifest.cache_version) +
        '/' + zoom + '/' + x + '/' + y + '.png' + yearQuery(sourceYear)
    // 腾讯 GL SDK 在 blob worker 里请求自定义瓦片；相对路径在 blob 上没有合法 origin。
    return new URL(path, window.location.href).href
  }

  function removeLayers(layers) {
    layers.forEach(function (layer) {
      if (!layer) return
      if (typeof layer.setMap === 'function') layer.setMap(null)
      else if (typeof layer.setVisible === 'function') layer.setVisible(false)
    })
  }

  function clearLayers() {
    removeLayers([fallbackLayer, detailLayer])
    fallbackLayer = null
    detailLayer = null
  }

  function centerTile(zoom) {
    const center = map.getCenter()
    const latitude = typeof center.getLat === 'function' ? center.getLat() : center.lat
    const longitude = typeof center.getLng === 'function' ? center.getLng() : center.lng
    const count = Math.pow(2, zoom)
    const limitedLatitude = Math.max(-85.05112878, Math.min(85.05112878, latitude))
    const x = Math.floor((longitude + 180) / 360 * count)
    const radians = limitedLatitude * Math.PI / 180
    const y = Math.floor(
      (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) /
      2 * count
    )
    return { x: x, y: y }
  }

  function preloadVisibleFallback(sourceManifest, sourceYear, coverage) {
    const zoom = Math.max(
      sourceManifest.min_zoom,
      Math.min(sourceManifest.max_zoom, Math.round(map.getZoom()))
    )
    const center = centerTile(zoom)
    const urls = []
    for (let offsetX = -2; offsetX <= 2; offsetX += 1) {
      for (let offsetY = -2; offsetY <= 2; offsetY += 1) {
        const x = center.x + offsetX
        const y = center.y + offsetY
        if (!hasTile(sourceManifest, coverage, zoom, x, y)) continue
        urls.push(tileUrl(
          'fallback', x, y, zoom, sourceManifest, sourceYear, coverage
        ))
      }
    }
    if (!urls.length) return Promise.resolve(true)
    return Promise.all(urls.map(function (url) {
      return new Promise(function (resolve) {
        const image = new Image()
        const timeout = window.setTimeout(function () { resolve(false) }, 5000)
        image.onload = function () {
          window.clearTimeout(timeout)
          resolve(true)
        }
        image.onerror = function () {
          window.clearTimeout(timeout)
          resolve(false)
        }
        image.src = url
      })
    })).then(function (results) {
      return results.every(Boolean)
    })
  }

  function buildLayers() {
    const previousLayers = [fallbackLayer, detailLayer]
    const sourceManifest = manifest
    const sourceYear = selectedYear
    const coverage = occupied
    fallbackLayer = new TMap.ImageTileLayer({
      map: map,
      minZoom: sourceManifest.min_zoom,
      maxZoom: sourceManifest.max_zoom,
      tileSize: 256,
      imageSize: 512,
      zIndex: 19,
      getTileUrl: function (x, y, zoom) {
        return tileUrl('fallback', x, y, zoom, sourceManifest, sourceYear, coverage)
      },
    })
    detailLayer = new TMap.ImageTileLayer({
      map: map,
      minZoom: Math.min(
        sourceManifest.max_zoom,
        sourceManifest.fallback_max_zoom + 1
      ),
      maxZoom: sourceManifest.max_zoom,
      tileSize: 256,
      imageSize: 512,
      zIndex: 20,
      getTileUrl: function (x, y, zoom) {
        return tileUrl('live', x, y, zoom, sourceManifest, sourceYear, coverage)
      },
    })
    // 当前视口 fallback 已预取成功；给 SDK 一个短帧窗口贴图后再移除旧层。
    window.setTimeout(function () {
      removeLayers(previousLayers)
    }, 500)
  }

  function boundsFor(points) {
    if (!Array.isArray(points) || points.length !== 2) return null
    return new TMap.LatLngBounds(
      new TMap.LatLng(points[0][1], points[0][0]),
      new TMap.LatLng(points[1][1], points[1][0])
    )
  }

  function fit(points, fallbackZoom) {
    const bounds = boundsFor(points)
    if (bounds && typeof map.fitBounds === 'function') {
      // 按钮切换是视图模式切换，不是路线播放；禁用跨十几个 zoom 的相机动画，
      // 避免中间级别瓦片排队并让用户误以为又在重新加载。
      map.fitBounds(bounds, { padding: 72, duration: 0 })
      return
    }
    map.easeTo({
      center: new TMap.LatLng(manifest.center.latitude, manifest.center.longitude),
      zoom: fallbackZoom,
    })
  }

  function setFitMode(mode) {
    fitLocal.classList.toggle('active', mode === 'local')
    fitAll.classList.toggle('active', mode === 'all')
    fit(mode === 'local' ? manifest.focus_points : manifest.all_points, mode === 'local' ? 13 : 10)
  }

  function renderYearOptions() {
    yearOptions.replaceChildren()
    const options = [{ value: null, label: '全部' }].concat(
      (manifest.available_years || []).map(function (year) {
        return { value: Number(year), label: String(year) }
      })
    )
    options.forEach(function (option) {
      const button = document.createElement('button')
      button.type = 'button'
      button.textContent = option.label
      button.className = option.value === selectedYear ? 'selected' : ''
      button.addEventListener('click', function () {
        if (option.value === selectedYear) return
        loadManifest(option.value).catch(showLoadError)
      })
      yearOptions.appendChild(button)
    })
  }

  function updateMeta() {
    rideCount.textContent = manifest.activity_count + ' 次骑行 · ' +
      (selectedYear === null ? '全部年份' : selectedYear + ' 年')
  }

  async function loadManifest(year) {
    const serial = ++requestSerial
    pageState.hidden = false
    pageState.textContent = '正在切换热图…'
    const query = year === null ? '' : '?year=' + encodeURIComponent(year)
    const response = await fetch('/heatmap/manifest' + query, {
      credentials: 'same-origin',
      cache: 'no-store',
    })
    if (response.status === 401) throw new Error('登录已过期，请返回小程序重新打开')
    if (!response.ok) throw new Error('热图暂时不可用，请稍后重试')
    const nextManifest = await response.json()
    if (serial !== requestSerial) return
    const nextOccupied = buildOccupied(nextManifest)

    if (!nextManifest.center) {
      selectedYear = year
      manifest = nextManifest
      occupied = nextOccupied
      updateMeta()
      renderYearOptions()
      clearLayers()
      pageState.hidden = false
      pageState.textContent = selectedYear === null ? '还没有可显示的骑行轨迹' : '这个年份还没有骑行轨迹'
      return
    }

    if (!map) {
      map = new TMap.Map(document.getElementById('map'), {
        center: new TMap.LatLng(
          nextManifest.center.latitude,
          nextManifest.center.longitude
        ),
        zoom: nextManifest.initial_zoom,
        minZoom: nextManifest.min_zoom,
        maxZoom: nextManifest.max_zoom,
        pitch: 0,
        rotation: 0,
      })
    }
    const hasPreviousLayers = !!(fallbackLayer || detailLayer)
    const ready = !hasPreviousLayers || await preloadVisibleFallback(
      nextManifest, year, nextOccupied
    )
    if (serial !== requestSerial) return
    if (!ready) throw new Error('新热图暂时未加载完成，已保留当前轨迹，请重试')
    selectedYear = year
    manifest = nextManifest
    occupied = nextOccupied
    updateMeta()
    renderYearOptions()
    buildLayers()
    pageState.hidden = true
    window.__veloHeatmap = {
      map: map,
      manifest: manifest,
      fallbackLayer: fallbackLayer,
      detailLayer: detailLayer,
    }
  }

  function showLoadError(error) {
    console.error(error)
    pageState.hidden = false
    pageState.textContent = error && error.message ? error.message : '热图加载失败'
  }

  layerButton.addEventListener('click', function () {
    layerPanel.hidden = !layerPanel.hidden
  })
  layerDone.addEventListener('click', function () { layerPanel.hidden = true })
  fitLocal.addEventListener('click', function () { setFitMode('local') })
  fitAll.addEventListener('click', function () { setFitMode('all') })

  if (!window.TMap) {
    pageState.textContent = '腾讯地图加载失败，请检查网络后重试'
    return
  }
  loadManifest(null).catch(showLoadError)
})()
