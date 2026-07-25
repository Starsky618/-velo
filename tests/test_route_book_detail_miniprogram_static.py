"""Route Draw V0 Task 3：我的路书详情页小程序静态合同测试。"""

import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"
PAGE_DIR = MINI / "pages" / "route-book-detail"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_route_book_detail_page_files_are_registered():
    app_json = json.loads(_read(MINI / "app.json"))

    assert "pages/route-book-detail/route-book-detail" in app_json["pages"]
    for suffix in ("js", "wxml", "wxss", "json"):
        assert (PAGE_DIR / f"route-book-detail.{suffix}").exists()


def test_route_book_detail_api_uses_display_detail_endpoint():
    api = _read(MINI / "utils" / "api.js")
    helper_block = api.split("getRouteBookDetail: function", 1)[1].split("getRouteBookActivityCandidates", 1)[0]

    assert "'/api/route-books/' + routeBookId + '/detail'" in helper_block
    assert "'/api/route-books/' + routeBookId, 'GET'" not in helper_block


def test_route_book_detail_page_uses_route_book_contract_not_route_guide():
    js = _read(PAGE_DIR / "route-book-detail.js")
    wxml = _read(PAGE_DIR / "route-book-detail.wxml")

    assert "api.getRouteBookDetail" in js
    assert "/api/route-guides/" not in js
    assert "content_md" not in js
    assert "renderMarkdown" not in js
    assert "file_id" not in js
    assert "route-book-detail-page" in wxml
    assert "route-detail-page" not in wxml


def test_route_book_detail_page_shows_map_elevation_export_and_meetup_actions():
    js = _read(PAGE_DIR / "route-book-detail.js")
    wxml = _read(PAGE_DIR / "route-book-detail.wxml")

    assert "wgs84ToGcj02" in js
    assert "buildRoutePreview(route.preview_points)" in js
    assert "routeMapNav.openRouteMapPage" in js
    assert 'bindtap="onOpenRouteMapPage"' in wxml
    assert 'wx:if="{{routePreviewVisible}}"' in wxml

    assert "buildStats(route)" in js
    assert "climb / distance * 100" in js
    assert "NaN" not in js
    assert "drawElevationThumb" in js
    assert "缺少完整逐点海拔" in wxml
    assert "海拔生成中" not in wxml
    assert "路线处理中" not in wxml

    assert "api.createRouteExport" in js
    assert "api.downloadRouteExport" in js
    assert 'wx:if="{{route.export_ready}}"' in wxml
    assert "onStartMeetup" in js
    assert "/pages/meetup-create/meetup-create?route_book_id=" in js


def test_private_route_export_does_not_offer_anonymous_browser_link():
    js = _read(PAGE_DIR / "route-book-detail.js")
    wxml = _read(PAGE_DIR / "route-book-detail.wxml")

    assert "canCopyAnonymousExportLink" in js
    assert 'wx:if="{{canCopyExportLink}}" class="export-copy-button secondary"' in wxml
    assert "私有路线不能用浏览器链接匿名下载" in js
    assert wxml.index("onShareLastExport") < wxml.index("onCopyLastExportLink")

    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                global.Page = function () {}
                global.wx = {}
                const detail = require('./miniprogram/pages/route-book-detail/route-book-detail.js')
                const rows = {
                  privateDraft: detail.canCopyAnonymousExportLink({ anonymous_export_download_allowed: false }),
                  publicPublished: detail.canCopyAnonymousExportLink({ anonymous_export_download_allowed: true }),
                }
                process.stdout.write(JSON.stringify(rows))
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"privateDraft": False, "publicPublished": True}


def test_route_book_detail_meetup_action_requires_login():
    js = _read(PAGE_DIR / "route-book-detail.js")
    wxml = _read(PAGE_DIR / "route-book-detail.wxml")
    meetup_block = js.split("onStartMeetup: function", 1)[1].split("wx.navigateTo", 1)[0]

    assert "路书详情" in wxml
    assert "我的路书" not in wxml
    assert "isLoggedIn" in js
    assert "if (!isLoggedIn())" in meetup_block
    assert "登录后才能发约骑" in meetup_block
    assert "wx.switchTab({ url: '/pages/profile/profile' })" in meetup_block


def test_route_book_detail_build_stats_uses_meter_units_and_zero_climb():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                global.Page = function () {}
                global.wx = {}
                const detail = require('./miniprogram/pages/route-book-detail/route-book-detail.js')
                const rows = {
                  longRoute: detail.buildStats({ distance: 18240.5, climb: 365.2 }),
                  zeroClimb: detail.buildStats({ distance: 5000, climb: 0 }),
                  missingClimb: detail.buildStats({ distance: 5000, climb: null }),
                  badDistance: detail.buildStats({ distance: 0, climb: 120 }),
                }
                process.stdout.write(JSON.stringify(rows))
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["longRoute"] == [
        {"v": "18.2", "u": "km", "k": "距离"},
        {"v": "365", "u": "m", "k": "爬升"},
        {"v": "2.0", "u": "%", "k": "均坡"},
    ]
    assert rows["zeroClimb"] == [
        {"v": "5.00", "u": "km", "k": "距离"},
        {"v": "0", "u": "m", "k": "爬升"},
        {"v": "0.0", "u": "%", "k": "均坡"},
    ]
    assert rows["missingClimb"] == [{"v": "5.00", "u": "km", "k": "距离"}]
    assert rows["badDistance"] == [{"v": "120", "u": "m", "k": "爬升"}]


def test_route_export_requests_have_watchdogs_when_wechat_callbacks_are_lost():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let timers = []
                  let requestAborts = 0
                  let downloadAborts = 0
                  global.getApp = function () {
                    return { globalData: { baseUrl: 'https://example.test', token: 'token' } }
                  }
                  global.setTimeout = function (callback, ms) {
                    timers.push({ callback, ms })
                    return timers.length
                  }
                  global.clearTimeout = function () {}
                  global.wx = {
                    request: function () {
                      return { abort: function () { requestAborts += 1 } }
                    },
                    downloadFile: function () {
                      return { abort: function () { downloadAborts += 1 } }
                    },
                  }

                  const api = require('./miniprogram/utils/api.js')
                  const createPromise = api.createRouteExport(42, 'gpx', 'generic')
                  const requestTimer = timers.shift()
                  requestTimer.callback()
                  const createError = await createPromise.catch(function (err) { return err })

                  const downloadPromise = api.downloadRouteExport('/download/42', 'route.gpx')
                  const downloadTimer = timers.shift()
                  downloadTimer.callback()
                  const downloadError = await downloadPromise.catch(function (err) { return err })

                  process.stdout.write(JSON.stringify({
                    createError,
                    downloadError,
                    requestAborts,
                    downloadAborts,
                    requestWatchdogMs: requestTimer.ms,
                    downloadWatchdogMs: downloadTimer.ms,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["createError"]["code"] == -2
    assert rows["downloadError"]["code"] == -2
    assert rows["requestAborts"] == 1
    assert rows["downloadAborts"] == 1
    assert rows["requestWatchdogMs"] == 31_000
    assert rows["downloadWatchdogMs"] == 61_000


def test_route_book_detail_js_syntax():
    subprocess.run(
        ["node", "--check", str(PAGE_DIR / "route-book-detail.js")],
        cwd=ROOT,
        check=True,
    )
