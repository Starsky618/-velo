"""
地理坐标工具——"GPS → 城市的查表器"。

根据一个经纬度坐标，判断它落在 6 个主城（北京/上海/杭州/深圳/成都/太原）的哪个
矩形范围内，落在外面就返回 'unknown'。

为什么用矩形 box 不用复杂的多边形：
- 6 城的核心区都是粗粒度方块就够（不是行政边界精确划分）
- 写个 box 5 行代码搞定，多边形要算几何包含，性价比差
- 边界坐标是经验值，未来可在 admin 工具里人工修正（5.D.3 批量管理）

为什么放 common 不放 segment / user：
- segment 模块和 user 模块都要用这个函数
- 如果放 segment，user 要 import segment → 反向依赖（按单向依赖原则用户在赛段下游）
- 抽到 common 谁都能用，common 不依赖任何业务模块（CLAUDE.md "单向依赖" 强化版）

注意事项：
- lat / lon 可能为 None（旧数据 / 新用户没填），必须 `is not None` 检查
  不要写 `if lat:`——0.0 是合法纬度但 truthiness 会判 False（CLAUDE.md 陷阱 #1）
- 扩 6 城（比如加苏州 / 广州）需**两处同步改**：
  1. 本文件 `_CITY_BOUNDS` 字典加新城坐标
  2. Alembic 迁移改 segments / users 的 city CHECK 约束加新枚举值
  漏改 CHECK 约束 → DB 写入直接 IntegrityError，业务代码静默挂掉
"""


# 6 城 GPS 边界 box（经验值，spec §3.1.3 / Tim 拍板）
# 实际使用中可能有 1-2% 边缘点判错（市郊接壤区），admin 工具可人工修正
_CITY_BOUNDS = {
    "beijing":  {"lat_min": 39.4, "lat_max": 41.1, "lon_min": 115.4, "lon_max": 117.5},
    "shanghai": {"lat_min": 30.7, "lat_max": 31.9, "lon_min": 120.9, "lon_max": 122.0},
    "hangzhou": {"lat_min": 29.8, "lat_max": 30.6, "lon_min": 119.8, "lon_max": 120.7},
    "shenzhen": {"lat_min": 22.4, "lat_max": 22.9, "lon_min": 113.7, "lon_max": 114.7},
    "chengdu":  {"lat_min": 30.3, "lat_max": 31.0, "lon_min": 103.7, "lon_max": 104.4},
    "taiyuan":  {"lat_min": 37.5, "lat_max": 38.1, "lon_min": 112.3, "lon_max": 113.0},
}


def infer_city_from_coords(lat: float | None, lon: float | None) -> str:
    """
    经纬度 → 城市枚举（6 城之一 或 'unknown'）。

    判定逻辑：
    1. 任一坐标为 None → 直接 'unknown'（不能瞎猜）
    2. 遍历 6 城 box，第一个命中的就返回
    3. 都不命中 → 'unknown'（海外 / 国内非主城）

    返回：'beijing' / 'shanghai' / 'hangzhou' / 'shenzhen' / 'chengdu' /
          'taiyuan' / 'unknown'

    陷阱 #1（CLAUDE.md）：lat/lon 用 `is None` 不用 truthiness——
    0.0 度是合法值（赤道 / 本初子午线），truthiness 会误判为 None
    """
    if lat is None or lon is None:
        return "unknown"

    for city, b in _CITY_BOUNDS.items():
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            return city

    return "unknown"
