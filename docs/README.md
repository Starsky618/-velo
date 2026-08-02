# VELO 项目入口

> 这份 README 只做三件事：说明 VELO 现在是什么、当前代码和真实用户证据到了哪一层、不同任务应该从哪份文档进入。
>
> **最后校准：2026-07-28。** 代码事实核对到本机最新 `origin/main`；生产环境、微信体验版和管理后台本轮未重新验证。本文中的“有代码”不等于“已上线”。

---

## 0. 30 秒理解 VELO

VELO 是面向严肃公路车骑手的微信小程序和后端服务。当前小程序包含三组用户能力：

1. **骑行记录**：上传 GPX/FIT、Strava 同步、解析轨迹、生成活动数据与成绩反馈。
2. **路线**：浏览路线百科、手动画线或贴路、保存路书、重新打开、导出 GPX/TCX 给码表或码表 App。
3. **训练分析**：FTP、训练负荷和训练分布。

约骑后端 API、定时任务、数据库结构和历史数据继续保留运行，作为兼容面；小程序中的约骑 Tab、页面、路线入口、个人入口、上传联动和 API helper 已移除，不再向用户开放。

技术形态：

- 前端：微信小程序，入口在 `miniprogram/`
- API：FastAPI，同步 SQLAlchemy，入口在 `app/main.py`
- 数据：PostgreSQL 16 + PostGIS
- 异步任务：Redis + RQ worker / scheduler
- 本地编排：`docker-compose.dev.yml`
- 生产编排：`docker-compose.yml`

### 当前产品聚焦

截至 2026-07-25 的产品复核，主线不是继续扩功能，而是把两件事做实：

- **个人闭环**：骑手能独立完成“画线 → 贴路 → 保存 → 重开 → 导出 → 导入码表”，不依赖贡献数据、邀请别人或网络密度。
- **路线理解**：让一个不熟悉这条路的严肃骑手，准确看懂一条有方向的真实路线。

当前明确边界：

- 公共路线的“地图、坡型、照片/POI 在同一里程位置互相对应”仍未完成，也没有陌生骑手验证。
- 页面和导出使用同一份海拔剖面，只能证明**表达一致**，不能证明**绝对海拔准确**。
- 暂停继续扩大海拔 R&D；Activity 贡献治理、网络密度机制和新实体扩张不进入当前主线。
- 约骑不进入当前产品前端；后端只为保护历史数据和降低一次性删除风险而保留，不代表仍在投入或对用户可用。

产品方向若发生新拍板，应先改本节，再改后续 PRD 或计划，避免旧战略叙事继续冒充当前结论。

---

## 1. 当前状态：代码、真用和上线必须分开

| 能力 | 仓库代码 | 真实使用证据 | 当前边界 |
|---|---|---|---|
| GPX/FIT 上传与活动解析 | 已存在于 `app/activity/`、`app/parsing/` 和小程序上传/详情页 | 历史上有真机使用 | 本轮未重验生产 |
| Route Draw 个人路书 | 最新 `origin/main` 已有探索入口、画线页、贴路预览、保存、路书详情和 GPX/TCX 导出 | 已有一次“保存 → 重开 → 导出 → iGPSPORT 导入”实证 | 当前生产接口和微信体验版仍需重新核对 |
| 公共路线百科 | `route_guides`、路线详情、地图和图片链路已存在 | 有历史真机证据 | 陌生骑手能否快速理解路线尚未验证 |
| 约骑 | 后端、表结构和历史测试保留；小程序前端已删除 | 有多轮历史真机走查 | 后端兼容面仍运行，但当前用户不可从小程序进入 |
| 训练分析 | FTP、PMC、训练分布代码已存在 | 有历史真机反馈 | 不是当前产品投入主线 |
| Route Cognition | DB foundation、内部 writer 和 seed dry-run 已有文档记录 | 只有内部流程证据 | 无公开 API、无 admin UI、无自动 backfill，不是用户可见产品 |

### 状态用词

以后在文档和汇报中统一使用下面四层，不再写含糊的“完成”：

- **代码已实现**：文件和调用链存在。
- **验证已通过**：写清测试、真 PostGIS、开发者工具或真机中的哪一种。
- **已部署**：生产 API / 容器 / migration 已读回确认。
- **用户已可用**：微信包版本、真实账号和完整用户路径已验证。

后一层不能由前一层自动推出。commit、测试、截图、原型和部署记录都不能互相替代。

---

## 2. 仓库地图

```text
app/
  activity/          骑行活动、上传、解析任务和活动读取
  parsing/           GPX / FIT / Strava 统一解析层
  segment/           赛段、匹配和成绩
  notification/      通知与荣誉
  strava/            OAuth、导入、webhook
  training/          FTP、训练负荷、训练分布
  route_book/        路书、路线版本、手画路线、海拔、导出
  route_cognition/   内部路线认知与审核数据层
  meetup/            保留运行的约骑后端与历史数据兼容
  user/              用户与身份
  admin/             管理接口

miniprogram/
  pages/             微信小程序页面
  components/        共用组件
  utils/api.js       小程序 API 单一入口

migrations/versions/ Alembic 迁移
tests/               单元、集成、静态合同和真 PG 测试
scripts/             运维、导入、回填、发布与门禁脚本
content/routes/      路线内容源文件
docs/                产品、规格、架构、运行规则和历史档案
```

模块和表的细节看 [architecture-guide.md](architecture-guide.md)，跨模块运行链路看 [data-flow-guide.md](data-flow-guide.md)。两份文档最后系统性同步停在 2026-06-19，涉及 Route Draw 和之后的代码时必须再 grep 真实实现。

---

## 3. 文档可信度与入口

### A. 当前运行规则

| 文档 | 用途 |
|---|---|
| [AGENTS.md](../AGENTS.md) | VELO 当前项目不变量；Claude 与 Codex 都以此为准 |
| [CLAUDE.md](../CLAUDE.md) | Claude 兼容入口，只指向 `AGENTS.md` |
| [agent-rules/product-decisions.md](agent-rules/product-decisions.md) | 新功能、商业化或用户范围变化时按需核对的产品决策记录 |
| [agent-rules/agent-collaboration.md](agent-rules/agent-collaboration.md) | 历史协作手册；只有当前任务明确引用时才加载 |
| [agent-rules/deploy-sop.md](agent-rules/deploy-sop.md) | 部署唯一执行入口；`commit ≠ ship` |
| [agent-first/README.md](agent-first/README.md) | Agent-First / Orchestrator 文档入口；用于区分领域权威、架构提案、长期蓝图与唯一执行状态，不代表生产实现或发布授权 |

### B. 当前路线工作

| 文档 | 怎么使用 |
|---|---|
| [spec-route-draw-v0.md](spec-route-draw-v0.md) | Route Draw 用户合同、范围和失败场景；“代码侧事实表”是立项时基线，不能当当前现状 |
| [plans/route-draw-v0/README.md](plans/route-draw-v0/README.md) | Route Draw 任务入口和真用验收 |
| [spec-route-export-v0.md](spec-route-export-v0.md) | GPX/TCX 导出合同和海拔门禁 |
| [plans/route-export-v0/README.md](plans/route-export-v0/README.md) | Route Export 任务入口 |
| [reviews/2026-06-25-route-export-v0.md](reviews/2026-06-25-route-export-v0.md) | 当时的代码审查证据和剩余真机风险 |

### C. Route Cognition 内部能力

| 文档 | 怎么使用 |
|---|---|
| [research/README.md](research/README.md) | 路线认知资料索引 |
| [research/route_cognition_v1_1_completion_report.md](research/route_cognition_v1_1_completion_report.md) | DB foundation 完成态 |
| [research/route_cognition_v1_1_operationalization_plan.md](research/route_cognition_v1_1_operationalization_plan.md) | 地基之后的内部 writer / 审核 / seed 边界 |
| [research/route_cognition_v1_1_operationalization_slice_completion_report.md](research/route_cognition_v1_1_operationalization_slice_completion_report.md) | internal writer 与 seed dry-run 证据；First Visible Slice 在该报告中仍是建议的下一阶段 |

### D. 架构、历史和旧规格

| 文档 | 可信度说明 |
|---|---|
| [architecture-guide.md](architecture-guide.md) | 2026-06-19 架构快照；字段和端点必须以代码、migration 为准 |
| [data-flow-guide.md](data-flow-guide.md) | 2026-06-19 数据流快照；未完整覆盖后来的 Route Draw |
| [changelog.md](changelog.md) | 截至 2026-06-19 的历史流水账，不是当前发布状态 |
| [deployment-diary.md](deployment-diary.md) | 历史事故和部署证词；实际部署只按 deploy SOP |
| [tech-debt.md](tech-debt.md) | 已登记债务；处理前先确认条目是否仍存在 |
| [spec-v5.md](spec-v5.md) / [spec-v6.md](spec-v6.md) | 已经过期的阶段规格，只用于追溯当时合同 |
| [real-device-regression-checklist.md](real-device-regression-checklist.md) | 2026-06-13 的一次性回归清单，不是通用当前验收表 |
| [prd/README.md](prd/README.md) | 长期 PRD 索引；旧叙事是历史证词，不能压过较新的用户反馈和拍板 |
| [archive/](archive/) | 已归档规格、计划和交接材料 |

---

## 4. 按任务进入

| 你要做什么 | 起手顺序 |
|---|---|
| 判断下一步产品方向 | 本文 §0-1 → 当前用户反馈 → `product-decisions.md`；方向未定时不要从旧 PRD 直接推导 |
| 改 Route Draw | `spec-route-draw-v0.md` → `plans/route-draw-v0/` 对应任务 → grep `origin/main` 真实页面/API/测试 |
| 改路线导出或海拔 | `spec-route-export-v0.md` → `app/route_book/` → 对应测试；分别验证几何、海拔来源、展示/导出采样和码表行为 |
| 处理约骑遗留后端或历史数据 | `app/meetup/` + migrations + 真实 PostgreSQL 数据关系；不得把保留的后端兼容面重新接回前端 |
| 改骑行上传/解析 | `app/activity/` + `app/parsing/` → data-flow 链路 1 → worker/Redis/PostGIS 验证 |
| 改 schema | models + 当前 Alembic chain + 真 PostgreSQL/PostGIS；SQLite 通过不算数据库验收 |
| 修线上问题 | 先查配置/权限/最远数据源，再查中间链路；部署问题按 deploy SOP |
| 发布用户可见改动 | 代码验证 → push/生产部署 → migration/read-back → 微信预览/上传 → 真机完整路径 |

---

## 5. 本地运行

### 后端开发栈

```bash
docker compose -p velo-dev -f docker-compose.dev.yml up -d --build
docker compose -p velo-dev -f docker-compose.dev.yml exec -T api python3 -m alembic upgrade head
curl http://127.0.0.1:8001/health
```

本地 dev 端口：

- API：`127.0.0.1:8001`
- PostgreSQL：`127.0.0.1:5435`
- Redis：`127.0.0.1:16379`

`docker-compose.dev.yml` 为外部服务提供占位值；要真实调用微信、腾讯位置服务、Strava 等能力时，再从 `.env.example` 创建本地 `.env`，真实密钥绝不能提交。

### 测试和日志

```bash
docker compose -p velo-dev -f docker-compose.dev.yml exec -T api pytest tests/ -q
docker compose -p velo-dev -f docker-compose.dev.yml logs -f api worker
git diff --check
```

小程序默认连接生产域名 `https://api.weiluai.top`。需要测本地 API 时，必须明确切换本地配置并在提交前恢复；开发者工具模拟器、扫码预览、体验版和正式版是四个不同状态。

---

## 6. 维护规则

- README 只保留**当前入口、状态边界和文档路由**，不再复制完整工作流或 skill 说明。
- 状态更新必须写绝对日期，并区分代码、测试、部署和用户可用。
- 新增用户流程时，同时检查 README、architecture/data-flow、运行手册和验收证据。
- 文档中的字段、路由、状态值和命令必须通过 grep、配置或运行结果核实。
- 旧结论被推翻时直接改正文；不要在底部追加一个互相矛盾的新说法。
- 每次阶段收尾运行路径/链接检查，并确认本文没有把历史文档写成当前事实。

## 7. 修订记录

- 2026-07-28：重写项目入口。删除已过时的全流程/skill 教科书和阶段状态；补 Route Draw、Route Export、Route Cognition、证据分层、文档可信度、本地启动和当前产品边界。
