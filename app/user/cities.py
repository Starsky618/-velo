"""6 城枚举常量 - 单一真相源（Sprint 6 task-2 / v0.3）。

干啥用：
- velo 后端到处用"北京/上海/杭州/深圳/成都/太原"6 个城市枚举（badges.py / city-medals /
  segments.city CHECK / users.city CHECK）。本模块负责统一**这 6 城真值从哪来**——
  绝不允许各处自己写一遍 ["beijing", "shanghai", ...]，否则未来加新城会改 N 处漏 M 处。

操作注意：
- 6 城真值在 `app/common/geo.py:_CITY_BOUNDS` 字典 keys（基础设施层 / 最早定义）。
  本文件**从 geo.py 派生**，不重复列 6 城字符串。
- 未来加新城市：① 改 geo.py `_CITY_BOUNDS` 字典加坐标 ② 改 Alembic CHECK 约束加枚举值
  ③ 在本文件 CITY_LABELS 加中文名（漏了会触发文件底部 assert 提示）。
- VALID_CITY_CODES 不含 "unknown"（业务真值的 6 城）；ALL_CITY_CODES_WITH_UNKNOWN 含
  "unknown"（与 DB CHECK 约束 7 枚举对齐）。

输入 / 输出：
- 输入：无（纯常量模块 / 静态派生）
- 输出：
  * `VALID_CITY_CODES: tuple[str, ...]` — 6 真实城市 code（不含 unknown）
  * `ALL_CITY_CODES_WITH_UNKNOWN: tuple[str, ...]` — 6 城 + unknown 全集
  * `CITY_LABELS: dict[str, str]` — code → 中文名映射
"""

from app.common.geo import _CITY_BOUNDS

# 6 真实城市 tuple（按 geo.py 字典 keys 插入顺序 / Python 3.7+ dict 保序）。
# 这里就像"快递分拣中心的城市清单"——清单本体在仓库（geo.py），本模块只是开窗口对外发卡。
VALID_CITY_CODES: tuple[str, ...] = tuple(_CITY_BOUNDS.keys())

# 含 unknown 兜底的全集（与 users.city / activities.city / segments.city CHECK 约束一致）。
# unknown = "推断不出来"的兜底值，不是真实城市，所以业务层（badges / city-medals）
# 通常用 VALID_CITY_CODES 排除掉它。
ALL_CITY_CODES_WITH_UNKNOWN: tuple[str, ...] = VALID_CITY_CODES + ("unknown",)

# 中文 label 映射（手维护 / 因为 geo.py 是 GPS 坐标 box 不带中文名）。
# 加新城时若忘了在这里加一行，下方 assert 会立刻报错提示 —— 不会等到生产 KeyError。
#
# label 带"骑友"后缀：与 PRD § 3.2 task-2 徽章规则表"成都骑友"示例字面一致。
# 这样 badges.py 输出 "北京骑友" / "成都骑友" 等 / 而不是裸城市名 "北京" / "成都"——
# 后者跟 user.city 字段重复 / 失去"身份徽章"语义。
CITY_LABELS: dict[str, str] = {
    "beijing": "北京骑友",
    "shanghai": "上海骑友",
    "hangzhou": "杭州骑友",
    "shenzhen": "深圳骑友",
    "chengdu": "成都骑友",
    "taiyuan": "太原骑友",
}

# 自检：CITY_LABELS keys 必须与 VALID_CITY_CODES 完全一致（防漏维护 / import 时立刻 fail）
assert set(CITY_LABELS.keys()) == set(VALID_CITY_CODES), (
    f"CITY_LABELS 漏维护 / VALID_CITY_CODES={VALID_CITY_CODES} / "
    f"CITY_LABELS keys={list(CITY_LABELS.keys())}"
)
