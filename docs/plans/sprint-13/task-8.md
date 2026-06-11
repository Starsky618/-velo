# Sprint 14 Task-8 — 路线推荐列表页 + 路线详情页（route-guides 双端点）

> 所属：Sprint 14 路线百科上架 / 第 2 个 task。
> 上游：`docs/spec-v6.md` §3.7 / §4（RouteGuideOut 字段闭集）/ D11。
> 前置门：T7 已 commit（表与数据就位）。与 T9 并行。

---

## ─────── 给 Tim 看 ───────

### 干啥用

App 里的"路线百科书架"：列表页一眼扫 13 条太原路线，点进详情看介绍、亮点、海拔曲线、轨迹地图，底部一键"发起约骑"（按钮归 T9 接线，本 task 先把页面立起来）。

### 用户故事

新用户第一次打开 velo，路线页是他的第一站：天龙山西线、横岭、清徐……每条有封面和一句亮点。点开天龙山：介绍读着像本地老骑友写的，海拔曲线告诉他爬升集中在哪段。汾河二库还没轨迹，照样有介绍——只是没有曲线、没有发起按钮，他不会看到一个"残缺"的页面，只会看到一个"还没挂图纸"的手册。

### 怎么算做对了

- ✓ 列表页数据源是 guides 全集（含还没轨迹的，标 ready 与否）。
- ✓ 详情页：介绍 + 亮点 + 海拔曲线 + 轨迹预览；没轨迹的路线无曲线、无地图、无发起按钮，整块消失不留"-"。
- ✓ 没封面的路线显示统一空态占位图，不破版。
- ✓ 官方列表与 route_books 解耦（D11：数据源是 route_guides，不是给 books 做筛选）。

### 这次不做

- 「发起约骑」按钮的预填接线（T9）。
- 实况格子 / 评论区（D-002 第二、三层，显式押后到上线后）。
- 路线搜索 / 筛选 / 排序（13 条不需要）。

### 估时

1.5 天。

---

## ⚠ 设计修订（2026-06-11 Tim 拍 / T8 已 commit 后的 UX 返工，正式版硬约束）

1. **模块可折叠**：打开路线详情页只看见——封面图 / 一句话简介 / 这是一条什么路 / 给真要去的骑友 / 核心数据 / 怎么骑 / 骑友怎么说 / 安全 / 真实画面——这几个**模块标题**；具体内容点开才展开（防认知过载）。封面图 + 一句话简介常显，其余全部默认折叠。
2. **禁止任何小字备注或提醒**：来源标签（［2源］）、时效提醒（"出发前再核实"）、数据备注括号一律不出现在正式版页面；溯源信息只活在 route.json。
3. **模块名 = HTML 卡板块名原文**（Tim 审过的词汇），投影器与前端协议化：content_md 用固定 `## 模块名` 分节，前端按 ## 切分成手风琴。路况时效内容并入「安全」模块；海拔曲线放「核心数据」展开态；轨迹地图放「怎么骑」展开态；「真实画面」= 图库（图未上传时整模块消失）。
4. 「发起约骑」按钮维持底部常显。

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/spec-v6.md | sed -n '184,192p;215,216p'      # §3.7 + RouteGuideOut 定义
sed -n '1,30p;95,115p' app/route_book/router.py           # 现有 router（顺序敏感注释）+ 通配路由
rg -n "class RouteBookResponse|preview_points|distance" app/route_book/schemas.py | head
rg -n "include_router" app/main.py
ls miniprogram/pages/                                      # 页面目录惯例
rg -n "占位|placeholder|空态" miniprogram/pages/ -r | head -5   # 既有空态模式
```

已验证事实（2026-06-11 主 agent grep）：
- route_book/router.py:104 有 `GET /{route_book_id}` 通配路由，:6-7 文件头有顺序敏感注释 [✓ Read]——**route_guides 用独立子前缀 `/api/route-guides` 完全避开**（spec 定案，不在旧 router 里加子路径）
- main.py 挂载模式 = import router + `app.include_router(xxx_router)`（:44-61），新增模块零侵入 [✓ Read]
- `RouteBook.preview_points` 是模型 property（WKB/WKT→[[lon,lat]]）[✓ Read models.py:58-82]，guide 详情的 preview_points 经 JOIN route_books 取
- distance/climb 是 route_books 现有列（米单位，API 出 km 按项目约定换算——执行时 re-grep 现有 RouteBookResponse 怎么换，照惯例）

## 2. 文件改动清单

- Create `app/route_book/guides_router.py`（新 router，prefix="/api/route-guides"）
- Modify `app/route_book/schemas.py`：新增 RouteGuideListItem / RouteGuideOut
- Modify `app/route_book/service.py`：新增 `list_route_guides(db)` / `get_route_guide(db, guide_id)`（或新建 service_guides.py，若现有 service.py 已近行数红灯——执行时 wc -l 后定，职责单一优先）
- Modify `app/main.py`：import + include_router（两行）
- Create `miniprogram/pages/route-list/` + `miniprogram/pages/route-detail/`（各四件）
- Modify `miniprogram/app.json`：注册两页
- Create `miniprogram/utils/md-render.js`（最小 markdown 子集 → rich-text 节点，见 §4）
- Create `tests/test_route_guides_api.py`
- **Do not** 改 route_book/router.py 现有路由 / **Do not** 在 route_guides 表加列

## 3. API 契约（spec §4 字段闭集，extra="forbid"）

```python
# GET /api/route-guides —— 列表（官方路线全集，含 track_pending）
class RouteGuideListItem(BaseModel):
    id: int
    name: str
    city: str
    ready: bool                       # = route_book_id IS NOT NULL（D11）
    cover_url: str | None = None
    highlights: list[str] | None = None   # DB 存 JSON 文本，service 层 json.loads
    distance: float | None = None     # km；仅 ready=true 时有值（JOIN route_books）
    climb: float | None = None        # m；仅 ready=true
    model_config = ConfigDict(extra="forbid")


# GET /api/route-guides/{id} —— 详情
class RouteGuideOut(BaseModel):
    id: int
    name: str
    city: str
    ready: bool
    content_md: str
    cover_url: str | None = None
    highlights: list[str] | None = None
    elevation_profile: list[list[float]] | None = None   # 本表列（D11 预计算），无轨迹 NULL
    route_book_id: int | None = None
    distance: float | None = None     # 仅 ready=true，JOIN route_books
    climb: float | None = None
    preview_points: list[list[float]] | None = None      # 仅 ready=true，经现有 property 取
    model_config = ConfigDict(extra="forbid")
```

service 要点：
- 列表查询 = `db.query(RouteGuide).outerjoin(RouteBook, ...)` 一次取齐（13 条规模无分页，但仍按 name 或 id 稳定排序）
- ready 派生 = `guide.route_book_id is not None`（**不要写 `if guide.route_book_id:`**——id 不会是 0 但纪律统一，陷阱 #1）
- 米→km 换算在 service 层，沿用现有 RouteBookResponse 的换算惯例
- 404：guide 不存在 → HTTPException 404

## 4. 前端要点

- **route-list**：封面 + 名字 + 亮点第一条 + （ready 时）距离/爬升徽标；cover_url 为 null → 统一本地占位图（`miniprogram/assets/` 放一张，不要灰字"暂无图片"）
- **route-detail**：
  - content_md 渲染：`miniprogram/utils/md-render.js` 最小子集（标题/段落/粗体/无序列表/图片）→ `<rich-text>` 节点数组；**不引第三方 md 库**（towxml 等过重）；不认识的语法原样当段落，宁可平淡不可吃字
  - 海拔曲线：canvas + `hidden` 控制（**禁 wx:if**，陷阱 #17）；数据 = elevation_profile 直接画，无值整块隐藏
  - 轨迹预览：map 组件 + polyline（preview_points），照 meetup-create 选路线的地图渲染模式**整链照抄**（README 地图绘制契约）：`utils/coords.js` 的 wgs84ToGcj02 转坐标 + `mapTheme.buildRoutePreviewPolylines` 出线 + wxml 绑 subkey/layer-style；ready=false 整块消失
  - 底部「发起约骑」按钮：ready=true 才渲染；本 task 只渲染按钮 + 占位 navigateTo（真预填接线归 T9，按钮 wx:if 条件先按 ready 写好）
- no-dash 判例全页生效：任何 null 字段整块 wx:if 隐藏

## 5. 测试用例

| # | 用例 | 断言 |
|---|---|---|
| 1 | 列表含 track_pending | ready=false 行返回，distance/climb/preview 为 null |
| 2 | 详情 ready=true | elevation_profile/preview_points/distance 有值，km 换算对 |
| 3 | 详情 ready=false | 三者全 null，content_md 正常 |
| 4 | highlights JSON 文本 | service 层 loads 成数组；空/null 不炸 |
| 5 | guide 404 | 不存在 id → 404 |
| 6 | 路由不冲突 | `/api/route-books/123` 与 `/api/route-guides/123` 各自命中（独立前缀） |

前端协议三层自校验 + track_pending 态/无封面空态在开发者工具各走一遍（截图进交付报告）。

## 6. 自检（commit 前）

- [ ] `rg -n "route-guides" app/main.py` → 已挂载
- [ ] `rg -n "wx:if" miniprogram/pages/route-detail/route-detail.wxml` → canvas 不在其中
- [ ] `rg -n '"-"' miniprogram/pages/route-list/ miniprogram/pages/route-detail/` → 零占位符
- [ ] pytest 全套绿
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.7+§4 逐条对照过吗

## 7. commit 指令

```
feat(route_book): S14-T8 路线百科双端点 + 列表/详情页
```

</details>
