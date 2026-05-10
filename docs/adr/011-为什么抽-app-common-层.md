# ADR-011: 为什么抽 app/common 层（共享工具下沉到独立包）

## 状态
accepted (2026-05-10)

## 上下文

v5 期 task-1.A.1 实施"赛段坡度+难度+城市"功能时，需要在两个模块都用到地理工具（haversine 距离计算 / GPS 坐标推断城市）：

- `app/segment/service.py`：赛段创建时计算 max_gradient 用 haversine
- `app/user/service.py`：用户 city 字段从最近一次 activity 起点 GPS 推断

第二轮 spec 双审（codex 异源审）抓到反向依赖问题：

- 方案 A：`infer_city_from_coords` 放 `app/segment/service.py` → `app/user/service.py` 要 import segment.service → user 模块依赖 segment 模块 = **违反 CLAUDE.md "单向依赖" 规则**（`User ← Activity ← Segment ← Notification ← Strava`）
- 方案 B：`infer_city_from_coords` 放 `app/user/service.py` → `app/segment/service.py` 也要这函数 → segment 反向依赖 user = **同样违反**
- 方案 C：两边各 copy 一份 = 复制粘贴 / 违反 spec 自审 "共享逻辑识别" 硬规则
- 方案 D：抽 `app/common/geo.py` 独立包 / 任意业务模块向下依赖 / common 自己不依赖任何业务模块 ✅

v0-v4 期间没有"无业务工具"的归属位置——零散小工具被塞进各自模块的 utils.py 或 helpers.py，遇到跨模块共享只能复制粘贴。v5 期共享工具已成规模（地理 / 时间 / 字符串规范化等），需要正式架构层归属。

## 决策

velo 从 v5 开始建立 `app/common/` 层，作为**任意业务模块都可以向下依赖的工具基础设施**：

```
app/
  common/      ← 任意业务模块向下依赖
    __init__.py
    geo.py     ← v5 第一个：haversine / infer_city_from_coords
  user/         ← 业务模块（最上层）
  activity/
  segment/
  notification/
  strava/       ← 业务模块（最下层）
```

### 准入规则

- ✅ **可以**：纯函数（输入/输出明确，无副作用）/ 通用算法（地理 / 时间 / 数学）/ 跨业务模块共享的常量
- ❌ **禁止**：任何业务对象（User / Activity 实例）/ 业务逻辑（如"骑行有效活动判定"）/ 数据库会话依赖
- ❌ **禁止**：common 自己 `import app.user / app.activity / app.segment` 等任何业务模块——即使 type hint 也不行（用 TYPE_CHECKING 或抽 protocol）

### 失败边界

如果一个工具发现自己离不开业务对象（例如要传 User 实例 / 要查 DB），说明它不该住 common，应该挪回业务模块自己的 utils 文件。**common 是"水电气"层 / 不是"杂货铺"**。

## 考虑过的选项

| 方案 | 描述 | 为什么不选 |
|---|---|---|
| A：放最依赖的模块 | `infer_city_from_coords` 放 segment（segment 用得多）| user 反向 import segment / 违反单向依赖 |
| B：放最上层模块 | 放 user（用户视角）| segment 反向 import user / 同样违反 |
| C：复制粘贴 | 两边各一份 | 修一处忘改另一处 / 违反 spec 自审"共享逻辑识别" |
| D：抽 common 包 | 独立 `app/common/` | ✅ 单向依赖明确 / 单一真相源 / 可拓展（v5 只有 geo.py / 未来可加 time.py / strings.py）|
| E：第三方库 | 找现成 PyPI 包 | haversine 简单一行 / city 推断是项目特定（6 城枚举）/ 引入依赖不划算 |

## 理由

1. **解决反向依赖根本性问题**。CLAUDE.md "单向依赖" 是核心架构纪律。任何"两个业务模块都需要"的工具，放在任一业务模块都会破坏单向依赖。`common` 层在所有业务模块下方 = 任意模块向下依赖合规。

2. **比"业务模块各放 utils.py"更可拓展**。v5 只抽了 geo.py（80 行），但已有 v6 候选：跨模块的时间窗口工具（"本周/本月" 时区切片用 BJT 不用 UTC）/ 字符串规范化（小程序字段做 trim 后再校验）/ 数学小工具（百分位 / 滑动平均）。`common` 层让这些有归属。

3. **强制接口纯净**。"common 不依赖任何业务模块" 这条硬约束让进入 common 的函数必须是纯函数 / 无副作用 / 输入输出明确——天然适合单元测试 / 可独立替换实现 / 多人协作不冲突。

4. **与 ADR-008 防火墙式扩展互补**。ADR-008 解决"业务功能怎么扩展"（新表 + 新模块），但没解决"业务模块之间的共享工具"。本 ADR 补这一层。

5. **v5 实证收敛快**。task-1.A.1 codex 异源审抓到反向依赖时，第二轮立刻拍 D 方案 / 写 `app/common/geo.py` + `__init__.py` 解释层职责 / Claude/Codex 三审通过 / 41 测试 passed。从问题暴露到落地 < 1 天。

## trade-off

**放弃了**：
- 模块自治性（业务模块自己拥有所有用到的工具）
- 找工具时 1 步定位（在 common 还是在自己的 utils？）

**换取了**：
- 单向依赖纪律不破
- 单一真相源（同一个工具只有一份实现）
- 跨业务模块改动协同成本降低

## 触发重评估的条件

- common 层文件数 > 8 → 说明杂货铺化 / 重新分类（geo / time / strings 各自独立包？）
- common 内某个函数被 100% 单一业务模块使用 → 应该挪回那个业务模块（不是真共享）
- 出现 "common 想 import 业务模块" 的需求 → 说明该函数不属于 common / 拒绝合入并讨论替代方案
- common 函数行为开始隐含"业务规则"（如 city 推断的 6 城枚举改 8 城）→ 评估是否仍是"通用工具"还是"业务规则"

## 引用路径

- `app/common/__init__.py:1-19` — 层职责说明 + 单向依赖图 + 操作注意事项
- `app/common/geo.py` — v5 第一个 common 模块（haversine / infer_city_from_coords / _CITY_BOUNDS）
- `docs/spec-v5.md §0.1` 代码事实表 — 标记 v5 新建 `app/common/` 是防火墙破例
- `docs/architecture-guide.md §3` 模块依赖表 — common 单独一行 / 标"单向依赖最下方（任意业务模块可向下用）"
- CLAUDE.md "单向依赖" — 业务模块层级链 + common 在所有之下
- 关联 memory：`feedback_no_reverse_dep_in_compat_window.md`（agent-collab §4.0 兼容期不引入新模块依赖原则的延伸）
