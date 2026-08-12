"""太原西山首轮赛段普查的版本化空间边界。"""

from __future__ import annotations


REGION_KEY = "taiyuan_xishan"
REGION_VERSION = "taiyuan_xishan_named_boundary_v1"

# 顺时针：南界枣杜公路 -> 西界角子崖 -> 北界二库/横岭 -> 东界各进山口。
# 已有赛段端点优先作为锚；没有赛段端点的进山口使用腾讯地点检索坐标。
BOUNDARY_ANCHORS = (
    {"label": "枣杜城区口", "lon": 112.380439, "lat": 37.673870, "evidence": "strava:34856789:start"},
    {"label": "枣杜山内端", "lon": 112.339045, "lat": 37.721736, "evidence": "strava:34856789:end"},
    {"label": "角子崖爬坡南端", "lon": 112.251919, "lat": 37.936327, "evidence": "strava:40079687:start"},
    {"label": "角子崖爬坡北端", "lon": 112.270578, "lat": 37.973229, "evidence": "strava:40079687:end"},
    {"label": "汾河二库桥", "lon": 112.378841, "lat": 37.988886, "evidence": "strava:29940254:start"},
    {"label": "二库北部岔口", "lon": 112.417969, "lat": 38.004139, "evidence": "strava:29940254:end"},
    {"label": "横岭11km大窑村口", "lon": 112.444720, "lat": 37.984082, "evidence": "strava:14942511:start"},
    {"label": "柴化线城区口", "lon": 112.470344, "lat": 37.941605, "evidence": "strava:25733595:start"},
    {"label": "玉泉山城区口", "lon": 112.449300, "lat": 37.896140, "evidence": "strava:29860910:end"},
    {"label": "S104化客头口", "lon": 112.415535, "lat": 37.866582, "evidence": "strava:23547468:start"},
    {"label": "杜儿坪街—桃花沟进山口", "lon": 112.404390, "lat": 37.836785, "evidence": "tencent_place:2026-08-13"},
    {"label": "长风西街万亩生态园", "lon": 112.452052, "lat": 37.827740, "evidence": "tencent_place:2026-08-13"},
    {"label": "狼坡入口", "lon": 112.387875, "lat": 37.798723, "evidence": "tencent_place:2026-08-13"},
    {"label": "店头城区口", "lon": 112.465191, "lat": 37.739973, "evidence": "strava:31959130:end"},
    {"label": "风峪沟口", "lon": 112.440033, "lat": 37.743277, "evidence": "tencent_place:2026-08-13"},
)

POLYGON_LON_LAT = tuple((item["lon"], item["lat"]) for item in BOUNDARY_ANCHORS)
QUERY_BOUNDS = (37.65, 112.23, 38.02, 112.49)


def polygon_wkt() -> str:
    closed = (*POLYGON_LON_LAT, POLYGON_LON_LAT[0])
    coordinates = ", ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in closed)
    return f"POLYGON (({coordinates}))"


def region_definition() -> dict:
    return {
        "region_key": REGION_KEY,
        "region_version": REGION_VERSION,
        "boundary_semantics": {
            "south": "枣杜公路",
            "north": "横岭—汾河二库",
            "west": "角子崖爬坡",
            "east": "西山与市区连接口链",
        },
        "anchors": list(BOUNDARY_ANCHORS),
        "query_bounds": list(QUERY_BOUNDS),
        "membership_rule": "完整来源线与 polygon 相交即纳入；矩形查询 halo 外部对象保留为 outside 审计账",
    }
