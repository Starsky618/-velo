"""约骑模块 Task 9：小程序静态合同测试。"""

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _else_map_block(wxml: str) -> str:
    return wxml.split("<map wx:else", 1)[1].split("</map>", 1)[0]


def _block_after(wxml: str, marker: str) -> str:
    return wxml.split(marker, 1)[1]


def test_meetup_pages_are_registered_at_app_json_tail():
    app_json = json.loads(_read(MINI / "app.json"))

    assert app_json["pages"][0] == "pages/home/home"
    assert app_json["pages"][-3:] == [
        "pages/meetups-list/meetups-list",
        "pages/meetup-detail/meetup-detail",
        "pages/meetup-create/meetup-create",
    ]


def test_meetup_tab_is_registered_in_tabbar():
    # 约骑必须有底部 tab 入口（spec 用户故事："velo '约骑' tab"），否则用户进不去
    app_json = json.loads(_read(MINI / "app.json"))
    tab_paths = [tab["pagePath"] for tab in app_json["tabBar"]["list"]]
    assert "pages/meetups-list/meetups-list" in tab_paths
    assert len(app_json["tabBar"]["list"]) <= 5  # 微信 tabBar 上限 5 个


def test_meetup_page_files_exist():
    for page in ("meetups-list", "meetup-detail", "meetup-create"):
        folder = MINI / "pages" / page
        for suffix in ("js", "wxml", "wxss", "json"):
            assert (folder / f"{page}.{suffix}").exists()


def test_api_helpers_use_meetup_endpoints():
    api = _read(MINI / "utils" / "api.js")

    for snippet in [
        "getMeetupsList",
        "getMeetupDetail",
        "createMeetup",
        "updateMeetup",
        "publishMeetup",
        "cancelMeetup",
        "joinMeetup",
        "leaveMeetup",
        "getRouteBooksList",
        "getRouteBookActivityCandidates",
        "createRouteBookFromActivity",
        "createRouteBookFromTencentDirection",
        "getSegmentsList",
        "requestForm",
    ]:
        assert snippet in api
    assert "/api/meetups" in api
    assert "/api/route-books" in api


def test_list_page_loads_open_meetups_and_navigates_to_detail():
    js = _read(MINI / "pages" / "meetups-list" / "meetups-list.js")
    wxml = _read(MINI / "pages" / "meetups-list" / "meetups-list.wxml")

    assert "api.getMeetupsList" in js
    assert "status: 'OPEN'" in js
    assert "/pages/meetup-detail/meetup-detail?id=" in js
    assert 'wx:for="{{meetups}}"' in wxml
    assert "发起约骑" in wxml


def test_detail_page_joins_and_leaves_without_user_chat():
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    wxml = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxml")

    assert "api.joinMeetup" in js
    assert "api.leaveMeetup" in js
    assert "api.getMeetupDetail" in js
    assert "onTapJoin" in js
    assert "onTapLeave" in js
    # 发起人取消：详情页按角色显示取消按钮（is_creator）+ 二次确认走 cancelMeetup
    assert "onTapCancel" in js
    assert "api.cancelMeetup" in js
    assert "is_creator" in js
    assert 'wx:if="{{meetup.canCancel}}"' in wxml
    # 照片墙：creator 上传 + 列表展示 + 删除
    assert "onTapAddMedia" in js
    assert "api.getMeetupMedia" in js
    assert "api.uploadMeetupMedia" in js
    assert "照片墙" in wxml
    assert "私信" not in wxml
    assert "评论" not in wxml


def test_detail_page_shows_participants_and_invite_share_button():
    # 2026-06-13 C6 修：详情页补已加入骑友列表 + 显眼的"邀请骑友"分享按钮。
    # 约骑是"一群人一起骑"，谁来了是第一眼社交信号；邀请必须显眼不能只靠右上角菜单。
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    wxml = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxml")

    # 参与者：拉 + 渲染（昵称/头像/队长标）
    assert "loadParticipants" in js
    assert "api.getMeetupParticipants" in js
    assert "invitees" in js and "invitees" in wxml
    assert 'wx:for="{{invitees}}"' in wxml
    assert "rider-list" in wxml
    assert "队长" in wxml  # is_creator 标
    # 0 人时空态 + 邀请按钮永远显示（刚发布最需要拉人）
    assert "rider-empty" in wxml
    # 分享：open-type="share" 触发 onShareAppMessage（带 token）
    assert 'open-type="share"' in wxml
    assert "onShareAppMessage" in js
    assert "邀请骑友" in wxml
    # 头像 baseUrl 拼接（自存头像 /uploads/ 才拼，微信完整 https 不拼）
    assert "/uploads/" in js


def test_detail_page_refreshes_participants_after_join_or_leave():
    # 加入/退出会改变"谁来了"这块社交信号；后端操作响应只带人数，不带头像昵称列表，
    # 所以前端成功后必须重新拉 /participants，避免按钮和骑友列表各显示一套旧状态。
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")

    join_block = js.split("onTapJoin: function ()", 1)[1].split("onTapLeave: function ()", 1)[0]
    leave_block = js.split("onTapLeave: function ()", 1)[1].split("onTapCancel: function ()", 1)[0]

    assert "loadParticipants()" in join_block
    assert "loadParticipants()" in leave_block


def test_create_page_is_three_step_flow_and_uses_backend_state():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "steps: [" in js
    assert "route" in js and "details" in js and "publish" in js
    assert "api.createMeetup" in js
    assert "api.publishMeetup" in js
    assert "api.updateMeetup" in js
    assert "draft_exists" in js
    assert "api.getSegmentsList" in js
    assert "api.getRouteBooksList" in js
    assert "api.getRouteBookActivityCandidates" in js
    assert "api.createRouteBookFromTencentDirection" in js
    assert "selectedSegmentId" in js
    assert "selectedRouteBookId" in js
    assert "selectedActivityId" in js
    assert "tencentStartText" in js
    assert "tencentEndText" in js
    assert "onTapCreateTencentRoute" in js
    assert "currentStep" in wxml
    assert "路线" in wxml and "时间" in wxml and "发布" in wxml
    assert "腾讯地图生成" in wxml
    # 时间必须用微信日期/时间选择器，不能用文本框让用户手敲 ISO 字符串
    assert 'mode="date"' in wxml
    assert 'mode="time"' in wxml


def test_create_page_uses_map_picker_instead_of_native_location_popup():
    app_js = _read(MINI / "app.js")
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "wx.chooseLocation" not in js
    assert "/pages/map-picker/map-picker?kind=" in js
    assert "onTapChooseTencentStart" in js
    assert "onTapChooseTencentEnd" in js
    assert "consumePendingMapPoint" in js
    assert "pendingMapPoint" in app_js
    assert "chooseLocation" not in json.dumps(app_json, ensure_ascii=False)
    assert "scope.userLocation" not in json.dumps(app_json, ensure_ascii=False)


def test_create_page_lets_user_name_tencent_route_before_generating():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "tencentRouteName" in js
    assert "tencentRouteName" in wxml
    assert "onTencentRouteNameInput" in js
    assert 'bindinput="onTencentRouteNameInput"' in wxml
    assert "buildTencentRouteName" in js
    assert "name: routeName" in js


def test_create_page_blocks_past_start_time_before_saving_or_publishing():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "minStartDate" in js
    assert 'start="{{minStartDate}}"' in wxml
    assert "ensureFutureMeetupTime" in js
    assert js.count("ensureFutureMeetupTime") >= 4


def test_confirm_page_route_detail_and_pace_controls_are_real_actions():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert 'bindtap="onTapPreviewRouteDetail"' in wxml
    assert "routeMapOverlayVisible" not in js
    assert "route-map-overlay" not in wxml
    assert "require('../../utils/route-map-nav')" in js
    assert "routeMapNav.openRouteMapPage" in js
    assert "paceIndex" in js
    assert 'class="pv-pace-picker"' in wxml
    assert 'bindchange="onPaceChange"' in wxml
    assert "this.updatePreviewDerived()" in js


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


def test_meetup_detail_uses_free_paper_canvas_for_display_route_map():
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    wxml = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxml")
    wxss = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxss")

    assert "require('../../utils/route-thumb')" in js
    assert "drawRoutePreviewThumb" in js
    assert "require('../../utils/route-map-nav')" in js
    assert "onOpenRouteMapPage" in js
    assert "routeMapOverlayVisible" not in js
    display_block = _block_after(wxml, 'class="map-card"')
    assert "<map" not in display_block
    assert "route-map-overlay" not in wxml
    assert 'canvas-id="meetup-route-preview"' in wxml
    assert 'bindtap="onOpenRouteMapPage"' in wxml
    assert ".route-preview-canvas" in wxss
    assert ".route-map-overlay" not in wxss


def test_confirm_publish_persists_confirm_page_pace_change():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    publish_block = js.split("onConfirmPublish: function ()", 1)[1].split("resolveRouteBookId", 1)[0]

    assert "pace_level: this.data.form.pace_level" in publish_block


def test_create_page_supports_meeting_point_map_and_favorites():
    api = _read(MINI / "utils" / "api.js")
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "getMeetupFavoritePlaces" in api
    assert "saveMeetupFavoritePlace" in api
    assert "deleteMeetupFavoritePlace" in api
    assert "/api/meetups/favorite-places" in api
    assert "favoritePlaces" in js
    assert "loadFavoritePlaces" in js
    assert "onTapChooseMeetingPoint" in js
    assert "saveMeetingPointAsFavorite" in js
    assert "applyFavoritePlace" in js
    assert "kind=meeting" in js
    assert "point.kind === 'meeting'" in js
    assert "bindtap=\"onTapChooseMeetingPoint\"" in wxml
    assert "bindtap=\"saveMeetingPointAsFavorite\"" in wxml
    assert "bindtap=\"applyFavoritePlace\"" in wxml


def test_create_page_persists_custom_power_speed_hints():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    ensure_block = js.split("ensureDraft: function ()", 1)[1].split("saveDraft: function ()", 1)[0]
    save_block = js.split("saveDraft: function ()", 1)[1].split("updateField: function", 1)[0]
    publish_block = js.split("onConfirmPublish: function ()", 1)[1].split("resolveRouteBookId", 1)[0]

    assert "recommended_power_label" in js
    assert "average_speed_range" in js
    assert "recommended_power_label: draft.recommended_power_label" in js
    assert "average_speed_range: draft.average_speed_range" in js
    assert "Object.assign({}, that.data.form" in ensure_block
    assert "Object.assign({}, that.data.form" in save_block
    assert "recommended_power_label: this.data.form.recommended_power_label" in publish_block
    assert "average_speed_range: this.data.form.average_speed_range" in publish_block
    # 功率/均速是区间选择器不是输入框（Tim 2026-06-13 拍：给现成档位挑，不让骑友手打）
    assert "POWER_OPTIONS" in js
    assert "SPEED_OPTIONS" in js
    assert "onPaceHintChange" in js
    assert 'range="{{powerOptions}}"' in wxml
    assert 'range="{{speedOptions}}"' in wxml
    assert 'data-field="recommended_power_label"' not in wxml
    assert 'data-field="average_speed_range"' not in wxml


def test_map_picker_supports_realtime_place_suggestions():
    api = _read(MINI / "utils" / "api.js")
    js = _read(MINI / "pages" / "map-picker" / "map-picker.js")
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")

    # 实时联想（Tim 2026-06-13 拍：像高德那样边输边出候选列）
    assert "getMeetupPlaceSuggestions" in api
    assert "/api/meetups/place-suggestions" in api
    assert "searchMeetupPlace" not in api
    assert "选择集合点" in js
    assert "api.getMeetupPlaceSuggestions" in js
    assert "wgs84ToGcj02" in js
    assert "searchKeyword" in js
    assert "placeSearchResults" in js
    assert "selectedSearchPlace" in js
    assert "sourceLatitude" in js
    assert "coordinate_system: 'wgs84'" in js
    assert "coordinate_system: 'gcj02'" in js
    assert "address: picked.address" in js
    assert "event.causedBy !== 'update'" in js
    assert "selectedSearchPlace: null" in js
    assert "onSearchKeywordInput" in js
    # 防抖 + 过期响应丢弃 + 起搜门槛，三件套缺一就退化成卡顿/错位
    assert "_suggestTimer" in js
    assert "_suggestSeq" in js
    assert "trimmed.length < 2" in js
    # 旧"搜索"按钮已删；卡顿根因（onRegionChange 写回地图中心）不许回潮
    assert "onTapSearchPlace" not in js
    assert "this.refreshCenter()" not in js
    assert 'bindinput="onSearchKeywordInput"' in wxml
    assert 'wx:for="{{placeSearchResults}}"' in wxml
    assert "picker-search-btn" not in wxml
    # 搜索框对起点/终点/集合点全开放（不再 wx:if kind 限定）
    assert 'wx:if="{{kind === \'meeting\'}}"' not in wxml


def test_confirm_publish_blocks_cutoff_window_before_backend_raw_error():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    publish_block = js.split("onConfirmPublish: function ()", 1)[1].split("resolveRouteBookId", 1)[0]

    assert "MEETUP_PUBLISH_CUTOFF_BUFFER_MS" in js
    assert "ensurePublishableMeetupTime" in js
    assert "30 * 60 * 1000 + 30 * 1000" in js
    assert "离出发太近，不能发布" in js
    assert "formatMeetupPublishError" in js
    assert "meetup cutoff passed" in js
    assert "ensurePublishableMeetupTime()" in publish_block


def test_tencent_route_names_are_bounded_and_errors_are_human():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    picker_wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")

    assert "TENCENT_POINT_NAME_MAX_LENGTH" in js
    assert "TENCENT_ROUTE_NAME_MAX_LENGTH" in js
    assert "limitTencentRouteName" in js
    assert "formatTencentRouteError" in js
    assert "生成失败，请检查路线名称和起终点" in js
    assert 'maxlength="40"' in picker_wxml


def test_create_page_formats_meter_distance_as_kilometers():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "distanceText(item.distance, type)" in js
    assert "type === 'segment'" in js
    assert "/ 1000" in js


def test_create_page_hides_tencent_env_config_errors_from_users():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "路线服务暂不可用" in js
    assert "err && err.code === 503" in js


def test_create_page_draws_light_route_preview_map():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    wxss = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxss")

    assert "wgs84ToGcj02" in js
    assert "preview_points" in js
    assert "drawMainRoutePreview" in js
    assert 'canvas-id="route-preview-main"' in wxml
    preview_block = _block_after(wxml, 'class="route-preview-shell"').split('class="pv-card pv-route-card"', 1)[0]
    assert "<map" not in preview_block
    assert "route-preview-wash" not in wxml
    assert ".route-preview-canvas" in wxss


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


def test_create_page_uses_shared_paper_map_theme_for_route_preview():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    wxss = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxss")

    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" not in js
    assert "buildRoutePreviewPolylines" in js
    assert "routePreviewMapSubkey" not in js
    preview_block = _block_after(wxml, 'class="route-preview-shell"').split('class="pv-card pv-route-card"', 1)[0]
    assert "paperMapSubkey" not in preview_block
    assert "paperMapLayerStyle" not in preview_block
    assert "route-map-overlay" not in wxml
    assert "route-preview-wash" not in wxml
    assert "rgba(255, 255, 255" in wxss


def test_heatmap_card_uses_canvas2d_for_full_tracks_no_whiteout():
    # 2026-06-13 修白屏：全量轨迹（几十万点）塞旧 ctx.draw() 渲染超时白屏，
    # 改用新版 Canvas 2D（type="2d" + this.createSelectorQuery）完整画不抽稀。
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


def test_map_picker_page_is_registered_and_uses_native_map_without_custom_subkey():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "map-picker" / "map-picker.js")
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")
    wxss = _read(MINI / "pages" / "map-picker" / "map-picker.wxss")

    assert "pages/map-picker/map-picker" in app_json["pages"]
    assert "require('../../utils/map-theme')" not in js
    assert "selectMapPoint" in js
    assert "<map" in wxml
    assert "paperMapSubkey" not in wxml
    assert "layer-style" not in wxml
    assert "map-picker-pin" in wxml
    assert "map-picker-wash" not in wxml
    # 名字跟着选中的候选走，不提供手填（位置名称输入框已删）
    assert "位置名称" not in wxml
    assert "picker-picked" in wxml
    assert "{{confirmText}}" in wxml
    assert "rgba(255, 255, 255" in wxss
    assert "pointer-events: none" in wxss


def test_map_picker_keeps_default_cartography_context():
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")

    assert 'enable-poi="{{false}}"' not in wxml
    assert 'enable-building="{{false}}"' not in wxml
    assert 'enable-traffic="{{false}}"' in wxml


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


def test_create_route_preview_card_uses_canvas_but_detail_opens_dedicated_map_page():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    preview_block = _block_after(wxml, 'class="route-preview-shell"').split('class="pv-card pv-route-card"', 1)[0]
    assert "<map" not in preview_block
    assert "route-map-overlay" not in wxml
    assert 'canvas-id="route-preview-main"' in wxml
    assert "require('../../utils/route-map-nav')" in js
    assert "routeMapNav.openRouteMapPage" in js


def test_meetup_detail_prefers_frozen_snapshot_and_keeps_legacy_route_fallback():
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")

    assert "that.loadRoutePreview(res.snapshot_route_points, res.route_book_id)" in js
    preview_block = js.split("loadRoutePreview: function", 1)[1].split("onOpenRouteMapPage", 1)[0]
    assert "if (preview.routePreviewVisible || !routeBookId" in preview_block
    assert "api.getRouteBookDetail(routeBookId)" in preview_block


def test_meetup_list_prefers_low_point_snapshot_and_only_fetches_legacy_routes():
    js = _read(MINI / "pages" / "meetups-list" / "meetups-list.js")
    load_block = js.split("loadTracks: function", 1)[1].split("markTrack: function", 1)[0]

    snapshot_check = "Array.isArray(item.snapshot_route_points)"
    assert snapshot_check in load_block
    assert load_block.index(snapshot_check) < load_block.index("api.getRouteBookDetail(item.route_book_id)")


def test_create_page_avoids_object_spread_for_wechat_runtime():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "...routePreview" not in js
    assert "...buildRoutePreview" not in js


def test_route_preview_coordinate_helper_exports_converter():
    coords = _read(MINI / "utils" / "coords.js")

    assert "function wgs84ToGcj02" in coords
    assert "module.exports = { wgs84ToGcj02 }" in coords


def test_meetup_pages_have_no_dash_placeholder():
    # Tim 2026-05-15 永久规则：前端永不显示 "-" 占位符，字段缺失整块隐藏（wx:if）
    for page in ("meetups-list", "meetup-detail", "meetup-create", "meetups-mine"):
        js = _read(MINI / "pages" / page / f"{page}.js")
        assert "'--'" not in js, f"{page}.js 不应有 '--' 占位符"


def test_my_meetups_page_registered_and_wired():
    # 个人页"我的约骑"：注册 + 四件套存在 + 两 tab + 个人页有入口
    app_json = json.loads(_read(MINI / "app.json"))
    assert "pages/meetups-mine/meetups-mine" in app_json["pages"]
    for suffix in ("js", "wxml", "wxss", "json"):
        assert (MINI / "pages" / "meetups-mine" / f"meetups-mine.{suffix}").exists()

    js = _read(MINI / "pages" / "meetups-mine" / "meetups-mine.js")
    wxml = _read(MINI / "pages" / "meetups-mine" / "meetups-mine.wxml")
    assert "api.getMyMeetups" in js
    assert "created" in js and "joined" in js
    assert "我发起的" in wxml and "我加入的" in wxml

    profile_js = _read(MINI / "pages" / "profile" / "profile.js")
    assert "onTapMyMeetups" in profile_js
    assert "meetups-mine" in profile_js


def test_v1_out_of_scope_features_are_absent():
    all_text = "\n".join(_read(path) for path in (MINI / "pages").glob("meetup*/*.*"))

    assert "路线足迹" not in all_text
    assert "算法推荐" not in all_text
    assert "为你推荐" not in all_text
    assert "私聊" not in all_text


def test_create_page_has_preview_step_and_social_fields():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "'confirm'" in js  # 2026-06 流程重排：preview 步改名 confirm（route→edit→confirm）
    assert "onTapGoPreview" in js
    assert "onConfirmPublish" in js
    assert "toggleAudienceTag" in js
    assert "onSelectVisibility" in js  # 可见范围改两盒子点选（不再用 picker 的 onVisibilityChange）
    assert "applySafetyTemplate" in js
    for field in ("supply_point", "eligibility_note", "safety_note", "visibility"):
        assert field in js and field in wxml
    # 标签：js 存 form.audience_tags，wxml 走 audienceOptions(带 selected 标志)+ toggleAudienceTag
    assert "audience_tags" in js
    assert "audienceOptions" in wxml and "toggleAudienceTag" in wxml
    assert "recommended_power_label" in js
    assert "average_speed_range" in js
    assert "VELO 反骚扰机制" in wxml
    # 继续邀请走微信原生转发（不是站内定向邀请）
    assert 'open-type="share"' in wxml
    # WXML 不支持 .indexOf()，选中态必须在 JS 算成 selected 标志
    assert "form.audience_tags.indexOf" not in wxml
    # 旧"发布约骑"直发按钮已被 onTapGoPreview/onConfirmPublish 两步取代
    assert 'bindtap="onPublish"' not in wxml
    # 发布前总览页用 canvas 轨迹缩略线，点"查看详情"再打开完整地图，避免小 map 抢按钮手势
    assert 'canvas-id="route-thumb-confirm"' in wxml
    assert "route-map-overlay" not in wxml


def test_eligibility_and_supply_point_are_component_pick_not_freetype():
    # Tim 2026-06-13 拍：给骑友现成组件挑，不让手打。门槛=预设多选 chips、
    # 补给点=最近用过快选（本地缓存），安全提示=模板 chips（既有）。
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    wxss = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxss")

    # 门槛：预设标签常量 + 多选拼接逻辑 + chips 带选中态
    assert "ELIGIBILITY_TAGS" in js
    assert "toggleEligibilityTag" in js
    assert "syncEligibilityOptions" in js
    assert "eligibilityOptions" in js and "eligibilityOptions" in wxml
    assert 'bindtap="toggleEligibilityTag"' in wxml
    assert ".pv-template-chip.active" in wxss  # 多选选中态样式
    # 草稿恢复 + 手打 textarea 都要同步 chips 选中态
    assert "syncEligibilityOptions(draft.eligibility_note" in js
    assert "syncEligibilityOptions(value)" in js

    # 补给点：本地缓存快选（不进后端表，纯客户端记忆）
    assert "SUPPLY_POINT_HISTORY_KEY" in js
    assert "loadSupplyPointHistory" in js
    assert "rememberSupplyPoint" in js
    assert "applySupplyPoint" in js
    assert "wx.getStorageSync" in js and "wx.setStorageSync" in js
    assert "supplyPointHistory" in wxml
    assert 'bindtap="applySupplyPoint"' in wxml
    # 发布成功才记住（不是草稿阶段）
    publish_block = js.split("onConfirmPublish: function ()", 1)[1].split("resolveRouteBookId", 1)[0]
    assert "rememberSupplyPoint" in publish_block


def test_pace_display_table_covers_all_four_pace_levels():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    for pace in ("relaxed", "cruise", "training", "race"):
        assert pace in js
    # 默认档必须是 POWER_OPTIONS / SPEED_OPTIONS 的成员，否则 picker 定位不到当前档
    assert "不限功率" in js
    assert "'160-180W'" in js
    assert "'200-220W'" in js
    assert "'250W+'" in js


def test_create_page_restores_draft_and_share_path_carries_invite_token():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    api = _read(MINI / "utils" / "api.js")

    # 草稿恢复
    assert "restoreDraft" in js
    assert "api.getMyMeetupDraft" in js
    assert "loadMedia()" in js
    assert "buildRoutePreview" in js
    # 微信原生转发邀请（invite_only 带 token）
    assert "onShareAppMessage" in js
    assert "draft.share_token" in js
    assert "shareToken" in js
    assert "token=" in js
    # api helper：participants 新增 / detail + join 替换为带 token 签名
    assert "getMeetupParticipants" in api
    # S13-T3/T5：detail 签名加了 source（埋点来路标记），token 合同不变
    assert "getMeetupDetail: function (meetupId, token, source)" in api
    assert "joinMeetup: function (meetupId, token)" in api
    assert "getRouteBookDetail" in api


def test_meetup_detail_consumes_invite_token_from_share_link():
    # 私圈分享链接 ?id=X&token=Y 落地详情页：必须收下 token 并透传给详情/加入/照片，
    # 否则受邀者带链接进来后端门禁返回 404（这是 task5+6 双审抓到的 Critical，加静态测试锁死）
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    assert "options.token" in js
    assert "shareToken" in js
    # S13-T3/T5：调用点第三参是 source（埋点来路），token 透传合同不变
    assert "getMeetupDetail(this.data.meetupId, this.data.shareToken, source)" in js
    assert "options.source" in js  # 分享卡 ?source=share_card 必须被读取，否则①触达埋点恒为 0（集成审 Critical 锁死）
    assert "joinMeetup(this.data.meetupId, this.data.shareToken)" in js
    assert "getMeetupMedia(this.data.meetupId, this.data.shareToken)" in js
