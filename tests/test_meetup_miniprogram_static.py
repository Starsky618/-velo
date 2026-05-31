"""约骑模块 Task 9：小程序静态合同测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_meetup_pages_are_registered_at_app_json_tail():
    app_json = json.loads(_read(MINI / "app.json"))

    assert app_json["pages"][0] == "pages/home/home"
    assert app_json["pages"][-3:] == [
        "pages/meetups-list/meetups-list",
        "pages/meetup-detail/meetup-detail",
        "pages/meetup-create/meetup-create",
    ]


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
    assert "selectedSegmentId" in js
    assert "selectedRouteBookId" in js
    assert "selectedActivityId" in js
    assert "currentStep" in wxml
    assert "路线" in wxml and "时间" in wxml and "发布" in wxml


def test_v1_out_of_scope_features_are_absent():
    all_text = "\n".join(_read(path) for path in (MINI / "pages").glob("meetup*/*.*"))

    assert "路线足迹" not in all_text
    assert "算法推荐" not in all_text
    assert "为你推荐" not in all_text
    assert "私聊" not in all_text
