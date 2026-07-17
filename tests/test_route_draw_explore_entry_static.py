"""Route Draw V0 Task 5：探索页画路线入口静态合同测试。"""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"
EXPLORE_DIR = MINI / "pages" / "explore"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_explore_entry_only_exists_after_route_draw_page_is_ready():
    app_json = json.loads(_read(MINI / "app.json"))

    assert "pages/route-draw/route-draw" in app_json["pages"]
    for suffix in ("js", "wxml", "wxss", "json"):
        assert (MINI / "pages" / "route-draw" / f"route-draw.{suffix}").exists()


def test_explore_page_has_create_route_section_above_guide_list():
    wxml = _read(EXPLORE_DIR / "explore.wxml")

    assert '<view class="page-title">探索</view>' in wxml
    assert "创建路线" in wxml
    assert "画一条路线" in wxml
    assert 'bindtap="onTapDrawRoute"' in wxml
    assert wxml.index("create-route-section") < wxml.index("guide-list")

    guide_card_block = wxml.split("guide-card", 1)[1]
    assert "/pages/route-draw/route-draw" not in guide_card_block
    assert "onTapDrawRoute" not in guide_card_block


def test_explore_entry_blocks_anonymous_user_before_route_draw_page():
    js = _read(EXPLORE_DIR / "explore.js")
    draw_block = js.split("onTapDrawRoute: function", 1)[1].split("openGuide", 1)[0]

    assert "isLoggedIn" in js
    assert "if (!isLoggedIn())" in draw_block
    assert "wx.showToast" in draw_block
    assert "/pages/profile/profile" in draw_block
    assert "wx.navigateTo({ url: '/pages/route-draw/route-draw' })" in draw_block
    assert draw_block.index("if (!isLoggedIn())") < draw_block.index("wx.navigateTo")


def test_explore_route_guide_list_contract_stays_intact():
    js = _read(EXPLORE_DIR / "explore.js")
    wxml = _read(EXPLORE_DIR / "explore.wxml")

    assert "api.get('/api/route-guides')" in js
    assert "openGuide: function" in js
    assert "/pages/route-detail/route-detail?id=" in js
    assert 'wx:for="{{guides}}"' in wxml
    assert 'bindtap="openGuide"' in wxml


def test_explore_js_syntax():
    subprocess.run(
        ["node", "--check", str(EXPLORE_DIR / "explore.js")],
        cwd=ROOT,
        check=True,
    )
