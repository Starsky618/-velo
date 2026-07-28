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

    allowed_account_deletion_disclosures = {
        MINI / "pages" / "settings" / "settings.js": [
            "已开放约骑会取消并解除关联后保留",
            "需删除已开放约骑",
        ],
        MINI / "pages" / "settings" / "settings.wxml": [
            "已开放约骑会取消并去关联保留",
        ],
        MINI / "utils" / "api.js": [
            "已开放约骑按后端规则去标识保留",
        ],
    }
    runtime_suffixes = {".js", ".json", ".wxml", ".wxss"}
    for path in MINI.rglob("*"):
        if not path.is_file() or path.suffix not in runtime_suffixes:
            continue
        if "design-system" in path.parts:
            continue
        source = _read(path)
        assert "meetup" not in source.lower(), f"{path} 仍残留约骑运行时代码"
        for disclosure in allowed_account_deletion_disclosures.get(path, []):
            assert disclosure in source
            source = source.replace(disclosure, "")
        assert "约骑" not in source, f"{path} 仍残留约骑用户文案或超出注销披露范围"


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

// 真画了线 + 真提交了绘制
assert.ok(calls.lineTo > 40, 'lineTo 调用次数过少: ' + calls.lineTo)
assert.strictEqual(calls.draw, 2)

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


def test_heatmap_card_uses_one_interactive_native_map_and_opens_fullscreen():
    js = _read(MINI / "components" / "heatmap-card" / "heatmap-card.js")
    wxml = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxml")
    wxss = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxss")

    assert "require('../../utils/heatmap-map')" in js
    assert "detail: 'card'" in js
    assert "buildHeatmapMapModel" in js
    assert "'orange', 2, 4000, '99'" in js
    assert "wx.navigateTo" in js
    assert "/pages/heatmap/heatmap" in js
    assert wxml.count("<map") == 1
    assert "<canvas" not in wxml
    assert 'polyline="{{polylines}}"' in wxml
    assert 'include-points="{{includePoints}}"' in wxml
    assert 'enable-scroll="{{true}}"' in wxml
    assert 'enable-zoom="{{true}}"' in wxml
    assert "全屏查看" in wxml
    assert "height: 480rpx" in wxss


def test_fullscreen_heatmap_has_map_layer_controls_and_real_map_interactions():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "heatmap" / "heatmap.js")
    wxml = _read(MINI / "pages" / "heatmap" / "heatmap.wxml")
    wxss = _read(MINI / "pages" / "heatmap" / "heatmap.wxss")

    assert "pages/heatmap/heatmap" in app_json["pages"]
    assert "detail: 'full'" in js
    assert "available_years" in js
    assert "wx.createMapContext('personal-heatmap-map'" in js
    assert "detail: 'viewport'" in js
    assert "getRegion" in js
    assert "getScale" in js
    assert "_viewportRequestSeq" in js
    assert "this._showOverviewLayer()" in js
    assert "this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1" in js
    assert "includePoints" in js
    assert "buildPolylines" in js
    assert "OVERVIEW_MAX_POINTS = 9000" in js
    assert "VIEWPORT_MAX_POINTS = 18000" in js
    assert "HEATMAP_LINE_OPACITY = '99'" in js
    assert 'polyline="{{polylines}}"' in wxml
    assert 'bindregionchange="onMapRegionChange"' in wxml
    assert 'enable-scroll="{{true}}"' in wxml
    assert 'enable-zoom="{{true}}"' in wxml
    assert "常骑区域" in wxml
    assert "全部足迹" in wxml
    assert "热度颜色" in wxml
    assert "yearOptions" in wxml
    assert "height: 100vh" in wxss
    assert "height: 88rpx" in wxss


def test_heatmap_map_model_keeps_one_geographic_space_and_converts_coordinates():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const model = heatmap.buildHeatmapMapModel([
  [[116.30, 39.90], [116.40, 39.95]],
  [[114.00, 22.50], [114.10, 22.55]],
], 'orange', 3)

assert.ok(model)
assert.strictEqual(model.polylines.length, 2)
// 轨迹仍在同一经纬度空间，而不是投影进多个互不相干的小格子。
assert.ok(model.allPoints[1].longitude - model.allPoints[0].longitude > 2)
assert.ok(model.allPoints[1].latitude - model.allPoints[0].latitude > 10)
// 中国境内 WGS-84 已转 GCJ-02，避免真实道路底图上偏移数百米。
assert.notStrictEqual(model.polylines[0].points[0].longitude, 116.30)
assert.notStrictEqual(model.polylines[0].points[0].latitude, 39.90)
assert.strictEqual(model.polylines[0].color, '#FF6B0052')
assert.strictEqual(model.polylines[0].width, 3)
assert.strictEqual(model.polylines[0].level, 'abovebuildings')
assert.strictEqual(model.focusPoints.length, 2)

const strongerModel = heatmap.buildHeatmapMapModel([
  [[116.30, 39.90], [116.40, 39.95]],
], 'orange', 2, 100, '99')
assert.strictEqual(strongerModel.polylines[0].color, '#FF6B0099')
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_client_lod_preserves_sharp_turns_instead_of_only_even_spacing():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const track = [
  { longitude: 0, latitude: 0 },
  { longitude: 1, latitude: 0 },
  { longitude: 2, latitude: 0 },
  { longitude: 2, latitude: 3 },
  { longitude: 3, latitude: 3 },
  { longitude: 4, latitude: 3 },
]
const reduced = heatmap.limitTrackPoints([track], 4)[0]

assert.strictEqual(reduced.length, 4)
assert.deepStrictEqual(reduced[0], track[0])
assert.deepStrictEqual(reduced[reduced.length - 1], track[track.length - 1])
assert.ok(reduced.some((point) => point.longitude === 2 && point.latitude === 3))

for (let pointCount = 3; pointCount <= 80; pointCount++) {
  const indexedTrack = Array.from({ length: pointCount }, (_, index) => ({
    longitude: index + Math.sin(index) * 0.2,
    latitude: Math.cos(index * 0.7),
    originalIndex: index,
  }))
  for (let limit = 2; limit < pointCount; limit++) {
    const indexedReduced = heatmap.limitTrackPoints([indexedTrack], limit)[0]
    const indexes = indexedReduced.map((point) => point.originalIndex)
    assert.strictEqual(indexedReduced.length, limit)
    assert.strictEqual(indexedReduced[0], indexedTrack[0])
    assert.strictEqual(indexedReduced[indexedReduced.length - 1], indexedTrack[pointCount - 1])
    assert.strictEqual(new Set(indexes).size, indexes.length)
    indexes.forEach((index, position) => {
      assert.ok(index >= 0 && index < pointCount)
      if (position > 0) assert.ok(index > indexes[position - 1])
    })
  }
}

const continuousTurns = Array.from({ length: 100 }, (_, index) => ({
  longitude: 112 + index * 0.0001,
  latitude: 37 + (index % 2 ? 0.0001 : 0),
  originalIndex: index,
}))
const continuousIndexes = heatmap.limitTrackPoints([continuousTurns], 10)[0]
  .map((point) => point.originalIndex)
const largestGap = Math.max(...continuousIndexes.slice(1).map((index, position) => (
  index - continuousIndexes[position]
)))
assert.ok(largestGap <= 14)

const shortTurn = Array.from({ length: 100 }, (_, index) => ({
  longitude: 112 + index * 0.0001,
  latitude: 37 + (index === 50 ? 0.001 : 0),
  originalIndex: index,
}))
assert.ok(heatmap.limitTrackPoints([shortTurn], 10)[0]
  .some((point) => point.originalIndex === 50))
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_does_not_infer_gps_gaps_from_dp_point_density():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const mixedDensity = heatmap.prepareTracks([[
  [116.000, 39], [116.001, 39], [116.002, 39],
  [116.042, 39], [116.043, 39], [116.044, 39],
]])
assert.strictEqual(mixedDensity.length, 1)
assert.strictEqual(mixedDensity[0].length, 6)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_final_wechat_polyline_payload_stays_under_one_megabyte():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const tracks = Array.from({ length: 1000 }, (_, trackIndex) =>
  Array.from({ length: 18 }, (_, pointIndex) => [
    112.45 + trackIndex * 0.00001 + pointIndex * 0.00002,
    37.70 + Math.sin(pointIndex / 5) * 0.001,
  ])
)
const model = heatmap.buildHeatmapMapModel(tracks, 'orange', 2, 18000, '99')
const payloadBytes = Buffer.byteLength(JSON.stringify(model.polylines))
const pointCount = model.polylines.reduce((sum, line) => sum + line.points.length, 0)

assert.strictEqual(model.polylines.length, 1000)
assert.ok(pointCount <= 18000)
assert.ok(payloadBytes < 1024 * 1024, `polyline payload too large: ${payloadBytes}`)

const oldCachedTracks = Array.from({ length: 9000 }, (_, trackIndex) => [
  [112.45 + trackIndex * 0.00001, 37.70],
  [112.45001 + trackIndex * 0.00001, 37.70001],
])
const oldCachedModel = heatmap.buildHeatmapMapModel(oldCachedTracks, 'orange', 2, 18000, '99')
const oldCachedBytes = Buffer.byteLength(JSON.stringify(oldCachedModel.polylines))
assert.strictEqual(oldCachedModel.polylines.length, 1000)
assert.ok(oldCachedBytes < 1024 * 1024, `old cache payload too large: ${oldCachedBytes}`)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_map_model_caps_render_payload_without_dropping_tracks():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const tracks = Array.from({ length: 100 }, (_, trackIndex) =>
  Array.from({ length: 100 }, (_, pointIndex) => [
    116 + trackIndex * 0.001 + pointIndex * 0.0001,
    39 + pointIndex * 0.0001,
  ])
)
const model = heatmap.buildHeatmapMapModel(tracks, 'orange', 3, 1000)
const pointCount = model.polylines.reduce((sum, line) => sum + line.points.length, 0)

assert.strictEqual(model.polylines.length, 100)
assert.ok(pointCount <= 1000)
model.polylines.forEach((line) => assert.ok(line.points.length >= 2))
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_polyline_cap_keeps_rare_geographic_coverage():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const common = Array.from({ length: 1000 }, (_, index) => [
  { longitude: 116.40 + index * 0.000001, latitude: 39.90 },
  { longitude: 116.41 + index * 0.000001, latitude: 39.91 },
])
const rareTravel = [
  { longitude: 114.00, latitude: 22.50 },
  { longitude: 114.10, latitude: 22.55 },
]
const reduced = heatmap.limitTrackPoints(common.concat([rareTravel]), 2002)

assert.strictEqual(reduced.length, 1000)
assert.ok(reduced.includes(rareTravel))
assert.ok(common.some((track) => !reduced.includes(track)))
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_zooming_out_invalidates_inflight_viewport_even_when_overview_is_visible():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const overview = [[{ longitude: 116.4, latitude: 39.9 }, { longitude: 116.5, latitude: 40.0 }]]
const page = Object.assign({}, pageDefinition, {
  data: { selectedColor: 'orange' },
  _overviewPreparedTracks: overview,
  _renderedTracks: overview,
  _viewportRequestSeq: 7,
  _lastViewportKey: 'inflight',
  setData: function () { throw new Error('same overview should not redraw') },
})

page._showOverviewLayer()

assert.strictEqual(page._viewportRequestSeq, 8)
assert.strictEqual(page._lastViewportKey, '')
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_last_year_request_wins_and_map_context_waits_for_rendered_map():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const requests = []
require.cache[apiPath] = { exports: {
  get: function () { return new Promise((resolve) => requests.push(resolve)) },
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
let mapContextCreates = 0
global.wx = {
  createMapContext: function () { mapContextCreates += 1; return { id: 'map' } },
}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange' }),
  _endpoint: function () { return '/api/user/me/heatmap' },
  _scheduleViewportRefresh: function () {},
  setData: function (update, callback) {
    Object.assign(this.data, update)
    if (callback) callback()
  },
})

// loading 时 map 尚未挂载，不能提前创建 MapContext。
assert.strictEqual(page._ensureMapContext(), null)
assert.strictEqual(mapContextCreates, 0)
page._pageReady = true

page._fetchHeatmap(2025, false)
page._fetchHeatmap(2024, false)
const response = (year) => ({
  tracks: [[[116.4, 39.9], [116.5, 40.0]]],
  activity_count: 1,
  available_years: [2025, 2024],
  selected_year: year,
})

;(async function () {
  requests[1](response(2024))
  await new Promise(setImmediate)
  requests[0](response(2025))
  await new Promise(setImmediate)
  assert.strictEqual(page.data.selectedYear, 2024)
  assert.strictEqual(mapContextCreates, 1)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_viewport_requests_are_single_flight_and_keep_latest_pending_view():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const requests = []
let active = 0
let maxActive = 0
require.cache[apiPath] = { exports: {
  get: function () {
    active += 1
    maxActive = Math.max(maxActive, active)
    return new Promise((resolve) => requests.push(function (value) { active -= 1; resolve(value) }))
  },
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange', selectedYear: null }),
  _endpoint: function () { return '/api/user/me/heatmap' },
  setData: function (update) { Object.assign(this.data, update) },
})
const first = { west: 116.2, south: 39.7, east: 116.6, north: 40.1, zoom: 10 }
const latest = { west: 116.3, south: 39.7, east: 116.7, north: 40.1, zoom: 10 }
const response = { tracks: [[[116.4, 39.9], [116.5, 40.0]]] }

;(async function () {
  page._fetchViewport(first)
  page._fetchViewport(latest)
  assert.strictEqual(requests.length, 1)
  requests[0](response)
  await new Promise(setImmediate)
  assert.strictEqual(requests.length, 2)
  requests[1](response)
  await new Promise(setImmediate)
  assert.strictEqual(maxActive, 1)
  assert.strictEqual(page._pendingViewport, null)
  assert.strictEqual(page.data.polylines.length, 1)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_viewport_read_generation_keeps_newest_async_map_region():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const reads = []
const fetched = []
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _overviewLoaded: true,
  _ensureMapContext: function () { return {} },
  _readViewport: function () {
    return new Promise((resolve) => reads.push(resolve))
  },
  _fetchViewport: function (viewport) { fetched.push(viewport) },
})
const older = { west: 116.1, south: 39.7, east: 116.5, north: 40.1, zoom: 10 }
const newest = { west: 116.3, south: 39.7, east: 116.7, north: 40.1, zoom: 10 }

;(async function () {
  page._scheduleViewportRefresh(0)
  await new Promise((resolve) => setTimeout(resolve, 5))
  page._scheduleViewportRefresh(0)
  await new Promise((resolve) => setTimeout(resolve, 5))
  reads[1](newest)
  await new Promise(setImmediate)
  reads[0](older)
  await new Promise(setImmediate)
  assert.deepStrictEqual(fetched, [newest])
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_unload_does_not_resurrect_viewport_retry_timer():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

let resolveRead = null
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _overviewLoaded: true,
  _ensureMapContext: function () { return {} },
  _readViewport: function () {
    return new Promise((resolve) => { resolveRead = resolve })
  },
})

;(async function () {
  page._scheduleViewportRefresh(0)
  await new Promise((resolve) => setTimeout(resolve, 5))
  page.onUnload()
  resolveRead(null)
  await new Promise(setImmediate)
  assert.strictEqual(page._pageAlive, false)
  assert.strictEqual(page._viewportTimer, null)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_unload_ignores_late_overview_and_viewport_network_responses():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const requests = []
require.cache[apiPath] = { exports: {
  get: function () { return new Promise((resolve) => requests.push(resolve)) },
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange', selectedYear: null }),
  _pageAlive: true,
  _endpoint: function () { return '/api/user/me/heatmap' },
  setDataCalls: 0,
  setData: function (update) {
    this.setDataCalls += 1
    Object.assign(this.data, update)
  },
})
const overviewResponse = {
  tracks: [[[116.4, 39.9], [116.5, 40.0]]],
  activity_count: 1,
  available_years: [2026],
}

;(async function () {
  page._fetchHeatmap(null, true)
  const callsBeforeUnload = page.setDataCalls
  page.onUnload()
  requests[0](overviewResponse)
  await new Promise(setImmediate)
  assert.strictEqual(page.setDataCalls, callsBeforeUnload)

  const viewportPage = Object.assign({}, pageDefinition, {
    data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange', selectedYear: null }),
    _pageAlive: true,
    _endpoint: function () { return '/api/user/me/heatmap' },
    setDataCalls: 0,
    setData: function () { this.setDataCalls += 1 },
  })
  viewportPage._fetchViewport({ west: 116.2, south: 39.7, east: 116.7, north: 40.2, zoom: 10 })
  viewportPage.onUnload()
  requests[1](overviewResponse)
  await new Promise(setImmediate)
  assert.strictEqual(viewportPage.setDataCalls, 0)
  assert.strictEqual(viewportPage._viewportFetchInFlight, false)
})().catch(function (error) { console.error(error); process.exit(1) })
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
    assert "function gcj02ToWgs84" in coords
    assert "module.exports = { wgs84ToGcj02, gcj02ToWgs84 }" in coords
