"""约骑模块 Task 9：小程序静态合同测试。"""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _else_map_block(wxml: str) -> str:
    return wxml.split("<map wx:else", 1)[1].split("</map>", 1)[0]


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
    assert "routePreviewPolylines" in js
    assert "<map" in wxml
    assert 'polyline="{{routePreviewPolylines}}"' in wxml
    assert 'wx:if="{{paperMapHasCustomStyle}}"' in wxml
    assert "enable-poi=\"{{false}}\"" in wxml.split("<map wx:else", 1)[0]
    assert "route-preview-wash" not in wxml
    assert ".route-preview-map" in wxss


def test_shared_paper_map_theme_exists_and_hides_server_secret():
    theme_path = MINI / "utils" / "map-theme.js"
    theme = _read(theme_path)

    assert "PAPER_MAP_CONFIG" in theme
    assert "getPaperMapData" in theme
    assert "buildRoutePreviewPolylines" in theme
    assert "buildHeatmapPolyline" in theme
    assert "TENCENT_MAP_SK" not in theme
    assert "服务端 SK" in theme


def test_shared_paper_map_theme_normalizes_public_style_config():
    script = """
const assert = require('assert')
const mapTheme = require('./miniprogram/utils/map-theme')

assert.deepStrictEqual(
  mapTheme.getPaperMapData({ subkey: ' paper-subkey ', layerStyle: '7' }),
  {
    paperMapSubkey: 'paper-subkey',
    paperMapLayerStyle: 7,
    paperMapHasCustomStyle: true,
  },
)

assert.deepStrictEqual(
  mapTheme.getPaperMapData({ subkey: '   ', layerStyle: 'not-a-number' }),
  {
    paperMapSubkey: '',
    paperMapLayerStyle: 1,
    paperMapHasCustomStyle: false,
  },
)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_create_page_uses_shared_paper_map_theme_for_route_preview():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    wxss = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxss")

    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" in js
    assert "buildRoutePreviewPolylines" in js
    assert "routePreviewMapSubkey" not in js
    assert "paperMapSubkey" in wxml
    assert "paperMapLayerStyle" in wxml
    assert "route-preview-wash" not in wxml
    assert "rgba(255, 255, 255" in wxss


def test_heatmap_card_uses_shared_paper_map_theme():
    js = _read(MINI / "components" / "heatmap-card" / "heatmap-card.js")
    wxml = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxml")
    wxss = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxss")

    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" in js
    assert "buildHeatmapPolyline" in js
    assert "#FFD700CC" not in js
    assert "paperMapSubkey" in wxml
    assert "heatmap-map-wash" not in wxml
    assert "background: #eef3ee" in wxss


def test_map_picker_page_is_registered_and_uses_paper_map():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "map-picker" / "map-picker.js")
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")
    wxss = _read(MINI / "pages" / "map-picker" / "map-picker.wxss")

    assert "pages/map-picker/map-picker" in app_json["pages"]
    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" in js
    assert "selectMapPoint" in js
    assert "paperMapSubkey" in wxml
    assert "map-picker-pin" in wxml
    assert "map-picker-wash" not in wxml
    assert "位置名称" in wxml
    assert "{{confirmText}}" in wxml
    assert "rgba(255, 255, 255" in wxss
    assert "pointer-events: none" in wxss


def test_map_picker_fallback_keeps_default_cartography_context():
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")
    fallback = _else_map_block(wxml)

    assert 'enable-poi="{{false}}"' not in fallback
    assert 'enable-building="{{false}}"' not in fallback
    assert 'enable-traffic="{{false}}"' in fallback


def test_route_preview_fallback_keeps_default_cartography_context():
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    fallback = _else_map_block(wxml)

    assert 'enable-poi="{{false}}"' not in fallback
    assert 'enable-building="{{false}}"' not in fallback
    assert 'enable-traffic="{{false}}"' in fallback


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

    assert "'preview'" in js
    assert "onTapGoPreview" in js
    assert "onConfirmPublish" in js
    assert "toggleAudienceTag" in js
    assert "onVisibilityChange" in js
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


def test_pace_display_table_covers_all_four_pace_levels():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    for pace in ("relaxed", "cruise", "training", "race"):
        assert pace in js
    assert "不限功率" in js
    assert "FTP 160W+ 更舒服" in js
    assert "FTP 220W+" in js
    assert "FTP 280W+" in js
