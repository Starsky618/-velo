(function () {
  'use strict'

  const statusNode = document.getElementById('status')
  const metricsNode = document.getElementById('metrics')
  const toggleButton = document.getElementById('toggle')
  const resetButton = document.getElementById('reset')

  let map = null
  let fallbackHeatLayer = null
  let detailHeatLayer = null
  let manifest = null
  let fallbackTileRequests = 0
  let detailTileRequests = 0
  let heatVisible = true
  const frameDurations = []
  let previousFrameAt = performance.now()

  function setStatus(message) {
    statusNode.textContent = message
  }

  function percentile(values, ratio) {
    if (!values.length) return 0
    const sorted = values.slice().sort(function (left, right) { return left - right })
    return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))]
  }

  function sampleFrames(now) {
    const duration = now - previousFrameAt
    previousFrameAt = now
    if (duration < 1000) frameDurations.push(duration)
    if (frameDurations.length > 300) frameDurations.shift()
    requestAnimationFrame(sampleFrames)
  }

  function updateMetrics() {
    const p50 = percentile(frameDurations, 0.5)
    const p95 = percentile(frameDurations, 0.95)
    const slowFrames = frameDurations.filter(function (duration) { return duration > 34 }).length
    metricsNode.textContent = [
      '底图 ' + fallbackTileRequests,
      '细节 ' + detailTileRequests,
      '帧间隔 P50 ' + p50.toFixed(1) + 'ms',
      'P95 ' + p95.toFixed(1) + 'ms',
      '>34ms ' + slowFrames,
    ].join(' · ')
  }

  function fallbackTileUrl(x, y, zoom) {
    fallbackTileRequests += 1
    return new URL(
      './fallback-tiles/' + encodeURIComponent(manifest.cache_version) +
        '/' + zoom + '/' + x + '/' + y + '.png',
      window.location.href
    ).href
  }

  function detailTileUrl(x, y, zoom) {
    detailTileRequests += 1
    return new URL(
      './live-tiles/' + encodeURIComponent(manifest.cache_version) +
        '/' + zoom + '/' + x + '/' + y + '.png',
      window.location.href
    ).href
  }

  async function boot() {
    requestAnimationFrame(sampleFrames)
    setInterval(updateMetrics, 500)

    if (!window.TMap) {
      throw new Error('腾讯地图 SDK 未加载；请检查本机 Key 或网络')
    }
    manifest = await fetch('./manifest.json', { cache: 'no-store' }).then(function (response) {
      if (!response.ok) throw new Error('固定瓦片尚未生成')
      return response.json()
    })

    const center = new TMap.LatLng(manifest.center.latitude, manifest.center.longitude)
    map = new TMap.Map(document.getElementById('map'), {
      center: center,
      zoom: manifest.initial_zoom,
      minZoom: manifest.min_zoom,
      maxZoom: manifest.max_zoom,
      pitch: 0,
      rotation: 0,
    })
    fallbackHeatLayer = new TMap.ImageTileLayer({
      map: map,
      minZoom: manifest.min_zoom,
      maxZoom: manifest.max_zoom,
      tileSize: 256,
      imageSize: 512,
      zIndex: 19,
      getTileUrl: fallbackTileUrl,
    })
    detailHeatLayer = new TMap.ImageTileLayer({
      map: map,
      minZoom: Math.min(manifest.max_zoom, manifest.fallback_max_zoom + 1),
      maxZoom: manifest.max_zoom,
      tileSize: 256,
      imageSize: 512,
      zIndex: 20,
      getTileUrl: detailTileUrl,
    })
    window.__heatmapTileSpike = {
      map: map,
      fallbackHeatLayer: fallbackHeatLayer,
      detailHeatLayer: detailHeatLayer,
      center: center,
    }
    setStatus('父级红线持续显示；高倍率原始轨迹就绪后无缝覆盖')

    toggleButton.addEventListener('click', function () {
      heatVisible = !heatVisible
      fallbackHeatLayer.setVisible(heatVisible)
      detailHeatLayer.setVisible(heatVisible)
      toggleButton.textContent = heatVisible ? '隐藏热图' : '显示热图'
    })
    resetButton.addEventListener('click', function () {
      map.easeTo({ center: center, zoom: manifest.initial_zoom })
    })
  }

  boot().catch(function (error) {
    console.error(error)
    setStatus('启动失败：' + (error && error.message ? error.message : String(error)))
    document.body.classList.add('failed')
  })
})()
