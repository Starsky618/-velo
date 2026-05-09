# 技术债务清单

> 项目 CLAUDE.md 防黑盒化机制 3："每期开工前做回溯体检"——新期 Spec 不允许依赖"还在 tech-debt 清单里"的功能，先修清理再做。

---

## 第 4 期遗留 P1（v5 Sprint 0 已全部清理 ✅）

> **2026-05-09 task-4.1 文档刷新时移除**：v5 Sprint 0 task 0.1-0.5 / 0.8 已闭环 5 项 P1。详见 `docs/changelog.md` 2026-04-29 起 Sprint 0 章节。

| # | 项 | 修复 commit |
|---|---|---|
| 1 | datetime 栈内不一致 | task-0.1 `4a94097`（5 表 12 列改 tz-aware + Python `datetime.now(UTC)`）|
| 2 | `ensure_valid_token` 行锁约束只在注释 | task-0.2 `022e2b1` + `db7e475`（签名改造 + populate_existing）|
| 3 | `ensure_valid_token` 未绑定用户路径 | task-0.3 `07327b1`（入口校验 + scheduler 兜底）|
| 4 | SQLAlchemy legacy `.get()` | task-0.4 `5e44c4f`（批量替换 8 处）|
| 5 | scheduler Redis 连接每次新建 | task-0.5 + 0.8 `04bb17d`（并入 app/queue.py 单一源）|

---

### 来源：生产部署缺陷（CLAUDE.md 已有条目）

已在主 CLAUDE.md "已知部署缺陷"小节记录：
- OAuth callback 可重复创建 strava_imports（本期 task-7.3 已修）
- ~~无 scheduler 容器~~（本期 task-7.9 将修）

### 来源：task-1.A.2 完工（2026-04-30 双主驾首战收尾）

**现状**：`app/segment/service.py` 792 行，超红灯 600。

**性质**：本期新增三个函数（`get_my_effort_with_compare` / `create_segment_from_activity` /
`get_segment_list` 扩展）职责均属"赛段操作"，与现有 8 个函数同模块语义一致，
**职责单一不强制拆**（CLAUDE.md §代码健康度自动巡检"红灯：先评估职责是否统一"）。

**和第 4 期 service.py 727 行红灯条的区别**：那条点的是 strava service.py（OAuth/token/sync），
这条点的是 segment service.py，两者无关。

**下期动作**（性价比中 / Sprint 2 完工后再评估）：
- 拆 `app/segment/service.py` → `service.py`（核心 CRUD）+ `effort_service.py`（即时反馈/排行榜）+ `admin_service.py`（from-activity 等 admin 专用）
- 触发条件：再加 1 个函数超 850 行 / 或 task-1.A.3 router 完工后看依赖收敛情况

---

### 来源：task-1.C.1 收尾遗漏（2026-05-03 codex 异源审 task-3.A.1 时发现）

**现状**：`app/middleware/__init__.py` + `app/middleware/rate_limit.py`（共 ~8500 字节）
作为 untracked 文件存在于 working tree（创建时间 2026-04-30 task-1.C.1 飞书告警时期），但：
- 从未 commit 进任何分支（`git log --all --oneline -- app/middleware/` 返回空）
- 没有任何项目代码 import（grep `from app.middleware` 无结果；
  `main.py` 那行 `fastapi.middleware.cors` 是 FastAPI 内置库无关）
- `rate_limit.py` 含 httpx + 飞书 webhook 调用 + Redis 限速逻辑

**性质**：Sprint 1 task-1.C.1 monitor 软目标可能漏 commit 的代码 / 或写完后被否决但未删

**影响**：
- working tree 持续 noise，未来任何 codex 异源审都会重新抓一次
- 对 Sprint 3 commit 流程的实际风险：`git add .` 类宽范围 add 会误纳

**下期动作**（待 Tim 单独裁决三选一）：
- A. 补 Sprint 1 commit（先评审 7344 字节代码质量）
- B. 删除（如果当时被否决）
- C. 暂保 untracked（task-3.A.1 commit 时 Tim 拍此路径，本条登记后维持原状）

---

### 来源：task-0.7 收尾遗漏（2026-04-30 dev stack 验证发现）

**现状**：commit `01caa5e` 改 `scripts/backfill_phase5.py` 用
`select(Segment.reference_line).where(...).scalar_subquery()` 解决 EWKB hex 字符串
被误当 WKT 解析，但 `tests/test_backfill_phase5.py` 的 `_FakeSegment` mock 类
未同步加 `reference_line` 类属性 → 2 测试持续失败。

**影响**：
- `test_backfill_segments_updates_each_segment_and_commits_once`
- `test_backfill_segments_keeps_going_when_one_segment_fails`

**性质**：fix-then-fix（hot-fix 后测试 fixture 漏同步），生产 backfill 已实证 24/24
回填成功（commit `daf6f1f` + `01caa5e`），所以 mock 测试失败不代表生产逻辑挂。

**下期动作**（性价比低 / 可推迟）：
- 给 `_FakeSegment` 加 `reference_line = Mock()` 或改测试用真 PG fixture（更稳但慢）
- 或者评估把 backfill 测试整体迁到集成测试（dev stack 已就绪）

---

### 来源：task-3.A.4 批量管理 endpoint 收尾（2026-05-04 Claude 复审）

**现状**：
- `tests/test_admin_router.py` 759 行红灯（>600），混合 4 个 endpoint domain：
  segment delete / curation_pool / ai_drafts / admin_segments。
- `app/admin/service.py` 353 行黄灯（>300），混合 3 个 admin 子领域：
  pool / draft / segment admin。

**性质**：
- 当前职责仍集中在 admin 模块内，task-3.A.4 不顺手拆，避免把功能交付和测试结构治理混在一起。

**触发条件**：
- task-3.A.5 已把 from-activity 新测试放到 `tests/admin/`，避免继续撑大
  `tests/test_admin_router.py`；下一次 admin endpoint 系列继续膨胀时，升级为拆分任务。

**下期动作**：
- 拆 `tests/test_admin_router.py` → `tests/admin/test_curation_pool.py` /
  `tests/admin/test_ai_drafts.py` / `tests/admin/test_admin_segments.py`。
- 同步评估 `app/admin/service.py` 拆成 pool / draft / segment admin 子模块，保持 router 编排层不变。

---

### 来源：task-3.B.1 D.3 admin 草稿 reject 后 human_edited_text 残留（2026-05-05 集成审 reviewer 提出 / 超出 D.3 范围）

**现状**：admin 编辑过草稿（写入 human_edited_text / status 自动转 human_edited）→ reject 时 backend 只改 status='rejected' / **不清 human_edited_text**。运营之后再 PATCH status='approved' 时，backend service.py:215 把残留的旧 human_edited_text 同步到 segments.description → 写入"已被运营丢弃"的旧文案。

**真实业务影响**：
- 运营场景：admin 编完决定 reject → 改主意再 approve → 旧编辑稿被静默发布到赛段介绍
- D.3 前端 reject 走 `{ status: 'rejected' }` 不传 human_edited_text → backend 保留旧值 → 已是 D.3 工作流默认行为（前端不能在 reject 时清，因为 backend schema `human_edited_text?: string` 没有显式 null sentinel）

**性质**：backend schema 演进任务 / 非 D.3 范围

**下期动作**（Sprint 3 收尾或 Sprint 4 起手）：
- 选项 A：`AiDraftPatchRequest.human_edited_text` 改为 `Optional[str | None]` + 显式 sentinel（如 `Field(... description="None=保留 / 空字符串=清空")`）/ 前端 reject 时显式传 `human_edited_text=""`
- 选项 B：backend service.py:196-230 在 status 切到 rejected 时自动清 human_edited_text（保守）
- 选项 C：admin H5 reject 时 modal.confirm 加"是否同时清空已编辑稿？"二选项

**优先级**：低 / Sprint 3 admin 工具内部低频场景 / 真踩才修

---

### 来源：task-3.A.6 admin from-gpx + Hausdorff 共享 helper（2026-05-05 reviewer 第二轮主动建议）

**现状**：commit `1432fad` 加了 `_check_hausdorff_overlap(db, wkt)` 共享 helper（含 dialect 守卫），from-gpx + from-activity 两条创建路径都走 helper。但**所有相关测试都用 mock**（admin 套件惯例）→ 真 Hausdorff 行为没在 SQLite 单元测试覆盖（守卫让 SQLite 跳过，无法在 SQLite fixture 验"重叠时抛 SegmentOverlapError"）。

**影响**：
- 生产 PG 真行为在 commit 时没有真实证（dev stack 真 PG 集成测试缺）
- 万一未来 helper 内部 SQL 写错 / 阈值调错 / 字段名漂移，单元测试都看不出来

**性质**：单元测试 mock 充分 / 但缺集成测试一层

**下期动作**（Sprint 3 收尾建议）：
- dev stack 真 PG 启动 + admin POST 同样 GPX 两次 → 第一次 201 / 第二次 409
- admin POST from-activity 同样 segment → 同样验
- 若纳入 CI / 评估 testcontainers + 真 PG fixture，统一 admin 套件真路径覆盖

### 来源：Sprint 1+2+3 部署后真用回归 — 产品观察 backlog（2026-05-06 Tim admin H5 真用 + Strava 绑定后反馈）

> **性质**：产品 feature 决策 / 非技术债 / 不阻塞 Sprint 4 排期 / Sprint 5+ PRD 时优先考虑。

**P1.PROD-1「不是所有赛段都适合加介绍」**（功能开关 / admin 审稿状态机）
- 现状：admin H5 草稿审核只有「通过 / 拒绝」/ 拒绝后 segment.description 依然空 / 但 admin 没法表达「永久跳过 / 不再生成」
- 未来方向：审稿状态机加「skip」状态 → segment.description 永久空 / 不再 enqueue AI 重生

**P1.PROD-2「AI 介绍很假 / 没特色 / admin 还得自己写」**（AI 输出质量 / 2026-05-06 重新定义）
- 现状：DeepSeek prompt 只喂 metadata（坐标 / 距离 / 爬升 / 难度）+ 调性要求 / 没真实"地气"输入
- 本质：metadata 写不出特色 / 活人感来自人 / AI 退化为格式补全工具

### AI 角色重定义（2026-05-06 Tim 真用 + 7 条改写洞察）

读 Tim 7 条 approved 改稿（segment_id 6/8/9/10/20/21/22）/ 提炼出**他的独家武器**：

1. **致命点警告**（事故 / 安全）—— "已发生多起车祸事故！且旁边就是悬崖" / "切记提前减速！不可逆行" / "经常有汽车或摩托越线行驶"
2. **实用补给情报** —— "终点旁边有补给，可买水、面皮和夹肉饼，约 10 元" / "藤原豆腐店（三岔路口左转上陡坡 500 米 / 平均 10%）"
3. **跨 GEO 社交基准** —— "横岭被戏称为'太原妙峰山'" / "进阶爬坡手 45 分钟大关 / 40 分钟以内是…" / "整体强度类似北京戒台寺"

**这三类 AI 永远编不出**：实地骑过 + 当地骑友口述 + 跨 GEO 横向语义网。AI 写出"教你做人""断腿前的最后一哆嗦""骨科预备役"语言节奏好但**全是空梗**（无真实事故 / 无补给 / 无基准）。

**重新定义**：
```
Tim（人）= raw material 来源（实地 + 当地圈子 + 网络评价 + 微信聊天记录）
AI       = 格式编辑器（不生成内容 / 只把散乱情报结构化 + 节奏化）
```
类比：Tim 是**现场记者** / AI 是**美编**。两者互补 / 不替代。

### 形态 B 详细设计（Tim 2026-05-06 拍 / 待 Sprint 5+ PRD）

**核心**：建 `segment_facts` 表存 raw 情报点 / AI 拼装时引用 / 事实可追溯到来源。

**Schema 草案**：
```sql
CREATE TABLE segment_facts (
  id SERIAL PRIMARY KEY,
  segment_id INT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  fact_type VARCHAR(20) NOT NULL CHECK (fact_type IN (
    'safety',      -- 致命点 / 事故警告
    'supply',      -- 补给点 / 商家 / 价格
    'benchmark',   -- 时间基准 / 跨 GEO 对标
    'history',     -- 历史 / 文化梗
    'condition',   -- 路况 / 季节性 / 时段
    'misc'
  )),
  content TEXT NOT NULL,
  source VARCHAR(20) NOT NULL CHECK (source IN (
    'admin_field',     -- Tim 实地骑过 / 朋友讲述
    'user_comment',    -- segment_efforts 评论
    'web_scrape',      -- 小红书 / 微博 / 抖音 / 知乎爬虫
    'wechat_log'       -- 微信聊天记录手工 ingest
  )),
  source_ref TEXT,         -- 来源 URL / 用户 ID / 聊天截图路径
  weight INT DEFAULT 1,    -- 权重（admin_field 权重高 / web_scrape 低）
  created_at TIMESTAMPTZ DEFAULT now(),
  is_active BOOLEAN DEFAULT TRUE  -- admin 可关闭过时情报
);
```

**AI 拼装 prompt 设计原则**：
- 不让 AI 自己**编**安全警告 / 补给详情 / 时间基准（这三类必须**只**从 segment_facts 引用）
- AI 只负责：组织顺序 + 段落分层 + 节奏润色
- prompt 模板大致：
  ```
  这条赛段的 metadata：{distance}/{elevation}/{difficulty}/{city}
  本地实测情报（必须保留 / 不可删 / 不可改事实）：
  - 致命点：{safety_facts}
  - 补给：{supply_facts}
  - 时间基准：{benchmark_facts}
  - 历史 / 梗：{history_facts}
  请把上面情报组织成 100-200 字的段落 / 节奏自然 / 不堆砌 / 致命点放显眼位置。
  ```

**数据来源演进**：
1. **短期（Sprint 5）**：admin H5 加 `segment_facts` CRUD UI / Tim 自己录 + 录的同时 AI 自动拼装 description
2. **中期（Sprint 6+）**：用户骑完 segment 在 segment_efforts 写评论 / admin 审核高质量评论标 fact_type 入库
3. **长期（Sprint 7+）**：网络爬虫（小红书 / 抖音 / 微博 / 知乎）+ LLM 语义提取 fact / admin 审入库
4. **最长期（Sprint 8+）**：微信聊天记录手工 ingest（隐私敏感 / 性价比待评估 / 可能不做）

**与 PROD-3 的关系**：PROD-3「信息源不全」是"raw material 哪里来" / PROD-2 形态 B 是"raw material 怎么用"。两者**配套**——PROD-3 解决供给端 / PROD-2 解决消费端。

**为什么不现做**：
- 当前 v5 admin H5 已经能让 Tim 手工写 description（活人感真情报已能进库 / 7 条实证）
- 形态 B 是 scale 时的事（赛段 50 → 500 时手工写不动 / 才需要拼装机制）
- 50 条规模手工写 OK / 500 条才需 AI 辅助拼装

**触发条件 / 何时升级**：
- 候选池 selected 数量 > 50 / 手工写吃不消时
- 或 Tim 觉得"raw material 多了 / AI 拼装比手写省力"时

**P1.PROD-5「活动列表索引筛选 / 像 Strava 按日期/距离/时长筛」**（UX + endpoint 扩展 / 非架构）
- 现状：home.js 列表已支持加载更多（v5 commit / onReachBottom 翻页）/ 但**没有筛选**
- 痛点：用户活动量大（实证 user_id=2 已 325 条 / 部分骑友更多）/ 翻页找老活动效率低
- 未来方向（待 Sprint 4-5 PRD）：
  - 后端：activity router 加 filter 参数（start_date_from/to / distance_min/max / duration_min/max）
  - 前端：筛选弹窗 / 日期 picker / range slider / chip 选择
- **配套硬规则**（写进未来 PRD 时考虑）：扩前端列表能力时（活动 / 排行榜 / 通知）应**统一引入分页 + 筛选模式** / 不要每页单独发明轮子（避免重复设计 + 用户体验割裂）

**P1.PROD-3「信息源不全 / 需要小红书 / 抖音 / 微信聊天记录」**（数据基础）
- 现状：admin 自己骑过 + 朋友讲述（Tim 当前的方式）/ 手头信息有限
- 三层未来方向：
  - 短期：用户在 segment_efforts 写评论 / 项目内已有路径可补
  - 中期：小红书 / 抖音 API 公开内容爬取 + LLM 语义提取
  - 长期：微信聊天记录手工 ingest（隐私 + 操作复杂 / 性价比待评估）

**下期动作**（Sprint 4 / 5 PRD 时评估）：
- A 三点 PROD-1/2/3 优先级排序（性价比 vs 当前痛点）
- B 是否合并出 'phase-N AI 草稿 v2' PRD：跳过状态 + 风味词补充 + 评论 RAG 一次性设计

---

## P2（远期）

### 前端相关
- 小程序 web-view 业务域名白名单未配（task-7.10 临时用剪贴板+模态过渡）
- 积分 + 骑行等级系统（spec §9.5，用户活跃度达标后启动）
- 微信服务消息推送（spec §9.3，独立大任务）

### 后端相关
- N+1 查询（排名计算循环发 SQL）—— 代码已标 TODO；**v5 task-4.2 已修 power-curve N+1（24s → 1-2s）/ 排名循环未修**
- trackpoints 表无分区策略（百万级用户后要加）
- ~~service.py 单文件 727 行~~ ✅ 已解决（task-pre-3.B / 2026-05-05 拆分为 service.py 189 + service_create.py 257 + service_query.py 380 / 详 commit）

---

## 来源：v5 Sprint 4 task-4.2 v3 polish 遗留（2026-05-09）

### D33 map matching（v5 真闭环 6 hotfix 链遗留）

**现状**：heatmap 山区赛段（如太原西山片区）有真物理 GPS 误差散网——单 segment >500m 跳点 1263 条。task-4.2 v3 polish 用"分层虚实线 + simplify 1500 + backfill"hack 修了 65%（1263 → 443 / 中位数 30m → 21m），但根本问题是 GPS 物理误差不是软件能完全修的。

**未来方向**：
- A. OSRM 容器（开源 / 自建 / 用 OpenStreetMap road network）/ trackpoint 喂进去 snap 到最近道路
- B. 高德 navigation match API（国内合规 / 速度快 / 但要 API 配额）
- 工程量 1-3 天 / 性价比中

**触发条件**：Sprint 5/6 跟 D28 高德 webview（探索 tab 用高德地图渲染）一起做 / 不单独立项

**优先级**：低 / 当前 hack 已让 90% 用户满意 / 真根治留 v6+

### tied PR my_rank off-by-one（D7 双 review I1）

**现状**：task-4.5 D7 真排名 hotfix（commit `33212a1`）给 LeaderboardResponse 加 my_rank + my_elapsed_time。算法基于 `(elapsed_time, created_at)` 排序，**tied PR**（相同 elapsed_time）场景下 my_rank 可能 off-by-one（用户看到第 4 实际是第 3-4 并列）。

**真实业务影响**：百级用户量 tied 概率 < 1% / 出现不影响数据正确性 / 视觉差 1 名

**下期动作**（跟 D33 一起补）：
- 主榜加 `(elapsed_time, effort_id)` 二级排序键 / effort_id 是单调递增 → 永远稳定 tie-break
- 测试加"两 effort 同 elapsed_time 不同 effort_id 的 my_rank 计算"边界

**优先级**：低 / 真踩才修

### 测试覆盖盲区 2 处（v3 polish ship 后批 review）

- worker hook 触发 invalidate_heatmap_cache 回归测试（heatmap city 改可选后双 cache key 是否真清）
- 无 city 精确 key 被清验证

**下期动作**：Codex --resume 时列下轮 backlog / 不阻塞当前 ship

---

## 来源：v5 PROD-2 AI 角色重定义（Tim 2026-05-06 真用 + 7 条改写洞察）

### 现状
admin H5 草稿审核生产真用 / Tim 改稿 7 条 approved（segment_id 6/8/9/10/20/21/22）/ 提炼三类"独家武器"AI 永远编不出：致命点警告 / 实用补给情报 / 跨 GEO 社交基准。

### 形态 B 详细设计已沉淀（见本文件上方"### 形态 B 详细设计"段）

### 触发条件
- 候选池 selected 数量 > 50 / 手工写吃不消时
- 或 Tim 觉得"raw material 多了 / AI 拼装比手写省力"时

### 优先级
中 / Sprint 5+ PRD 时考虑 / 当前 50 条规模手工写 OK

---

## 来源：v5 Sprint 3 task-3.A.4 admin 模块红灯（待再膨胀时升级）

### 现状
- `tests/test_admin_router.py` 759 行红灯（>600）/ 混合 4 个 endpoint domain
- `app/admin/service.py` 353 行黄灯（>300）/ 混合 3 个子领域

### 触发条件
- 下一次 admin endpoint 系列继续膨胀时（task-3.A.5 已把 from-activity 测试放 `tests/admin/` 部分缓解）

### 下期动作
- 拆 `tests/test_admin_router.py` → `tests/admin/test_curation_pool.py` / `tests/admin/test_ai_drafts.py` / `tests/admin/test_admin_segments.py`
- 同步评估 `app/admin/service.py` 拆 pool / draft / segment admin 子模块

### 优先级
低 / 当前 admin 系列稳定 / 真撑大再拆

---

## 清理节奏

> 每期 10-20% 时间处理 P1，P2 评估性价比再决定。
> 完成清理的条目从本文件移除并在 `docs/changelog.md` 记录一句。
