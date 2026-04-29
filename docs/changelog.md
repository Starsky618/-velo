# VELO 开发变更日志

## 2026-04-29 起 第 5 期：赛段内容深化 + 数据成长 + 个人页 + admin 工具（进行中）

### 启动期（2026-04-26 ~ 04-29）

- 战术 PRD `docs/prd/phase-5-prd.md` v0.4 完工（Tim 拍 11 yes 决策点）
- 技术 spec `docs/spec-v5.md` 2879 行，3 轮双审 Critical 14→8→3→0 收敛
- 实施计划 `docs/plans/phase5/` 29 张 task 卡 + README

### Sprint 0：地基修补（5-8 天）✅ 全部完成

| 任务 | 状态 | commit |
|------|------|--------|
| 0.1 datetime 全局 tz-aware | ✅ 三审通过 + alembic 真 PG 双向验证 | `4a94097` |
| 0.2 ensure_valid_token 签名改造 + populate_existing | ✅ Codex 异源抓陷阱第 12 条 | `022e2b1` + `db7e475` |
| 0.3 ensure_valid_token 未绑定路径 + scheduler 兜底 | ✅ | `07327b1` |
| 0.4 SQLAlchemy legacy `.get()` 替换 | ✅ | `5e44c4f` |
| 0.5 + 0.8 scheduler Redis 复用 + app/queue.py 单一源 | ✅（0.5 并入 0.8）| `04bb17d` |
| 0.6 v5 主迁移（segments + users + 2 新表）| ✅ Codex 异源抓 2 Critical | `91a3691` |
| 0.7 老数据回填脚本 + 生产部署 | ✅ 24 segments + 2 users 全部回填 / 双主驾首次互审 | `daf6f1f` + `01caa5e` |

### Sprint 1：赛段内容深化（5-7 天）⏳ 进行中

| 任务 | 状态 | 备注 |
|------|------|------|
| 1.A.1 segment 算法纯函数（max_gradient/difficulty/infer_city）+ common 包 | ✅ 41 测试 + Codex 异源抓 2 Critical | `a9c1bff` |
| 1.A.2 segment service 扩展（搜索 + 即时反馈 + from-activity）| ⏳ 下一个 | 计划"双主驾首战"——codex 主开发 + Claude 异源审 + 必跑命令 |
| 1.A.3 segment router 扩展 + 即时反馈 endpoint | ⏳ 待 1.A.2 完工 | - |
| 1.B.1 / 1.C.1 | ⏳ 待执行 | - |

### 2026-04-29 战略升级：双主驾协作架构 v2.0 ⭐

**触发**：task-0.7 部署链路暴露 6 个真实问题（mock ≠ 真环境 / 容器 rebuild 验证 / PAT 泄露 / progress_records 误报 / EWKB hex 字段 / 信息整流原则违反）→ Tim ↔ Claude 长讨论收敛 4 议题。

**落地（4 commits）**：
- `1bd15ec` `codex-division-of-labor.md` 改名 → `agent-collaboration.md` v2.0（660 行，从 Claude 中枢改为双主驾）+ CLAUDE.md 顶部加协作硬规则（信息整流 / 少增文档 / 动作 trigger 自查）+ 5 文件 11 处引用更新
- `a836637` `docs/README.md` §5.F 加升级路由表（教训类型 → 进哪份文档）
- `daafe62` changelog 加战略升级总结 + 明日交接桥梁
- `038dd5e` Tim 双重 push back 后立规则：CLAUDE.md 顶部加 §🧭 决策反向索引（7 类决策 → 必查规则）+ agent-collaboration.md §10.X 工作交接桥梁机制 + §12.X 规则成熟度原则（含 80% 高频例外）
- 3 条新 memory：`feedback_promise_must_action.md`（承诺必落实）/ `user_decision_style_defense_and_roi.md`（Tim 决策风格画像）/ `feedback_rule_system_entropy_risk.md`（第三阶熵增警觉）

**核心规则（4 议题决议，详见 agent-collaboration.md）**：
- **B 议题**：信息整流原则——给 Tim 用翻译层句式，禁止贴 raw diff；高风险动作硬 checklist；最低限度不确定度自报；动作 trigger 自查（mental check 4 问）
- **A 议题**：运行时验证门禁——动 DB / 外部 API / 文件系统类代码必跑命令，配本地 docker stack 替代频繁 SSH 生产
- **C 议题**：memory → 文档升级机制——半自动 + agent 自决目标 + 翻译层问 Tim
- **D 议题**：切换 trigger——按自然边界切 + 例外清单 + Tim 主权

### 待办（2026-04-30 起）⭐ 新 session 必读

1. **A 叠加 D 计划**：先配 `docker-compose.dev.yml` + 种子数据（30-60min Claude 主驾）→ 然后 task-1.A.2 派 codex 主开发 + Claude 异源审 + 在新 docker stack 必跑命令验证（首次实战双主驾架构）
2. ⏳ 待 Tim 触发：学 git 分支多线程开发 / 专题讨论"规则系统熵增"（第三阶问题）

### 关键决策

- LLM API 走 DeepSeek（OpenAI 兼容 SDK，Tim 2026-04-29 拍）
- 赛段目录公开访问 / 看他人主页默认公开 / AI 草稿 202 异步
- admin H5 独立部署（域名暂不买，先 IP）
- **agent 协作模式：双主驾 + 单一裁决链**（v1.x Claude-中枢 → v2.0 双主驾对称）

---

## 2026-04-17 ~ 2026-04-18 第 4 期：前端反馈环闭合 + Strava 集成加固

### 一、产品目标
把后端早就做好的成就数据（通知/荣誉/Strava 同步）真正送到用户眼前，顺手修 8 个 Critical + 11 个 Important 历史风险。

### 二、9 批闭环 + 双审制度（2026-04-17 晚 → 04-18 凌晨）

| 批 | 任务 | 主体改动 | 双审收获 |
|----|------|---------|---------|
| 7.1 | Alembic 迁移 + 4 model 改动 | is_read / activity_type / mute_notifications / updated_at tz / 外键 SET NULL | 上线后发现 conftest 遗漏，事后补 fix commit |
| 7.2+7.3 | OAuth state 加固 + callback 防重复 | Redis nonce GETDEL 一次性消费 / 7 步 callback 流程 / UNIQUE 检测先于 cleanup | 合并成单 commit（中间态会炸不可拆）|
| 7.4 | Webhook subscription_id 校验 | 双门校验（未配置 503 / 不匹配 403）| 老 webhook 测试需补 subscription_id mock |
| 7.5 | import-progress stalled + Redis 限速 | view_status 派生态 / 1s/user 限速 | 老测试契约迁移 |
| 7.6 | Strava 现有函数加固 | I7/I8/I9/I10：401 pause imports / 行锁 / 连续 2 次空确认 / 手动 sync 联动 | — |
| 7.7 | 解析器入口 activity_type 分流 | 抢锁后、下载前分流，省 I/O | — |
| 7.8 | mark-all-read + unread_count | service.mark_all_read + GET 加 unread_only / 响应永远带 unread_count + outerjoin Segment | — |
| 7.9 | scheduler 容器部署 | scheduler.py + docker-compose 加 7th 容器 | **集成审抓出 tier1_completed 无行锁 → SQL 原子表达式修复**（code-reviewer 没看到）|
| 7.10（瘦身）| 小程序前端通知反馈环 | 通知中心 + 荣誉页 + 红点 + 免打扰 + api.js 扩展（**砍 Strava 绑定 UI** 留第 5 期）| **集成审抓出 leaderboard.js 不读 segment_id → 反馈环断**（差点把核心目标交付一半）|

### 三、双审制度沉淀

第 4 期最大教训：**v1-v3 单 agent 模式 → v4 多 subagent 模式后我没及时同步纪律 → 批 1-6 跑完才发现没做"代码层双审"违反 CLAUDE.md 明文**。

事后双审一次抓 1 Critical + 6 Important（ORM/DB schema 不一致、重复 detect_events、非骑行活动 activity_type 错、行锁测试假通过等），证明双审硬性的价值。

**沉淀**：
- `~/.claude/skills/architect/SKILL.md` 信条 5 升级为"两处必做硬性"（spec 层 + 代码层），强调 prompt 互补
- `velo/CLAUDE.md` 顶部加 3 条硬规则：commit 前 4 问 / 任务规模预算（每期 ≤6 任务）/ 防火墙式扩展（新功能默认放新表）
- `velo/CLAUDE.md` 大瘦身 482 → 231 行（与 architect skill 重叠的方法论砍掉留指针）

### 四、规模数据

- 13 个 commit（含双审修复 4 个 fix commit）
- ~3500 行净增（后端 + 小程序 + 文档 + 测试）
- 50+ 新测试用例
- 全套：181 passed / 0 failed
- 工时：约 10 小时（含规划、双审、3 次重大反思）

### 五、留 P1 给第 5 期（详见 docs/tech-debt.md）

- datetime 栈内不一致（naive vs aware 全量迁移）
- ensure_valid_token 行锁约束封装（防绕过）
- service.py 727 行（红灯）拆分（OAuth / token / sync）
- handle_callback 7 步流程拆函数
- _run_tier1 拆 fetch / persist / progress 三步
- N+1 查询历史 TODO 清理

### 六、未做（明确推迟）

- Strava 绑定 UI（task-7.10 砍掉，留第 5 期）—— 当前用户走后台手动绑定
- 后端集成测试（mock 链路，单元测试已覆盖关键路径，价值低）
- 真实 Strava E2E（生产部署后做）
- 前端手工回归（部署后小程序开发者工具跑）

---

## 2026-04-09 ~ 2026-04-13 本轮开发总结

### 一、GCJ-02 → WGS-84 坐标系转换（04-09）
- **问题**：赛段创建接口 reference_points 无坐标系约定，腾讯地图坐标（GCJ-02）与 GPX 轨迹（WGS-84）偏移 100~700m，导致 50m 容差下匹配必然失败
- **修复**：新增 `app/segment/coord_convert.py` 纯函数模块，SegmentCreateRequest 增加 `coordinate_system` 字段（默认 gcj02），service 层自动转换
- **测试**：7 个转换测试（`tests/test_coord_convert.py`）
- 文件：`coord_convert.py`、`schemas.py`、`service.py`、`router.py`

### 二、赛段创建工具（04-09）
- **功能**：Strava 风格的管理员工具（`tools/segment-creator.html`），从 GPX 文件截取赛段
- **交互**：GPX 导入 → Chart.js 海拔剖面图 + 双滑块拖选 → Leaflet+OSM 地图联动 → POST /api/segments 创建或 JSON 降级下载
- **键盘微调**：点击"起点/终点"标签选中，← → 箭头每次 ±20m，长按连续调整
- **后端增强**：Segment 模型新增 `elevation_loss`、`avg_gradient`、`elevation_profile` 三个 nullable 字段；距离精度 1→2 位小数；`_geo_utils.py` 拆分避免 service.py 超 500 行
- **部署**：Caddyfile 新增 `/tools/*` 静态文件路由
- **测试**：4 个字段计算测试（`tests/test_segment_fields.py`）

### 三、本地 Docker 部署（04-12）
- **环境**：`docker-compose.dev.yml`（不含 Caddy），PostgreSQL+PostGIS / Redis / FastAPI / rq Worker
- **迁移**：Alembic 初始迁移脚本，清理 PostGIS tiger 内置表干扰，修复 geoalchemy2 自动空间索引冲突
- **配置修复**：`.env` 与 pydantic-settings 兼容（`extra="ignore"`）；端口冲突改用 5434；CORS 中间件允许跨域
- **验证**：24 条太原赛段 JSON 全部导入成功，上传 GPX 自动匹配 21 条赛段

### 四、Matcher 算法增强（04-13）
1. **独立端点容差**：`endpoint_tolerance` 与 `match_tolerance` 分离，起终点检测和覆盖率校验可独立调整
2. **Moving Time 自动暂停**：速度 + 时间双条件（连续低于阈值 ≥30 秒才扣除），阈值 0.5 km/h，避免误扣陡坡慢速骑行
3. **DELETE /api/segments/{id}**：管理员删除赛段接口，连带清除所有成绩记录
- 与 Strava 成绩对比验证：柴化线两条赛段误差缩至 9~16 秒

### 五、API 接入调研（04-10）
- Strava API：免费，2000 次/天，Webhook 推送，但条款限制数据缓存 ≤7 天
- Garmin API：免费基础接入，需企业身份申请，Push 模式秒级推送
- 行者：有官方开发者中心（XOSS 开放平台）
- 顽鹿/iGPSport：无官方 API
- **结论**：先接 Strava（秒批），同时申请 Garmin（用"共演纪"个体户身份）

### 当前状态
- 后端 API 功能完整，本地 Docker 端到端验证通过
- 24 条太原赛段已入库，匹配算法与 Strava 成绩误差 <20 秒
- 赛段创建工具可用（HTML 单文件，在线/离线双模式）
- **待做**：云服务器部署 → 微信小程序前端 → Strava API 接入

## 2026-04-09 赛段创建工具 + Segment 模型增强

### 新功能
1. **赛段创建工具**（`tools/segment-creator.html`）：Strava 风格的管理员工具，从 GPX 文件中截取赛段。功能：GPX 导入解析 → Chart.js 海拔剖面图 + 双滑块拖选 → Leaflet 地图联动 → POST /api/segments 创建 + JSON 降级下载。单 HTML 文件，CDN 依赖 Chart.js + Leaflet，部署在 Caddy /tools/ 路由下。

### Segment 模型增强
2. **新增 3 个字段**：`elevation_loss`（累计下降）、`avg_gradient`（平均坡度%）、`elevation_profile`（海拔采样 JSON，约 80 个值，供前端画 sparkline 缩略图）
3. **距离精度提升**：API 返回距离从 1 位小数改为 2 位小数（如 48.25 km）
4. **service.py 拆分**：`_haversine` 和 `_sample_elevation_profile` 提取到 `_geo_utils.py`，service.py 从 533 行降至 491 行

### 部署
5. **Caddyfile**：新增 `/tools/*` 静态文件路由

### 隔离验证
- app/activity/ 和 app/user/ 零修改
- 72 个测试全部通过（新增 4 个字段计算测试）
- 所有新 Segment 字段 nullable，向后兼容

## 2026-04-09 GCJ-02 → WGS-84 坐标系转换

### 问题
赛段创建接口（POST /api/segments）的 `reference_points` 没有坐标系约定。管理员从腾讯地图取的坐标是 GCJ-02（偏移 100~700m），而 GPX 轨迹点是 WGS-84。两套坐标在 matcher 里做距离计算时会偏移，导致 50m 容差下匹配必然失败。

### 修复
1. **新增 `app/segment/coord_convert.py`**：纯函数模块，GCJ-02 → WGS-84 转换，精度 <1m
2. **`SegmentCreateRequest` 新增 `coordinate_system` 字段**：`"gcj02"`（默认，腾讯/高德地图）或 `"wgs84"`（GPS/GPX 原始坐标）
3. **`service.create_segment` 集成转换**：在距离计算前调用 `convert_points_to_wgs84`，确保存入 PostGIS 的 reference_line 始终是 WGS-84（SRID=4326）
4. **新增 5 个测试用例**（test_21 ~ test_25）验证转换精度和边界情况

### Spec 偏离记录
- 原 spec 未提及坐标系，现在 API 层明确约定默认 GCJ-02 输入、内部统一 WGS-84 存储
- 向后兼容：不传 `coordinate_system` 字段默认走 GCJ-02 转换

## 2026-04-08 Alembic 迁移初始化 + Worker 超时保护 + 卡片天气字段决策

### 基础设施
1. **Alembic 初始化**：生成 `alembic.ini` + `migrations/env.py`，数据库地址从 `app/config.py` 统一读取。部署时执行 `alembic revision --autogenerate` + `alembic upgrade head` 即可生成并应用迁移。

### 功能增强
2. **Worker 超时保护（方案 A）**：`get_activity_status` 新增超时判断——activity 在 processing 状态超过 10 分钟时，自动标记为 failed 并提示"解析超时，请重新上传"。轻量方案，仅在前端轮询时触发，不引入额外基础设施。未来流量增长后可叠加定时扫描方案，两者不冲突。

### Spec 偏离记录
3. **v1 骑行卡片不显示天气**：spec 5.1 卡片设计包含 `22°C · 晴`，但 Activity 表无天气字段，前端获取天气也增加复杂度。决定 v1 卡片标题区仅显示日期（如 `2026.04.07`），天气留到 v2 按需添加。

## 2026-04-08 Task 4.5 排行榜接口 + 代码拆分

### 架构变更
1. **service.py 拆分**：自动匹配逻辑（`match_activity_against_segments` + `_parse_linestring_wkt`）从 `service.py` 拆到 `auto_match.py`。原因：service.py 达 468 行接近 500 行红线，新增排行榜函数后会突破。拆分后 service.py 410 行、auto_match.py 206 行。

### Spec 增强（向后兼容）
2. **排行榜 bike_type 字段**：`get_segment_detail` 的 TOP20 排行榜增加 `bike_type` 字段（来自 User 表）。Spec 原始定义无此字段，但 Task 4.5 的独立排行榜接口需要它，为保持一致性统一添加。不影响已有消费方（多返回一个可选字段）。

### 设计决策
3. **bike_type 过滤语义**：排行榜按 `bike_type` 过滤时，查的是用户当前车型（User 表），非骑行时车型。用户换车后历史成绩的车型会随之变化。MVP 阶段可接受。

## 2026-04-07 技术文档终版（v3 → 终版）

基于 ChatGPT 编写的 v3 技术文档，经 Claude 审查后修正 9 个问题：

### 严重修复
1. **ST_DWithin 单位错误**：PostGIS `geometry` 类型的 `ST_DWithin` 距离单位是度，不是米。所有空间查询加 `::geography` 转换
2. **缺少 HTTPS**：微信小程序强制要求 HTTPS。部署方案新增 Caddy 反向代理，自动 SSL 证书

### 功能修复
3. **距离单位不统一**：活动接口返回米、统计接口返回公里。统一为所有 API 返回公里
4. **时区未定义**：新增约定——数据库存 UTC，周期计算按 UTC+8
5. **GPX BOM 头**：上传校验增加 BOM 跳过处理
6. **活动标题不可编辑**：新增 `PATCH /api/activities/{id}` 接口
7. **路段创建无权限**：users 表增加 `is_admin`，创建路段需管理员权限
8. **JWT 无续期说明**：新增静默续期机制文档
9. **分页参数不一致**：统一为 `page_size`
