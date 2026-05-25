"""Sprint 11 训练结构纯函数测试：把 6 周功率区间翻译成用户能看懂的训练类型。"""

import json
import importlib


def _module():
    return importlib.import_module("app.training.distribution")


def _zones(z1=0, z2=0, z3=0, z4=0, z5=0, z6=0, z1_zero=0):
    z1_item = {"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 129, "seconds": z1, "percent": 0}
    if z1_zero:
        z1_item["zero_seconds"] = z1_zero
    return [
        z1_item,
        {"zone": "Z2", "name": "耐力", "min_w": 130, "max_w": 176, "seconds": z2, "percent": 0},
        {"zone": "Z3", "name": "节奏", "min_w": 177, "max_w": 211, "seconds": z3, "percent": 0},
        {"zone": "Z4", "name": "阈值", "min_w": 212, "max_w": 247, "seconds": z4, "percent": 0},
        {"zone": "Z5", "name": "VO2max", "min_w": 248, "max_w": 282, "seconds": z5, "percent": 0},
        {"zone": "Z6", "name": "无氧", "min_w": 283, "max_w": None, "seconds": z6, "percent": 0},
    ]


def _payload_for(zone_set):
    distribution = _module()
    stats = distribution.aggregate_power_zones([zone_set, zone_set, zone_set])
    return distribution.build_training_distribution_payload(stats)


def _group(payload, key):
    return next(item for item in payload["groups"] if item["key"] == key)


def _raw_zone(payload, zone):
    return next(item for item in payload["raw_zones"] if item["zone"] == zone)


def test_normalize_power_zones_accepts_list():
    distribution = _module()
    value = _zones(z2=60)

    assert distribution.normalize_power_zones(value) == value


def test_normalize_power_zones_accepts_json_string():
    distribution = _module()
    value = _zones(z2=60)

    assert distribution.normalize_power_zones(json.dumps(value, ensure_ascii=False)) == value


def test_normalize_power_zones_rejects_malformed_json_as_empty():
    distribution = _module()

    assert distribution.normalize_power_zones("{broken") == []


def test_aggregate_uses_group_denominator_without_z1():
    payload = _payload_for(_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900, z6=0))

    assert _group(payload, "endurance")["percent"] == 44
    assert _group(payload, "tempo_threshold")["percent"] == 47
    assert _group(payload, "high_intensity")["percent"] == 9


def test_raw_zones_percent_uses_total_with_z1():
    payload = _payload_for(_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900, z6=0))

    assert _raw_zone(payload, "Z1")["percent"] == 9
    assert _raw_zone(payload, "Z2")["percent"] == 40
    assert _raw_zone(payload, "Z3")["percent"] == 27
    assert _raw_zone(payload, "Z4")["percent"] == 15
    assert _raw_zone(payload, "Z5")["percent"] == 8
    assert _raw_zone(payload, "Z6")["percent"] == 0


def test_aggregate_exclude_zero_removes_only_z1_zero_time_from_display_total():
    distribution = _module()
    stats = distribution.aggregate_power_zones(
        [_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900, z1_zero=700)] * 3,
        exclude_zero=True,
    )
    payload = distribution.build_training_distribution_payload(stats)

    assert _raw_zone(payload, "Z1")["seconds"] == 900
    assert _raw_zone(payload, "Z2")["seconds"] == 13200
    assert payload["total_power_seconds"] == 30900
    assert payload["total_power_hours"] == 8.6
    assert _raw_zone(payload, "Z1")["percent"] == 3
    assert _raw_zone(payload, "Z2")["percent"] == 43


def test_aggregate_exclude_zero_keeps_groups_and_classification_unchanged():
    distribution = _module()
    zone_sets = [_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900, z1_zero=700)] * 3
    normal_payload = distribution.build_training_distribution_payload(distribution.aggregate_power_zones(zone_sets))
    exclude_payload = distribution.build_training_distribution_payload(
        distribution.aggregate_power_zones(zone_sets, exclude_zero=True)
    )

    assert exclude_payload["current_type"] == normal_payload["current_type"]
    assert exclude_payload["current_label"] == normal_payload["current_label"]
    assert exclude_payload["headline"] == normal_payload["headline"]
    assert exclude_payload["groups"] == normal_payload["groups"]


def test_aggregate_exclude_zero_uses_original_total_for_data_complete():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=3000, z2=700, z1_zero=2500)] * 3, exclude_zero=True)
    payload = distribution.build_training_distribution_payload(stats)

    assert payload["data_complete"] is True
    assert payload["insufficient_power_data"] is False
    assert payload["total_power_seconds"] == 3600


def test_aggregate_exclude_zero_treats_missing_zero_seconds_as_zero():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=1000, z2=3000)] * 3, exclude_zero=True)
    payload = distribution.build_training_distribution_payload(stats)

    assert _raw_zone(payload, "Z1")["seconds"] == 3000
    assert payload["total_power_seconds"] == 12000


def test_aggregate_exclude_zero_clamps_dirty_zero_seconds_to_z1_seconds():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=100, z2=3600, z1_zero=999)] * 3, exclude_zero=True)
    payload = distribution.build_training_distribution_payload(stats)

    assert _raw_zone(payload, "Z1")["seconds"] == 0
    assert payload["total_power_seconds"] == 10800


def test_threshold_wins_before_sweet_spot_when_z4_reaches_30_percent():
    distribution = _module()
    stats = distribution.aggregate_power_zones(
        [_zones(z1=500, z2=3500, z3=1500, z4=3000, z5=1500, z6=500)] * 3
    )

    assert distribution.classify_distribution(stats) == "threshold"
    assert distribution.build_training_distribution_payload(stats)["current_type"] == "threshold"


def test_classifies_sweet_spot():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900)] * 3)

    assert distribution.classify_distribution(stats) == "sweet_spot"


def test_classifies_polarized():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=800, z2=8200, z3=600, z4=1000, z5=900, z6=300)] * 3)

    assert distribution.classify_distribution(stats) == "polarized"


def test_classifies_pyramidal():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=700, z2=6000, z3=2500, z4=500, z5=800, z6=200)] * 3)

    assert distribution.classify_distribution(stats) == "pyramidal"


def test_classifies_mixed():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=500, z2=3500, z3=2500, z4=1000, z5=2500, z6=500)] * 3)

    assert distribution.classify_distribution(stats) == "mixed"


def test_z1_only_complete_data_falls_back_to_mixed():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=3600)] * 3)
    payload = distribution.build_training_distribution_payload(stats)

    assert payload["data_complete"] is True
    assert payload["insufficient_power_data"] is False
    assert payload["current_type"] == "mixed"
    assert payload["actions"]
    assert len(payload["week_plan"]) == 7


def test_data_incomplete_when_activity_count_below_two():
    # 门槛 3→2 后：1 条仍不足（1 < 2）；2 条达标见 test_two_activities_with_enough_seconds_is_complete
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z2=4000)])

    payload = distribution.build_training_distribution_payload(stats)

    assert payload["data_complete"] is False
    assert payload["insufficient_power_data"] is True
    assert payload["current_type"] is None
    assert payload["actions"] == []
    assert payload["week_plan"] == []
    # spec §7 line 257：数据不足时 current_description / target_description 也必须是确定文案，
    # 锁住 _INSUFFICIENT_COPY，将来有人改文案测试会立刻报警，不会静默漂移。
    assert payload["current_description"] == "最近 6 周有功率区间的骑行还不够，暂时不能判断训练结构。"
    assert payload["target_description"] == "先多记录几次有功率计的骑行，再让 velo 判断训练时间怎么分布。"


def test_data_incomplete_when_total_power_under_three_hours():
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z2=1000)] * 3)
    payload = distribution.build_training_distribution_payload(stats)

    assert payload["data_complete"] is False
    assert payload["current_label"] == "功率数据不足"
    assert payload["actions"] == []
    assert payload["week_plan"] == []


def test_payload_does_not_include_min_w_or_max_w():
    payload = _payload_for(_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900))

    assert all("min_w" not in zone and "max_w" not in zone for zone in payload["raw_zones"])


def test_week_plan_has_seven_structured_items_for_complete_data():
    payload = _payload_for(_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900))

    assert len(payload["week_plan"]) == 7
    assert all(set(item) == {"day", "title", "focus"} for item in payload["week_plan"])


def test_missing_zone_is_treated_as_zero_seconds():
    distribution = _module()
    stats = distribution.aggregate_power_zones([[{"zone": "Z2", "name": "耐力", "seconds": 3600}]] * 3)
    payload = distribution.build_training_distribution_payload(stats)

    assert _raw_zone(payload, "Z1")["seconds"] == 0
    assert _raw_zone(payload, "Z6")["seconds"] == 0
    assert payload["total_power_seconds"] == 10800


def test_non_numeric_seconds_is_ignored_without_crashing():
    distribution = _module()
    stats = distribution.aggregate_power_zones(
        [[{"zone": "Z2", "name": "耐力", "seconds": 3600}, {"zone": "Z3", "name": "节奏", "seconds": "bad"}]] * 3
    )
    payload = distribution.build_training_distribution_payload(stats)

    assert _raw_zone(payload, "Z3")["seconds"] == 0
    assert payload["total_power_seconds"] == 10800


def test_empty_or_all_zero_input_returns_incomplete_payload():
    distribution = _module()
    empty_payload = distribution.build_training_distribution_payload(distribution.aggregate_power_zones([]))
    zero_payload = distribution.build_training_distribution_payload(distribution.aggregate_power_zones([_zones()] * 3))

    assert empty_payload["data_complete"] is False
    assert zero_payload["data_complete"] is False
    assert empty_payload["total_power_seconds"] == 0
    assert zero_payload["total_power_seconds"] == 0


def test_two_activities_with_enough_seconds_is_complete():
    # 门槛从 3 降到 2（Tim 真实最近 6 周只骑 2 次有功率）：2 条 + 总时长达标即判定，不再卡 3 条
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z2=4400, z3=2000)] * 2)
    payload = distribution.build_training_distribution_payload(stats)

    assert payload["activity_count"] == 2
    assert payload["data_complete"] is True
    assert payload["current_type"] is not None


def test_sweet_spot_explanation_embeds_dynamic_tempo_percent():
    # 动态百分比：sweet_spot 解释里嵌入真实中强度占比（demo 那种"你有 47% 卡在中间"，比"较多时间"更戳人）
    distribution = _module()
    stats = distribution.aggregate_power_zones([_zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900)] * 3)
    payload = distribution.build_training_distribution_payload(stats)

    assert payload["current_type"] == "sweet_spot"
    tempo_pct = next(g["percent"] for g in payload["groups"] if g["key"] == "tempo_threshold")
    assert f"{tempo_pct}%" in payload["explanation"]
    assert "{tempo}" not in payload["explanation"]  # 占位符必须被真实数字替换
