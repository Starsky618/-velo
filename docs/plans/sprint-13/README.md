# Sprint 13+14 上线冲刺 · 实施计划

> 上游：`docs/spec-v6.md`（v6.4，四轮双审 Critical=0）+ `docs/prd/sprint-13-launch-prd.md`（Tim 12 条 y/n 全 y，2026-06-11）。
> **spec 是单一真相源**：task 卡是 spec §7 的执行展开，卡与 spec 冲突时以 spec 为准，且必须先改文档再改代码。
> 子 agent 纪律：启动时只读本 README + 自己那张 task 卡，**禁止读其他 task 卡**（防跨任务风格污染）。

## 任务总览

| 任务 | 核心交付 | 估时 | 建议通道 |
|---|---|---|---|
| T1 关联 | meetup_activities 表 + 独立迁移 + attach tick + bj_time 共享模块 | 1.5 天 | Codex 写 + Claude 双审 |
| T2 开奖 | upload 页按 demo 重做 + fit 后缀 + 双端点 800ms 轮询 | 2 天 | Codex 写 + Claude 双审 |
| T3 分享 | meetup-detail 预拉 reportStats + onShare 同步钩子 + source 参数 | 0.5 天 | Codex 写 + Claude 双审 |
| T4 战报 | GET /api/meetups/{id}/report + pages/meetup-report + 详情入口按钮 | 1.5 天 | Codex 写 + Claude 双审 |
| T5 埋点 | get_meetup 加 source 参数 + SENSOR view 行 + 数据回看查询 | 0.5 天 | Codex 写 + Claude 双审 |
| T6 部署 | 部署核实 + 真用回归（FIT 端到端 / share_token 真演 / 延迟实测） | 1 天 | 主 agent 亲自（生产操作） |
| T7 灌库 | route_guides 表 + is_official 列 + 灌库脚本 + 13 条内容转换 | 2 天 | 脚本派 Codex；**内容转换主 agent 亲自**（spec 风险 5） |
| T8 路线页 | /api/route-guides 双端点 + pages/route-list + route-detail | 1.5 天 | Codex 写 + Claude 双审 |
| T9 双入口 | route-books official 过滤 + 向导官方组 + 详情页路书预览 | 1 天 | Codex 写 + Claude 双审 |

## 执行序与依赖图（spec §7）

```
T1 关联 ──┬→ T2 开奖 ──┐
          ├→ T3 分享 ──┼→ T4 战报 ──→ T6 部署核实（S13 收口 / 上线门之一）
          └→ T5 埋点 ──┘
T7 灌库 ──┬→ T8 路线页 ──┐
          └→ T9 双入口 ──┴→ 上线（T6 + T8 + T9 全收）
```

- T1 是 S13 一切的地基（表 + tick），不许并行抢跑。
- T2 / T3 / T5 在 T1 后并行；T4 收口 S13 前端；T6 是 S13 与生产之间的桥。
- T7→(T8,T9) 是独立的 S14 线，可与 S13 线并行推进。
- **上线点 = Sprint 14 收尾**（PRD：顺序不可反，13 的开奖与战报得先存在，14 才开闸放人进来）。

## 全局约定（10 条，每个执行 agent 必守）

1. **中文注释**，零基础讲课风格（设计思路 + 类比，CLAUDE.md §3.3）；重要新文件头三句话（干啥用 / 注意事项 / 输入输出）。
2. **技术栈硬约束**：FastAPI 同步模式禁 `async def`；SQLAlchemy 2.0 同步 session；DB 存米、API 返 km（service 层转换）；分页 `page`+`page_size`。
3. **TDD 红→绿 A 档**：新业务逻辑测试先行；最后补跑 pytest ≠ TDD。
4. **起手 re-grep**：卡内"已验证事实"标注的 file:line 以执行时 re-grep 为准（判例：phase5 task 卡 grep 数据普遍 stale）；发现偏差先列给主 agent 再动手。
5. **边界纪律**：只做卡上写的，不顺手优化；新功能放新表/新模块，禁碰核心表（users/activities/segments/segment_efforts）。
6. **风险分层审查+门禁**（每 task commit 前 / 2026-06-11 Tim 拍，替代原三审默认全跑）：常规批次（T2/T3/T5/T8/T9）= 1 道 reviewer-integration 集成审 + pytest 全套 + pre-commit 门禁；高危批次（T7 迁移+灌库 / T4 隐私门禁路径）= 双审 + Codex 异源照旧。Critical/Important 当下修不留 follow-up；机械修复且 pytest 绿则不跑复查轮。
7. **每任务单独 commit**：`feat(模块): S13-TN 描述` / `feat(模块): S14-TN 描述`；commit ≠ ship（部署统一 T6 收口，S14 随上线部署）。
8. **陷阱必扫**：#1 truthiness（Boolean 查询 `.is_(True)`）/ #2 naive-aware datetime（SQLite fixture 返 naive）/ #17 canvas 禁 wx:if 用 hidden / no-dash 判例（缺字段 wx:if 整块隐藏，禁止 "-" 占位）/ IntegrityError try-except 是项目冲突惯例（禁 ON CONFLICT）。
9. **依赖方向**：`app/meetup/cron.py` 禁止 import segment（历史双向债不加深，spec §3.9）；任何新增反向依赖一律禁止。
10. **日志带实体 ID**；五环节埋点统一 `"SENSOR "` 前缀（D8），不建事件表。

## 跨任务契约（符号索引）

**新增 DB（归属任务）**
- `meetup_activities` 表 / `MeetupActivity` / `uq_meetup_activity` / `uq_meetup_user_one_cell` / `idx_meetup_activities_meetup` → T1；迁移 `migrations/versions/20260611_meetup_activities.py`（down_revision = `"20260603_meetup_create_fields"`——这是 **revision 串不是文件名**，链末文件实际叫 `20260603_meetup_create_prototype_fields.py`，别照文件名写）
- `route_guides` 表 / `RouteGuide` + `route_books.is_official` 列 → T7；迁移 `20260612_route_guides.py`（down_revision = `20260611_meetup_activities`）

**新增模块 / 函数（归属任务）**
- `app/common/bj_time.py`：`BJ_TZ` / `to_bj_date()` → T1（T1 内 blocking：先建模块再改 cron）
- `app/meetup/cron.py`：`ATTACH_WINDOW_DAYS = 7` / `attach_meetup_activities(db)` / `run_meetup_attach_tick()` → T1
- **scheduler 真实路径 = 仓库根目录 `scheduler.py`**（不是 app/ 下，[✓ grep] 唯一插入点 = `scheduler.py:55` if 块内 complete 之后，import 行在 `scheduler.py:22`）→ T1

**新增 API（归属任务）**
- `GET /api/meetups/{id}/report` → `MeetupReportOut` → T4（门禁复用 `service.get_meetup_detail` 整链，禁止另写）
- `GET /api/meetups/{id}` 加 `source` 参数（仅日志） → T5
- `GET /api/route-guides` + `GET /api/route-guides/{id}` → `RouteGuideOut` → T8（独立子前缀，避开 route_book 通配路由）
- `GET /api/route-books?official=1` → T9

**新增页面（归属任务）**
- `pages/meetup-report`（T4，不注册 tab / 不进首页导航——这是 PRD 验收项）
- `pages/route-list` / `pages/route-detail`（T8）

**跨任务参数契约（两端都要遵守）**
- upload 页新增可选启动参数 `meetup_id` + `token`：T4 的灰格「交卷」按钮产生 → T2 消费（页首约骑横幅 + 成绩卡分享走战报路径）
- 分享 `source` 值域：`share_card`（约骑详情卡 / 创建完成卡）/ `report_card`（成绩卡 + 战报页自身）/ `direct`（默认，T5 埋点用）
- **avatar 字段定案**：users 表字段是 `avatar_url`（[✓ grep] `app/user/models.py:45`），cells 用 `avatar_url` 沿用 `InviteeSummary` 惯例（spec §4 已预留"以 users 模型预读为准"）
- **降级契约**：T2 / T3 对 `GET /api/meetups/{id}/report` 的预拉请求若 404 / 失败 → `reportStats = null` 降级（标题退化为纯约骑名，不显示 m/n，防 undefined/undefined）——spec §3.3 已授权，T4 上线后自动恢复

**汾河闸门（T7 硬约束）**：汾河 3 版定本待 Tim 拍板（推荐最新「环太原汾河自行车道」版）；拍板前 T7 只灌其余 12 条，**未决决策不进实施**。

## 风险分层审查 + 门禁 SOP（每 task 收尾必跑 / 2026-06-11 Tim 拍）

1. 实现完 → pytest 全套绿 → 主 agent **亲读 diff**（不只看 subagent 报告）。
2. **常规批次**（T2/T3/T5/T8/T9）：派 1 道 `reviewer-integration`（grep 实证跨模块影响 / 反向依赖 / 配套联动 / 测试盲区），读真 diff 不读"已修复"声明。
3. **高危批次**（T7 迁移+灌库 / T4 隐私门禁路径）：双审（reviewer-spec-faithful + reviewer-integration）+ Codex 异源（`agent-collaboration.md §4 场景 B` 模板）。
4. Critical / Important 当下修；机械修复且 pytest 绿 → 不跑复查轮 → commit（>300 行响铃，审查留痕写 commit message footer）。
5. 终审 = T6 真用回归 + 上线 4 周数据；真用抓到"原双审会抓的事故" → 收紧回旧制（`docs/agent-rules/retired-rules.md` 有全文）。
6. 跳过场景仅限：纯文档 / 单文件 <50 行（理由写进 commit message）。
- T1 已按旧制完成（双审 5I 全修 / 实证账本来源），不回溯。
