"""小程序前端模块边界与共享地图、热力图回归。"""

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block_after(wxml: str, marker: str) -> str:
    return wxml.split(marker, 1)[1]


def test_meetup_frontend_is_fully_removed():
    app_json = json.loads(_read(MINI / "app.json"))
    registered_pages = app_json["pages"]
    tab_paths = [item["pagePath"] for item in app_json["tabBar"]["list"]]

    assert tab_paths == [
        "pages/home/home",
        "pages/explore/explore",
        "pages/upload/upload",
        "pages/profile/profile",
    ]
    assert "pages/map-picker/map-picker" not in registered_pages
    assert all("meetup" not in page.lower() for page in registered_pages)
    assert all("约骑" not in item.get("text", "") for item in app_json["tabBar"]["list"])

    removed_paths = [
        MINI / "pages" / "map-picker",
        MINI / "pages" / "meetup-create",
        MINI / "pages" / "meetup-detail",
        MINI / "pages" / "meetup-report",
        MINI / "pages" / "meetups-list",
        MINI / "pages" / "meetups-mine",
        MINI / "assets" / "icons" / "meetup",
        MINI / "utils" / "meetup-format.js",
    ]
    assert all(not path.exists() for path in removed_paths)

    runtime_suffixes = {".js", ".json", ".wxml", ".wxss"}
    for path in MINI.rglob("*"):
        if not path.is_file() or path.suffix not in runtime_suffixes:
            continue
        if "design-system" in path.parts:
            continue
        source = _read(path)
        assert "meetup" not in source.lower(), f"{path} 仍残留约骑运行时代码"
        assert "约骑" not in source, f"{path} 仍残留约骑用户文案"


def test_route_and_upload_surfaces_keep_core_flows_without_meetup_links():
    route_guide_js = _read(MINI / "pages" / "route-detail" / "route-detail.js")
    route_guide_wxml = _read(MINI / "pages" / "route-detail" / "route-detail.wxml")
    route_book_js = _read(MINI / "pages" / "route-book-detail" / "route-book-detail.js")
    route_book_wxml = _read(MINI / "pages" / "route-book-detail" / "route-book-detail.wxml")
    upload_js = _read(MINI / "pages" / "upload" / "upload.js")
    upload_wxml = _read(MINI / "pages" / "upload" / "upload.wxml")

    assert "onOpenRouteMapPage" in route_guide_js
    assert "onDownloadRouteExport" in route_guide_js
    assert "onOpenRouteMapPage" in route_book_js
    assert "onDownloadRouteExport" in route_book_js
    assert "onStartMeetup" not in route_guide_js + route_book_js
    assert "约骑" not in route_guide_wxml + route_book_wxml

    assert "/api/activities/upload" in upload_js
    assert "pollStatus" in upload_js
    assert "buildScoreCard" in upload_js
    assert "查看骑行详情" in upload_wxml
    assert "/api/meetups" not in upload_js
    assert "meetupBannerVisible" not in upload_js + upload_wxml


def test_registered_pages_and_static_assets_still_exist():
    app_json = json.loads(_read(MINI / "app.json"))

    for page in app_json["pages"]:
        page_path = MINI / page
        for suffix in (".js", ".json", ".wxml", ".wxss"):
            assert page_path.with_suffix(suffix).exists(), f"{page}{suffix} 缺失"

    for item in app_json["tabBar"]["list"]:
        assert (MINI / item["iconPath"]).exists()
        assert (MINI / item["selectedIconPath"]).exists()

    asset_ref = re.compile(r'src="/(assets/[^"]+)"')
    for wxml_path in MINI.rglob("*.wxml"):
        for ref in asset_ref.findall(_read(wxml_path)):
            assert (MINI / ref).exists(), f"{wxml_path} 引用了不存在的 /{ref}"


def test_route_map_markers_keep_wechat_required_dimensions():
    for page in ("route-detail", "route-book-detail"):
        js = _read(MINI / "pages" / page / f"{page}.js")
        for title in ("起点", "终点"):
            marker = re.search(
                r"\{[^{}]*width:\s*18[^{}]*height:\s*18[^{}]*title:\s*'"
                + title
                + r"'[^{}]*\}",
                js,
            )
            assert marker, f"{page} 的{title} marker 缺少微信地图要求的 18x18 尺寸"


def test_route_detail_uses_free_paper_canvas_for_display_route_map():
    js = _read(MINI / "pages" / "route-detail" / "route-detail.js")
    wxml = _read(MINI / "pages" / "route-detail" / "route-detail.wxml")
    wxss = _read(MINI / "pages" / "route-detail" / "route-detail.wxss")

    assert "require('../../utils/route-thumb')" in js
    assert "drawRoutePreviewThumb" in js
    assert "require('../../utils/route-map-nav')" in js
    assert "onOpenRouteMapPage" in js
    assert "routeMapOverlayVisible" not in js
    display_block = _block_after(wxml, 'class="route-map-wrap"')
    assert "<map" not in display_block
    assert "route-map-overlay" not in wxml
    assert 'canvas-id="route-paper-preview"' in wxml
    assert 'bindtap="onOpenRouteMapPage"' in wxml
    assert ".route-paper-canvas" in wxss
    assert ".route-map-overlay" not in wxss


def test_route_detail_export_flow_has_clear_fallback_actions():
    js = _read(MINI / "pages" / "route-detail" / "route-detail.js")
    wxml = _read(MINI / "pages" / "route-detail" / "route-detail.wxml")
    api = _read(MINI / "utils" / "api.js")

    assert "promptShareExportFile" not in js
    assert "lastExportDownloadUrl" in js
    assert "onCopyLastExportLink" in js
    assert "showExportSendFallback" in js
    assert "复制下载链接" in wxml
    assert "尝试发送微信" not in wxml
    assert wxml.index("复制下载链接") < wxml.index("发送到微信")
    assert "先生成路线文件" in wxml
    assert "两步导入" in wxml
    assert "wx.env.USER_DATA_PATH" in api
    assert "saveDownloadedFile" in api
    assert "tempFilePath: tempFilePath" in api
    assert "savedFilePath: savedFilePath" in api
    assert "filePath: savedFilePath || tempFilePath" in api
    assert "lastExportSavedPath || this.data.lastExportTempPath" in js
    assert "开发者工具不支持发送文件，请用真机测试" in api
    assert "wx.getFileSystemManager" in api
    assert "err && err.errMsg" in api


def test_shared_paper_map_theme_exists_and_documents_paid_style_lesson():
    theme_path = MINI / "utils" / "map-theme.js"
    theme = _read(theme_path)

    assert "PAPER_MAP_CONFIG" in theme
    assert "buildRoutePreviewPolylines" in theme
    # 个性化底图机器已拆除（付费能力未购买，挂上 = 真机鉴权卡死）
    assert "getPaperMapData" not in theme
    assert "buildHeatmapPolyline" not in theme
    # 教训必须留在文件头：subkey 是先购买再使用的付费能力，防未来 agent 重新接上
    assert "付费" in theme
    assert "TENCENT_MAP_SK" not in theme


def test_shared_paper_map_theme_builds_orange_route_polylines():
    script = """
const assert = require('assert')
const mapTheme = require('./miniprogram/utils/map-theme')

assert.deepStrictEqual(mapTheme.buildRoutePreviewPolylines([]), [])
assert.deepStrictEqual(mapTheme.buildRoutePreviewPolylines([{ latitude: 1, longitude: 2 }]), [])

const lines = mapTheme.buildRoutePreviewPolylines([
  { latitude: 37.8, longitude: 112.5 },
  { latitude: 37.9, longitude: 112.6 },
])
assert.strictEqual(lines.length, 1)
assert.strictEqual(lines[0].color, '#FF9500')
assert.strictEqual(lines[0].points.length, 2)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_route_thumb_drawing_really_executes_and_draws_lines():
    # 回归锚（2026-06-13 全地图白屏事故）：drawRouteThumb 曾先把点归一化成 {x,y}
    # 再传给 projectTracks，后者二次归一化只认 [lon,lat] / {latitude,longitude}，
    # {x,y} 全被当非法点丢弃 → 所有路线缩略图静默画空白。字符串断言测不出执行层
    # 断裂——本测试用 wx 桩真跑绘制链路，断言"真画了线"。
    script = """
const assert = require('assert')
const calls = {}
function rec(name) { return function () { calls[name] = (calls[name] || 0) + 1 } }
global.wx = {
  createCanvasContext: function () {
    return {
      setFillStyle: rec('setFillStyle'), fillRect: rec('fillRect'),
      setStrokeStyle: rec('setStrokeStyle'), setLineWidth: rec('setLineWidth'),
      beginPath: rec('beginPath'), moveTo: rec('moveTo'), lineTo: rec('lineTo'),
      quadraticCurveTo: rec('quad'), stroke: rec('stroke'), arc: rec('arc'),
      fill: rec('fill'), setLineCap: rec('cap'), setLineJoin: rec('join'),
      clearRect: rec('clearRect'), draw: rec('draw'),
    }
  },
}
const rt = require('./miniprogram/utils/route-thumb')

// 后端原始格式 [[lon, lat], ...]（preview_points / track-thumbs 都是这个）
const pts = []
for (let i = 0; i < 40; i++) pts.push([112.5 + i * 0.001, 37.8 + Math.sin(i / 5) * 0.01])
assert.strictEqual(rt.drawRouteThumb('a', pts, { width: 320, height: 180, lineWidth: 4, paper: true }), true)

// buildRoutePreview 转换后格式 [{latitude, longitude}, ...]
const objPts = pts.map(p => ({ latitude: p[1], longitude: p[0] }))
assert.strictEqual(rt.drawRouteThumb('b', objPts, { width: 70, height: 70, lineWidth: 2 }), true)

// 热力图多轨迹
assert.strictEqual(rt.drawHeatmapThumb('c', [pts, pts], { width: 327, height: 240, lineWidth: 2 }), true)

// 真画了线 + 真提交了绘制
assert.ok(calls.lineTo > 40, 'lineTo 调用次数过少: ' + calls.lineTo)
assert.strictEqual(calls.draw, 3)

// 点不够时如实返回 false（调用方据此隐藏画布）
assert.strictEqual(rt.drawRouteThumb('d', [[112.5, 37.8]], { width: 70, height: 70 }), false)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_no_wrong_method_jumps_to_tabbar_pages():
    # 红线守卫（2026-06-13 全模块走查实证）：微信硬规则——wx.navigateTo / wx.redirectTo /
    # navigator 默认 open-type 都不能跳 tabBar 页，调用静默 fail、页面纹丝不动。
    # 实锤过的翻车：settings 退出登录后卡死原页 ×4 / home 登录按钮点了没反应 /
    # 战报"交卷"跳不进上传页。tabBar 页只能 wx.switchTab（且带不了 url 参数，
    # 上下文走 globalData 寄存柜约定）。
    app_json = json.loads(_read(MINI / "app.json"))
    tab_paths = {item["pagePath"] for item in app_json["tabBar"]["list"]}

    js_jump = re.compile(r"wx\.(navigateTo|redirectTo)\(\s*\{\s*url:\s*['\"]([^'\"]+)['\"]")
    for js_path in MINI.rglob("*.js"):
        for m in js_jump.finditer(_read(js_path)):
            target = m.group(2).lstrip("/").split("?")[0]
            assert target not in tab_paths, (
                f"{js_path}: wx.{m.group(1)} 跳 tabBar 页 {target} 会静默 fail，必须 wx.switchTab"
            )

    navigator_tag = re.compile(r"<navigator[^>]*url=\"([^\"]+)\"[^>]*>")
    for wxml_path in MINI.rglob("*.wxml"):
        for m in navigator_tag.finditer(_read(wxml_path)):
            target = m.group(1).lstrip("/").split("?")[0]
            if target in tab_paths:
                assert 'open-type="switchTab"' in m.group(0), (
                    f"{wxml_path}: navigator 指向 tabBar 页 {target} 缺 open-type=\"switchTab\""
                )


def test_no_wxml_in_whole_project_uses_paid_personalized_map_style():
    # 红线守卫：微信小程序个性化底图（subkey + layer-style）自 2023-06-29 起是
    # "先购买再使用"的付费能力，velo 未购买——任何 <map> 挂上这两个属性，
    # 真机鉴权必失败、地图卡死（2026-06-12 事故，codex 多轮代码修复全部无效）。
    # 这条测试把教训变成结构约束：全工程 wxml 永远不许再出现这两个属性。
    for wxml_path in MINI.rglob("*.wxml"):
        wxml = _read(wxml_path)
        assert "subkey" not in wxml, f"{wxml_path} 使用了付费个性化底图 subkey"
        assert "layer-style" not in wxml, f"{wxml_path} 使用了付费个性化底图 layer-style"


def test_heatmap_card_uses_canvas2d_for_full_tracks_no_whiteout():
    # 2026-06-13 修白屏：全量轨迹（几十万点）塞旧 ctx.draw() 渲染超时白屏；
    # 新版 Canvas 2D 完整绘制服务端按显示预算返回的预览点。
    js = _read(MINI / "components" / "heatmap-card" / "heatmap-card.js")
    wxml = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxml")
    wxss = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxss")
    thumb = _read(MINI / "utils" / "route-thumb.js")

    assert "require('../../utils/route-thumb')" in js
    assert "drawHeatmap2d" in js  # 新版 Canvas 2D 函数
    assert "<map" not in wxml
    # 新版 Canvas 2D：type="2d" + id（不再是旧 canvas-id）
    assert 'type="2d"' in wxml
    assert 'id="heatmap-canvas"' in wxml
    assert 'canvas-id="heatmap-canvas"' not in wxml
    # canvas 永久在 DOM（hidden 状态层），不被 wx:else 销毁 → createSelectorQuery 永远查得到（防 race）
    assert "heatmap-state" in wxml
    assert "background: #eef3ee" in wxss
    # route-thumb 的 drawHeatmap2d 用组件作用域 createSelectorQuery + getContext('2d')
    assert "drawHeatmap2d" in thumb
    assert "comp.createSelectorQuery()" in thumb
    assert "getContext('2d')" in thumb


def test_heatmap_keeps_large_track_payload_out_of_set_data():
    # 真实账号 293 条活动时 tracks 约 6.7 MB；WXML 不读坐标，塞进 setData 只会
    # 把同一份大数组复制到视图层并阻塞重启后的首屏渲染。
    js = _read(MINI / "components" / "heatmap-card" / "heatmap-card.js")

    assert "this._tracks = tracks" in js
    assert "this.data.tracks" not in js
    assert "tracks: tracks" not in js


def test_heatmap_projects_distant_cities_into_readable_regions():
    # 回归锚：北京 + 深圳若共用一个全国比例尺，城市内 20~50km 的路线只剩几个像素点。
    # 热力图必须保留全部活动，同时给常骑区域独立可读的绘制空间。
    script = """
const assert = require('assert')
const rt = require('./miniprogram/utils/route-thumb')

function route(lon, lat, dx, dy) {
  const points = []
  for (let i = 0; i < 30; i++) {
    points.push([lon + dx * i / 29, lat + Math.sin(i / 4) * dy])
  }
  return points
}

const beijing = [
  route(116.25, 39.85, 0.35, 0.08),
  route(116.30, 39.92, 0.28, 0.06),
  route(116.18, 39.78, 0.42, 0.10),
]
const shenzhen = route(113.90, 22.50, 0.30, 0.05)
const result = rt.projectHeatmapTracks(beijing.concat([shenzhen]), 327, 240, 12)

assert.ok(result)
assert.strictEqual(result.regions.length, 2)
assert.strictEqual(result.tracks.length, 4)
// 常骑区域占主画面；首条北京路线不再被全国跨度压成小点。
const main = result.tracks[0]
const xs = main.map(p => p.x)
assert.ok(Math.max(...xs) - Math.min(...xs) > 100)
// 深圳仍在右侧独立区域中，不被静默过滤。
const remote = result.tracks[3]
assert.ok(remote.every(p => p.x > 210 && p.x < 327))
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_keeps_five_distant_regions_independently_readable():
    # 第 5 个城市不能和第 4 个城市重新合并共用全国比例尺；5+ 区域改用独立网格。
    script = """
const assert = require('assert')
const rt = require('./miniprogram/utils/route-thumb')

function route(lon, lat) {
  const points = []
  for (let i = 0; i < 30; i++) points.push([lon + i * 0.008, lat + Math.sin(i / 4) * 0.05])
  return points
}

const tracks = [
  route(116.3, 39.9),  // 北京
  route(121.4, 31.2),  // 上海
  route(104.0, 30.6),  // 成都
  route(114.0, 22.5),  // 深圳
  route(87.5, 43.8),   // 乌鲁木齐
]
const result = rt.projectHeatmapTracks(tracks, 327, 240, 12)

assert.ok(result)
assert.strictEqual(result.regions.length, 5)
assert.strictEqual(result.tracks.length, 5)
result.tracks.forEach(track => {
  const xs = track.map(p => p.x)
  const ys = track.map(p => p.y)
  assert.ok(Math.max(...xs) - Math.min(...xs) > 40)
  assert.ok(Math.max(...ys) - Math.min(...ys) > 10)
})
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_drops_isolated_gps_teleport_without_losing_real_segments():
    script = """
const assert = require('assert')
const rt = require('./miniprogram/utils/route-thumb')

const track = [
  [116.30, 39.90], [116.32, 39.91],
  [0, 0],
  [116.34, 39.92], [116.36, 39.93],
]
const result = rt.projectHeatmapTracks([track], 327, 240, 12)

assert.ok(result)
assert.strictEqual(result.regions.length, 1)
assert.strictEqual(result.tracks.length, 2)
assert.ok(result.tracks.every(segment => segment.length === 2))
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_drops_realistic_spike_and_short_bad_segment():
    script = """
const assert = require('assert')
const rt = require('./miniprogram/utils/route-thumb')

// 约 68km 单点漂移 + 两个相邻坏点都不应成为独立区域。
const tracks = [
  [[116.30, 39.90], [116.32, 39.91], [117.10, 39.91], [116.34, 39.92], [116.36, 39.93]],
  [[116.30, 39.90], [116.32, 39.91], [117.10, 39.91], [117.105, 39.912], [116.34, 39.92], [116.36, 39.93]],
]
tracks.forEach(track => {
  const result = rt.projectHeatmapTracks([track], 327, 240, 12)
  assert.ok(result)
  assert.strictEqual(result.regions.length, 1)
  result.tracks.forEach(segment => {
    assert.ok(segment.every(point => point.x < 327))
    const xs = segment.map(point => point.x)
    assert.ok(Math.max(...xs) - Math.min(...xs) > 100)
  })
})
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_keeps_sparse_three_point_long_ride():
    script = """
const assert = require('assert')
const rt = require('./miniprogram/utils/route-thumb')

const result = rt.projectHeatmapTracks([
  [[116.3, 39.9], [116.9, 40.1], [117.5, 40.3]],
], 327, 240, 12)

assert.ok(result)
assert.strictEqual(result.tracks.length, 1)
assert.strictEqual(result.tracks[0].length, 3)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_keeps_sparse_four_point_long_ride_and_two_real_regions():
    script = """
const assert = require('assert')
const rt = require('./miniprogram/utils/route-thumb')

const sparse = rt.projectHeatmapTracks([
  [[116.0, 39.9], [116.6, 39.9], [117.2, 39.9], [117.8, 39.9]],
], 327, 240, 12)
assert.ok(sparse)
assert.strictEqual(sparse.tracks.length, 1)
assert.strictEqual(sparse.tracks[0].length, 4)

// 一个连续双点段 + 稀疏远端点没有“跳出后返回”证据，也必须完整保留。
const mixedThree = rt.projectHeatmapTracks([[
  [116.0, 39.9], [116.02, 39.91], [116.7, 40.0],
]], 327, 240, 12)
assert.ok(mixedThree)
assert.strictEqual(mixedThree.tracks.length, 1)
assert.strictEqual(mixedThree.tracks[0].length, 3)

const mixedFour = rt.projectHeatmapTracks([[
  [116.0, 39.9], [116.02, 39.91], [116.7, 40.0], [117.3, 40.1],
]], 327, 240, 12)
assert.ok(mixedFour)
assert.strictEqual(mixedFour.tracks.length, 1)
assert.strictEqual(mixedFour.tracks[0].length, 4)

// 同一活动内两个各自连续的真实区域没有“跳出后返回”证据，两个都必须保留。
const twoRegions = rt.projectHeatmapTracks([[
  [116.30, 39.90], [116.32, 39.91],
  [121.40, 31.20], [121.42, 31.21],
]], 327, 240, 12)
assert.ok(twoRegions)
assert.strictEqual(twoRegions.regions.length, 2)
assert.strictEqual(twoRegions.tracks.length, 2)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_prefers_returned_real_region_over_long_bad_cluster():
    script = """
const assert = require('assert')
const rt = require('./miniprogram/utils/route-thumb')

const result = rt.projectHeatmapTracks([[
  [116.30, 39.90], [116.32, 39.91],
  [117.10, 39.91], [117.105, 39.912], [117.11, 39.914], [117.115, 39.916], [117.12, 39.918],
  [116.34, 39.92], [116.36, 39.93],
]], 327, 240, 12)

assert.ok(result)
assert.strictEqual(result.regions.length, 1)
assert.strictEqual(result.tracks.length, 2)
assert.ok(result.tracks.every(track => track.length === 2))
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_route_map_page_is_registered_and_uses_native_map_without_custom_subkey():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "route-map" / "route-map.js")
    wxml = _read(MINI / "pages" / "route-map" / "route-map.wxml")
    wxss = _read(MINI / "pages" / "route-map" / "route-map.wxss")

    assert "pages/route-map/route-map" in app_json["pages"]
    assert "pendingRouteMap" in js
    assert "onTapBack" in js
    assert "<map" in wxml
    assert "paperMapSubkey" not in wxml
    assert "layer-style" not in wxml
    assert 'polyline="{{polylines}}"' in wxml
    assert "route-map-page" in wxss


def test_route_preview_coordinate_helper_exports_converter():
    coords = _read(MINI / "utils" / "coords.js")

    assert "function wgs84ToGcj02" in coords
    assert "module.exports = { wgs84ToGcj02 }" in coords
