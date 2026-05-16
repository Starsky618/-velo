"""徽章规则模块 - 根据真实骑行数据自动算用户身份徽章（Sprint 6 task-2）。

干啥用：
- profile endpoint 调用 / 返 top 3 徽章挂在头像旁
- 5 种规则：FTP / 山名常客 / 累计里程 / 累计爬升 / 城市本地
- 规则全是真实骑行数据算出来的 = 无法编造 = velo 护城河

操作注意（红线）：
- **纯函数 / 不 import service / 不查 DB / 不读文件**（CLAUDE.md "纯函数规则"）
- **永远不允许用户手填徽章 / 自定义徽章**——破坏护城河
- top 3 限制 / 防视觉密度爆炸
- FTP 加脏数据下界 guard `ftp >= 50`（与 schemas.py PUT /profile 范围 50-500 一致），
  历史脏数据 ftp=10 等会被过滤 / 不渲染怪 label "FTP 10W"
- 山名稳定排序：频次降序 + segment_id 升序 tie-breaker（相同频次结果可复现）
- 阶梯遇负数 / 0 / 异常值 → 防御性归 0 不抛异常

输入 / 输出：
- 输入：dict（ftp / total_distance_m / total_elevation_m / city / top_segments 列表）
- 输出：list[dict]（每个含 type / label）/ 按优先级排序 / 最多 3 个

类比：徽章像高考成绩单上"自动算出"的奖项——分数线在那（阈值），考够分自动给奖，
没人能手填"我自己说我考了 700"——这就是 velo 徽章的护城河。
"""

from typing import Optional

# 从 cities.py 引共享 6 城常量（单一真相源 / 不重复列 6 城字符串）。
# cities.py 又从 app/common/geo.py 派生，保证未来加新城只改 geo.py 一处。
from app.user.cities import VALID_CITY_CODES, CITY_LABELS

# ===== 5 种徽章 type 常量 =====
# 用字符串常量而不是 Enum：① 前端 JSON 协议需要 str ② 跨模块引用直接 import 常量
# 而不是绕 Enum.value，少一层间接。
BADGE_TYPE_FTP = "ftp"
BADGE_TYPE_DISTANCE = "distance"
BADGE_TYPE_ELEVATION = "elevation"
BADGE_TYPE_REGULAR_MOUNTAIN = "regular_mountain"
BADGE_TYPE_CITY_LOCAL = "city_local"

# ===== 优先级（数字小 = 优先级高 / top 3 时按这个排）=====
# 排序逻辑："最能体现身份"的徽章排前面。FTP 是骑手生理硬实力 → 最高；
# 山名常客次之（"啥山骑常客"决定个人 identity）；累计里程 / 爬升偏量化；
# 城市本地排最后（信息密度低 / 只是地理标签）。
PRIORITY = {
    BADGE_TYPE_FTP: 1,
    BADGE_TYPE_REGULAR_MOUNTAIN: 2,
    BADGE_TYPE_DISTANCE: 3,
    BADGE_TYPE_ELEVATION: 4,
    BADGE_TYPE_CITY_LOCAL: 5,
}

# ===== 累计里程阶梯（米 / 1000km = 1_000_000m）=====
# 阈值降序排：按从高到低扫一遍，命中第一个就返回（取用户达到的最高阶梯）。
# 类比游戏里 "白银/黄金/铂金" 段位——只展示当前段位，不展示历史所有段位。
DISTANCE_TIERS = [
    (10_000_000, "累计 10000km+"),
    (8_000_000, "累计 8000km"),
    (5_000_000, "累计 5000km"),
    (3_000_000, "累计 3000km"),
    (1_000_000, "累计 1000km"),
]

# ===== 累计爬升阶梯（米）=====
ELEVATION_TIERS = [
    (100_000, "爬升 100000m+"),
    (50_000, "爬升 50000m"),
    (30_000, "爬升 30000m"),
    (10_000, "爬升 10000m"),
    (5_000, "爬升 5000m"),
]

# 山名常客判定阈值：同一赛段骑过 ≥ 5 次解锁徽章
REGULAR_MOUNTAIN_THRESHOLD = 5


def compute_badges(
    *,
    ftp: Optional[int],
    total_distance_m: float,
    total_elevation_m: float,
    city: Optional[str],
    top_segments: list[dict],  # [{"segment_id": int, "segment_name": str, "count": int}, ...]
) -> list[dict]:
    """计算用户徽章列表，按优先级返回最多 3 个。

    所有输入都允许 None / 0 / 空 list / 异常值——任何分支异常都不抛 / 仅跳过该徽章，
    保证 profile endpoint 永远不会因为徽章模块抛异常而 500。

    参数：
        ftp: 用户 FTP（瓦特）/ None 或 < 50 视为脏数据跳过 FTP 徽章
        total_distance_m: 全部 completed activity 距离之和（米）
        total_elevation_m: 全部 completed activity 爬升之和（米）
        city: 用户主城市 code（"beijing" 等 6 城 或 "unknown" 或 None）
        top_segments: 用户骑过最多次的 top N 赛段，每条含 segment_id / segment_name / count
                      调用方负责按 count desc 排好（本函数内部还会再用 segment_id 做 tie-breaker
                      二次稳定排序，保证相同频次时结果可复现）

    返回：
        list[dict]：每条 {"type": "ftp", "label": "FTP 220W"}，按 PRIORITY 升序 / 最多 3 个
    """
    badges = []

    # ----- 1. FTP 徽章 -----
    # guard ftp >= 50（与 schemas.UserProfileUpdate.ftp 范围 ge=50 一致 / 防脏数据 ftp=10）
    # 历史导入数据 / 老用户填错 / 第三方导出的极小值都会被过滤——不渲染"FTP 10W"这种怪 label
    if ftp is not None and ftp >= 50:
        badges.append({
            "type": BADGE_TYPE_FTP,
            "label": f"FTP {ftp}W",
            "priority": PRIORITY[BADGE_TYPE_FTP],
        })

    # ----- 2. 山名常客徽章 -----
    # top_segments 由 service 层 SQL group_by + count 给出；本函数兜底再排一次
    # 保证 count desc + segment_id asc 稳定（相同频次结果可复现 / 测试可断言）。
    #
    # 全程用 dict.get() 取键 / 缺键不抛 KeyError 把 profile endpoint 打成 500——
    # 即使上游传入坏 dict（缺 count / segment_id / segment_name 任一键），
    # 也只是跳过该条 / 退化到无徽章，不连累整个 profile 接口。
    if top_segments:
        eligible = [s for s in top_segments if s.get("count", 0) >= REGULAR_MOUNTAIN_THRESHOLD]
        if eligible:
            # 稳定排序：负 count 升序 = count 降序；segment_id 升序做 tie-breaker。
            # 相同频次时取 segment_id 小的（最早入库的赛段 = 用户骑得最久的那座山）。
            eligible.sort(key=lambda s: (-s.get("count", 0), s.get("segment_id", 0)))
            top = eligible[0]
            segment_name = top.get("segment_name") or ""
            if segment_name:  # 名字为空时退化跳过，不渲染"常客"裸字符串
                badges.append({
                    "type": BADGE_TYPE_REGULAR_MOUNTAIN,
                    "label": f"{segment_name}常客",
                    "priority": PRIORITY[BADGE_TYPE_REGULAR_MOUNTAIN],
                })

    # ----- 3. 累计里程徽章（取最高命中阶梯）-----
    # `> 0` guard 防御负数 / 0 / NaN：DISTANCE_TIERS 最低阈值 1_000_000m = 1000km，
    # 0 米的用户进入 for 循环也会走完全部 break 不到，但显式 `> 0` 更清晰
    # （未来加 0 米起步的 "新手徽章" 时能立刻看出这里要改）。
    if total_distance_m and total_distance_m > 0:
        for threshold, label in DISTANCE_TIERS:
            if total_distance_m >= threshold:
                badges.append({
                    "type": BADGE_TYPE_DISTANCE,
                    "label": label,
                    "priority": PRIORITY[BADGE_TYPE_DISTANCE],
                })
                break

    # ----- 4. 累计爬升徽章 -----
    if total_elevation_m and total_elevation_m > 0:
        for threshold, label in ELEVATION_TIERS:
            if total_elevation_m >= threshold:
                badges.append({
                    "type": BADGE_TYPE_ELEVATION,
                    "label": label,
                    "priority": PRIORITY[BADGE_TYPE_ELEVATION],
                })
                break

    # ----- 5. 城市本地徽章 -----
    # 只有 city 在 6 真城市内才挂（VALID_CITY_CODES 不含 "unknown"）。
    # unknown / None / 任意非枚举值都跳过——避免渲染"unknown 本地"这种语义错位。
    if city in VALID_CITY_CODES:
        badges.append({
            "type": BADGE_TYPE_CITY_LOCAL,
            "label": CITY_LABELS[city],
            "priority": PRIORITY[BADGE_TYPE_CITY_LOCAL],
        })

    # 按优先级排序 / 取 top 3 / 剥离内部辅助字段 priority（不透到 API 响应）。
    # Badge schema 只含 type / label 两字段，priority 是排序中间值不外露——
    # 保留 priority 在 dict 里只为排序方便，sort 完立刻 strip 干净。
    badges.sort(key=lambda b: b["priority"])
    return [{"type": b["type"], "label": b["label"]} for b in badges[:3]]
