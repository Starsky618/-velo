"""6 城共享常量测试 — Sprint 6 task-2 / case 12（单一真相源）。

测试目标：
- VALID_CITY_CODES 必须从 app.common.geo._CITY_BOUNDS 派生（不能手维护重复列表）
- CITY_LABELS keys 必须与 VALID_CITY_CODES 完全一致（防漏维护）
- ALL_CITY_CODES_WITH_UNKNOWN 含 unknown 兜底值

类比：测的是"派生关系"本身——如果哪天有人手滑改成 hardcode 6 城字符串，
本测试会立刻断言失败，提示"单一真相源被破坏了"。
"""

from app.common.geo import _CITY_BOUNDS
from app.user.cities import (
    ALL_CITY_CODES_WITH_UNKNOWN,
    CITY_LABELS,
    VALID_CITY_CODES,
)


def test_valid_city_codes_derived_from_geo_city_bounds():
    """case 12：VALID_CITY_CODES === tuple(_CITY_BOUNDS.keys())（单一真相源）。"""
    assert VALID_CITY_CODES == tuple(_CITY_BOUNDS.keys()), (
        f"VALID_CITY_CODES 应从 geo._CITY_BOUNDS 派生 / "
        f"实际 VALID_CITY_CODES={VALID_CITY_CODES} / "
        f"_CITY_BOUNDS.keys()={tuple(_CITY_BOUNDS.keys())}"
    )


def test_valid_city_codes_does_not_contain_unknown():
    """VALID_CITY_CODES 是 6 真城市 / 不含 unknown 兜底值。"""
    assert "unknown" not in VALID_CITY_CODES, (
        "VALID_CITY_CODES 不应含 unknown / unknown 是推断不出的兜底"
    )
    assert len(VALID_CITY_CODES) == 6, f"应正好 6 城 / 实际 {len(VALID_CITY_CODES)} 城"


def test_all_city_codes_with_unknown_extends_valid_with_unknown():
    """ALL_CITY_CODES_WITH_UNKNOWN = VALID + unknown / 与 DB CHECK 7 枚举对齐。"""
    assert ALL_CITY_CODES_WITH_UNKNOWN == VALID_CITY_CODES + ("unknown",)
    assert len(ALL_CITY_CODES_WITH_UNKNOWN) == 7


def test_city_labels_keys_match_valid_codes():
    """CITY_LABELS keys 必须与 VALID_CITY_CODES 完全一致（防漏维护中文名）。

    cities.py 末尾已有 assert 守卫 / 这条 pytest 双保险：
    pytest 阶段就报错 / 不等到 import cities.py 才炸。
    """
    assert set(CITY_LABELS.keys()) == set(VALID_CITY_CODES)


def test_city_labels_contain_real_chinese_names():
    """6 城 label 锁定（带"骑友"后缀 / 与 PRD § 3.2 字面"成都骑友"示例一致）。"""
    expected = {
        "beijing": "北京骑友",
        "shanghai": "上海骑友",
        "hangzhou": "杭州骑友",
        "shenzhen": "深圳骑友",
        "chengdu": "成都骑友",
        "taiyuan": "太原骑友",
    }
    assert CITY_LABELS == expected
