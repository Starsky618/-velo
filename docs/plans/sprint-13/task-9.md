# Sprint 14 Task-9 — 路线转约骑双入口（预填 + 向导官方组 + 详情路书预览）

> 所属：Sprint 14 路线百科上架 / 第 3 个 task / 上线点收口件之一。
> 上游：`docs/spec-v6.md` §3.7 / D6；PRD 任务预览 #9。
> 前置门：T7 已 commit（is_official 字段就位）。与 T8 并行（按钮接线处依赖 T8 页面存在，联调在两者都 commit 后）。

---

## ─────── 给 Tim 看 ───────

### 干啥用

把"看路线"和"约人骑"接成一条路：路线详情页底部点「发起约骑」，创建向导自动选好这条路线；创建向导的选路线步里多一个"官方路线"分组；约骑详情页能看到路书预览图——收到邀请的人不用问"走哪条"。

### 用户故事

老张看完天龙山西线的介绍页，热血上头，点底部「发起约骑」——创建向导打开，路线已经选好是天龙山西线，他只填时间和集合点。发出去的约骑，朋友点开详情页直接看到轨迹预览图。

### 怎么算做对了

- ✓ 路线详情「发起约骑」→ 创建向导路线步已预选该路线。
- ✓ 创建向导选路线步出现"官方路线"和"我的路书"两组。
- ✓ 约骑详情页嵌路书预览地图（之前没有）。
- ✓ route_book_id 一路透传不断链（路线详情 → 向导 → 约骑 → 详情预览）。

### 这次不做

- 不在后端合并"官方+我的"为一个接口（前端两次调用分组渲染，spec 定案）。
- 不动 route_books 之外的查询逻辑。

### 估时

1 天。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/spec-v6.md | sed -n '184,192p'                # §3.7
rg -n "def list_route_books|official" app/route_book/service.py app/route_book/router.py
sed -n '230,260p' miniprogram/pages/meetup-create/meetup-create.js   # restoreRoutePreview（移植源）
rg -n "route_book_id" miniprogram/pages/meetup-create/meetup-create.js | head
rg -n "map|polyline" miniprogram/pages/meetup-detail/meetup-detail.wxml | head   # 预期为空（详情现无预览）
```

已验证事实（2026-06-11 主 agent grep）：
- `restoreRoutePreview(routeBookId)` 在 meetup-create.js:248，草稿恢复时按 id 拉路书并 setData 预览 [✓ Read]——约骑详情页的预览**移植此函数模式**
- meetup-detail 现无任何地图/路书预览 [✓ spec §0.1 + PRD grep 实证]
- route_books 列表端点现状无 official 过滤（T9 加）；`is_official` 列由 T7 建，查询**必须 `.is_(True)`**（D6 防 truthiness，陷阱 #1）

## 2. 文件改动清单

- Modify `app/route_book/router.py`：`GET /api/route-books` 加 `official: bool | None = Query(None)` 透传
- Modify `app/route_book/service.py`：list 函数加 official 过滤分支
- Modify `miniprogram/pages/route-detail/`：「发起约骑」按钮接真线 → `navigateTo /pages/meetup-create/meetup-create?route_book_id=X`
- Modify `miniprogram/pages/meetup-create/meetup-create.js`：① onLoad 读 `route_book_id` 参数 → 预选路线 + restoreRoutePreview ② 选路线步加官方组（第二次调用 `?official=1`，两组渲染）
- Modify `miniprogram/pages/meetup-create/meetup-create.wxml`：路线步两分组结构
- Modify `miniprogram/pages/meetup-detail/`：嵌路书预览（meetup.route_book_id 非空时 map+polyline，移植 restoreRoutePreview 模式；无路书整块消失）
- Create/Modify `tests/test_route_books_official_filter.py`
- **Do not** 改 route_books 写路径 / **Do not** 后端合并双组 / **Do not** 动 segment 下拉旧逻辑

## 3. 行为契约

### 3.1 后端 official 过滤

```python
# service 层（陷阱 #1：Boolean 查询必须 .is_(True)，禁止 == True / if 直接当真值）
query = db.query(RouteBook)
if official is True:
    query = query.filter(RouteBook.is_official.is_(True))
elif official is False:
    query = query.filter(RouteBook.is_official.is_(False))
# official is None → 不过滤，现有调用方行为不变（向后兼容）
```

router：`official: bool | None = Query(None)`；现有调用方（不传参）行为零变化——这是集成审的关键断言。

### 3.2 前端三处接线

- **预填**：meetup-create onLoad 读 `options.route_book_id` → 有值时拉该路书详情 → setData 选中态 + `restoreRoutePreview(routeBookId)` → 用户落在"路线已选好"的向导第一步（现有草稿恢复路径已验证此模式可行，照抄）
- **官方组**：选路线步并行两次调用——`GET /api/route-books?official=1`（官方组）+ 现有"我的路书"调用；两组分别渲染，组标题「官方路线」「我的路书」；官方组为空时整组隐藏（上线初期就有 T7 灌的数据，但代码要容忍空）
- **详情预览**：meetup-detail onLoad 后若 `meetup.route_book_id` 非空 → 拉路书 preview_points → map 组件 polyline 渲染（样式抄 meetup-create 预览）；route_book 已被删（SET NULL 孤儿态）→ 整块消失，不报错

## 4. 测试用例

| # | 用例 | 断言 |
|---|---|---|
| 1 | ?official=1 | 只返回 is_official=True 的路书 |
| 2 | 不传 official | 全量返回（现有行为不变——集成回归） |
| 3 | ?official=0 | 只返回用户路书 |
| 4 | 过滤写法 | service 源码用 `.is_(True)`（grep 断言） |
| 5 | route_book_id 透传链 | route-detail 按钮 path → meetup-create onLoad 读参 → 预览渲染，三段 grep 自校验贴报告 |
| 6 | 详情页孤儿路书 | route_book_id 指向已删路书 → 预览整块消失不炸 |

## 5. 自检（commit 前）

- [ ] `rg -n "is_(True)" app/route_book/service.py` 命中（D6 纪律）
- [ ] `rg -n "route_book_id" miniprogram/pages/route-detail/ miniprogram/pages/meetup-create/meetup-create.js` → 透传两端字段名一致
- [ ] 现有 meetups 流程回归：不带 route_book_id 打开向导，行为与改前一致
- [ ] pytest 全套绿
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.7 逐条对照过吗

## 6. commit 指令

```
feat(route_book): S14-T9 路线转约骑双入口（official 过滤 + 向导预填 + 详情路书预览）
```

</details>
